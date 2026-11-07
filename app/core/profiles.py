"""Profiles, sign-in and sessions.

Each person in the home has a profile: a name, an avatar (initial + colour), an
optional email and password, and a role. Profiles without a password open with
one tap. Passwords are hashed with scrypt and never logged or sent back.
Profiles are not a security boundary on a panel with password-free admins:
only make the panel available on a trusted LAN or private tailnet.

Roles: an **admin** can add devices, edit rooms, accounts, settings and profiles;
a **member** only uses the devices their profile is allowed to see ("all", or a
list of device ids). Each profile also keeps its own Home page layout.

Sessions: signing in creates a random token, sent to the browser in an HttpOnly
cookie and stored here only as a SHA-256 hash (data/sessions.json, mode 600). A
browser session lasts 30 days from its last use; a wall-panel session lasts
about a year. Idle screens show the clock or photos without locking the profile.

The viewer of the current request (who is signed in) is kept in a context
variable, `current_viewer`, set by the API's auth middleware. The service reads
it to filter what a member sees. No viewer means the panel itself is acting
(automations, polling): nothing is filtered.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable

log = logging.getLogger("homepanel.auth")

ADMIN, MEMBER = "admin", "member"
ROLES = (ADMIN, MEMBER)
COLORS = ("#f2b35b", "#7cc7a5", "#96a6ff", "#ff8a7a", "#e59ad8", "#6fc3df", "#c3d36b", "#b9a1ff")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
MIN_PASSWORD = 8
MAX_PROFILES = 20

BROWSER_TTL = 30 * 86400          # phones and laptops: 30 days after last use
PANEL_TTL = 400 * 86400           # the wall panel: stays signed in
MAX_SESSIONS = 200

# scrypt cost: ~30 ms on a laptop, a few hundred on a Pi 3. 16 MB of memory.
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LEN = 2 ** 14, 8, 1, 32


class ProfileError(ValueError):
    """A profile can't be saved; the message says why in plain words."""


class AuthError(Exception):
    """Sign-in failed. The message is safe to show (it never says which part was wrong
    when that would help someone guess)."""


class RateLimited(AuthError):
    def __init__(self, retry_after: float):
        mins = max(1, round(retry_after / 60))
        super().__init__(f"Too many tries. Wait {mins} {'minute' if mins == 1 else 'minutes'} and try again.")
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_secret(secret: str) -> str:
    """scrypt$N$r$p$salt$hash: everything needed to check it later, nothing that reveals it."""
    salt = os.urandom(16)
    dk = hashlib.scrypt(secret.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_secret(secret: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, want = stored.split("$")
        assert algo == "scrypt"
        n, r, p = int(n), int(r), int(p)
        want_b = base64.b64decode(want)
        dk = hashlib.scrypt(secret.encode(), salt=base64.b64decode(salt), n=n, r=r, p=p,
                            dklen=len(want_b), maxmem=128 * r * (n + p + 2) + (1 << 20))
    except Exception:
        return False
    return hmac.compare_digest(dk, want_b)


_DUMMY_HASH = None


def _dummy_hash() -> str:
    """Checked against when nobody matches, so a wrong email takes as long as a wrong password."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_secret(secrets.token_hex(8))
    return _DUMMY_HASH


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class RateLimiter:
    """At most `max_failures` failed sign-ins per key (a browser's address, a profile)
    within `window` seconds. A success clears the counts for its keys."""

    def __init__(self, max_failures: int = 8, window: float = 900, clock: Callable[[], float] = time.monotonic):
        self.max_failures, self.window, self.clock = max_failures, window, clock
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = self.clock() - self.window
        times = [t for t in self._fails.get(key, []) if t > cutoff]
        if times:
            self._fails[key] = times
        else:
            self._fails.pop(key, None)
        return times

    def check(self, *keys: str) -> None:
        for k in keys:
            times = self._recent(k)
            if len(times) >= self.max_failures:
                raise RateLimited(times[0] + self.window - self.clock())

    def failure(self, *keys: str) -> None:
        now = self.clock()
        for k in keys:
            self._fails.setdefault(k, []).append(now)
        if len(self._fails) > 5000:            # don't grow forever if someone sprays addresses
            for k in list(self._fails)[:1000]:
                self._recent(k)

    def success(self, *keys: str) -> None:
        for k in keys:
            self._fails.pop(k, None)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Session:
    id: str                    # sha256 of the token; the token itself is only in the cookie
    profile_id: str
    created: float
    expires: float
    panel: bool = False        # the wall panel: long-lived

    @property
    def ttl(self) -> float:
        return PANEL_TTL if self.panel else BROWSER_TTL


class Sessions:
    """Server-side sessions, saved so the wall panel stays signed in across restarts."""

    def __init__(self, path: str | None, clock: Callable[[], float] = time.time):
        self.path, self.clock = path, clock
        self._lock = threading.Lock()
        self._items: dict[str, Session] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path) as f:
                raw = json.load(f)
            now = self.clock()
            for s in raw.get("sessions", []):
                s.pop("locked", None)  # old idle locks no longer block saved sessions
                sess = Session(**s)
                if sess.expires > now:
                    self._items[sess.id] = sess
        except Exception as e:      # a damaged file signs everyone out; it never stops the panel
            log.warning("Couldn't read saved sign-ins (%s). Everyone will need to sign in again.", e)

    def save(self) -> None:
        if not self.path:
            return
        data = {"version": 1, "sessions": [asdict(s) for s in self._items.values()]}
        with self._lock:
            d = os.path.dirname(self.path) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def create(self, profile_id: str, panel: bool = False) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        s = Session(id=token_hash(token), profile_id=profile_id, created=now,
                    expires=now + (PANEL_TTL if panel else BROWSER_TTL), panel=panel)
        self._items[s.id] = s
        if len(self._items) > MAX_SESSIONS:             # drop the oldest
            for old in sorted(self._items.values(), key=lambda x: x.created)[:len(self._items) - MAX_SESSIONS]:
                self._items.pop(old.id, None)
        self.save()
        return token, s

    def get(self, token: str | None) -> Session | None:
        """The live session for a cookie, extended on use (saved at most once a day)."""
        if not token or len(token) > 200:
            return None
        s = self._items.get(token_hash(token))
        if not s:
            return None
        now = self.clock()
        if s.expires <= now:
            self._items.pop(s.id, None)
            self.save()
            return None
        if now + s.ttl - s.expires > 86400:
            s.expires = now + s.ttl
            self.save()
        return s

    def update(self, s: Session, **changes: Any) -> None:
        for k, v in changes.items():
            setattr(s, k, v)
        if "panel" in changes:
            s.expires = self.clock() + s.ttl
        self.save()

    def delete(self, s: Session | None) -> None:
        if s and self._items.pop(s.id, None):
            self.save()

    def delete_for_profile(self, profile_id: str) -> None:
        gone = [k for k, s in self._items.items() if s.profile_id == profile_id]
        for k in gone:
            self._items.pop(k)
        if gone:
            self.save()

    def all(self) -> list[Session]:
        return list(self._items.values())


# ---------------------------------------------------------------------------
# Who is looking
# ---------------------------------------------------------------------------

@dataclass
class Viewer:
    """The signed-in person for one request."""
    profile: dict
    session: Session | None = None
    auto: bool = False                       # demo mode without sign-in: acting as the owner

    @property
    def id(self) -> str:
        return self.profile["id"]

    @property
    def is_admin(self) -> bool:
        return self.profile.get("role") == ADMIN

    def sees(self, device_id: str) -> bool:
        if self.is_admin or self.profile.get("devices", "all") == "all":
            return True
        return device_id in set(self.profile.get("devices") or [])


current_viewer: contextvars.ContextVar[Viewer | None] = contextvars.ContextVar("current_viewer", default=None)


def sees(device_id: str) -> bool:
    """Can the current request's viewer see this device? (No viewer = the panel itself: yes.)"""
    v = current_viewer.get()
    return v is None or v.sees(device_id)


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def initial(name: str) -> str:
    name = (name or "").strip()
    return name[:1].upper() if name else "?"


class Profiles:
    """The list of profiles (kept in the main store) plus sign-in and sessions."""

    def __init__(self, store, sessions: Sessions, limiter: RateLimiter | None = None):
        self.store = store
        self.sessions = sessions
        self.limiter = limiter or RateLimiter()

    # --- reading -------------------------------------------------------------
    @property
    def items(self) -> list[dict]:
        return self.store.profiles

    def get(self, profile_id: str) -> dict:
        p = next((p for p in self.items if p["id"] == profile_id), None)
        if not p:
            raise KeyError(profile_id)
        return p

    def find(self, profile_id: str | None) -> dict | None:
        return next((p for p in self.items if p["id"] == profile_id), None)

    def admins(self) -> list[dict]:
        return [p for p in self.items if p.get("role") == ADMIN]

    def owner(self) -> dict | None:
        admins = self.admins()
        return admins[0] if admins else None

    def public(self, p: dict, *, full: bool = True) -> dict:
        """What the UI may see of a profile. Never the hashes. `full=False` is the picker
        shown before sign-in: name, avatar and how to sign in, nothing else."""
        out = {"id": p["id"], "name": p["name"], "initial": initial(p["name"]), "color": p.get("color") or COLORS[0],
               "has_password": bool(p.get("password_hash"))}
        if full:
            out.update({"email": p.get("email") or "", "role": p.get("role", MEMBER),
                        "devices": p.get("devices", "all") if p.get("role") != ADMIN else "all",
                        "custom_layout": bool(p.get("home_layout"))})
        return out

    def picker(self) -> list[dict]:
        return [self.public(p, full=False) for p in self.items]

    # --- migration -------------------------------------------------------------
    def migrate(self, settings: dict) -> bool:
        """Preserve profiles and passwords, retire PINs, and create an Owner if needed."""
        changed = "lock_after_minutes" in settings
        settings.pop("lock_after_minutes", None)
        for p in self.items:
            if "pin_hash" in p:
                p.pop("pin_hash")
                changed = True
        if self.items:
            if changed:
                self.store.save()
            return changed
        layout = settings.get("home_layout")
        self.store.profiles = [{
            "id": uuid.uuid4().hex[:10], "name": "Owner", "color": COLORS[0], "email": "", "role": ADMIN,
            "password_hash": None, "devices": "all",
            "home_layout": json.loads(json.dumps(layout)) if layout else None, "created": time.time(),
        }]
        self.store.save()
        log.info("Created the Owner profile. Choose it on the panel to get started.")
        return True

    # --- editing ---------------------------------------------------------------
    def _clean(self, data: dict, current: dict | None) -> dict:
        if "pin" in data:
            raise ProfileError("Profile PINs are no longer used. Reload the panel and save again.")
        p = dict(current or {})
        p.pop("pin_hash", None)
        if "name" in data or not current:
            name = " ".join(str(data.get("name") or "").split())[:24]
            if not name:
                raise ProfileError("Give the profile a name.")
            if any(o["name"].lower() == name.lower() and o["id"] != p.get("id") for o in self.items):
                raise ProfileError(f"There's already a profile called {name}.")
            p["name"] = name
        if "color" in data or not current:
            color = str(data.get("color") or "")
            p["color"] = color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else COLORS[len(self.items) % len(COLORS)]
        if "email" in data or not current:
            email = str(data.get("email") or "").strip().lower()
            if email and not EMAIL_RE.match(email):
                raise ProfileError("That email address doesn't look right.")
            if email and any(o.get("email") == email and o["id"] != p.get("id") for o in self.items):
                raise ProfileError("Another profile already uses that email address.")
            p["email"] = email
        if "role" in data or not current:
            role = data.get("role") or MEMBER
            if role not in ROLES:
                raise ProfileError("Role should be admin or member.")
            p["role"] = role
        if "devices" in data or not current:
            dev = data.get("devices", "all")
            if dev != "all":
                if not isinstance(dev, list) or not all(isinstance(x, str) for x in dev):
                    raise ProfileError("Devices should be \"all\" or a list of device ids.")
                dev = sorted(set(dev))
            p["devices"] = dev
        # A password value sets it, "" or missing keeps it, None removes it.
        if data.get("password") is not None and data.get("password") != "":
            pw = str(data["password"])
            if len(pw) < MIN_PASSWORD:
                raise ProfileError(f"A password needs at least {MIN_PASSWORD} characters.")
            if len(pw) > 256:
                raise ProfileError("That password is too long.")
            p["password_hash"] = hash_secret(pw)
        elif "password" in data and data["password"] is None:
            p["password_hash"] = None
        if p.get("password_hash") and not p.get("email"):
            raise ProfileError("Add an email address to sign in with a password.")
        return p

    def _check_admins(self, profiles: list[dict]) -> None:
        if not any(p.get("role") == ADMIN for p in profiles):
            raise ProfileError("The panel needs at least one admin.")

    def create(self, data: dict) -> dict:
        if len(self.items) >= MAX_PROFILES:
            raise ProfileError(f"The panel can hold up to {MAX_PROFILES} profiles.")
        p = self._clean(data, None)
        p.update({"id": uuid.uuid4().hex[:10], "home_layout": None, "created": time.time()})
        p.setdefault("password_hash", None)
        self.store.profiles = [*self.items, p]
        self.store.save()
        log.info("Profile added: %s (%s)", p["name"], p["role"])
        return p

    def update(self, profile_id: str, data: dict) -> dict:
        current = self.get(profile_id)
        p = self._clean(data, current)
        after = [p if o["id"] == profile_id else o for o in self.items]
        self._check_admins(after)
        self.store.profiles = after
        self.store.save()
        log.info("Profile changed: %s", p["name"])
        return p

    def delete(self, profile_id: str) -> None:
        p = self.get(profile_id)
        after = [o for o in self.items if o["id"] != profile_id]
        self._check_admins(after)
        self.store.profiles = after
        self.store.save()
        self.sessions.delete_for_profile(profile_id)
        log.info("Profile removed: %s", p["name"])

    def set_layout(self, profile_id: str, layout: dict | None) -> None:
        self.get(profile_id)["home_layout"] = layout
        self.store.save()

    def forget_device(self, device_id: str) -> None:
        for p in self.items:
            if isinstance(p.get("devices"), list) and device_id in p["devices"]:
                p["devices"] = [d for d in p["devices"] if d != device_id]

    # --- signing in ------------------------------------------------------------
    def check_credentials(self, data: dict, client: str) -> dict:
        """Blocking (scrypt): run in a thread. Returns the profile or raises AuthError."""
        if "pin" in data:
            raise AuthError("Profile PINs are no longer used. Reload the panel and choose your profile.")
        email = str(data.get("email") or "").strip().lower()
        pid = data.get("profile_id")
        password = data.get("password")
        p = self.find(pid) if pid else next((o for o in self.items if email and o.get("email") == email), None)
        keys = [f"ip:{client}"] + ([f"profile:{p['id']}"] if p else [f"email:{email}"] if email else [])
        self.limiter.check(*keys)
        if pid and p and not p.get("password_hash") and password in (None, ""):
            ok = True
            wrong = ""
        elif password not in (None, ""):
            stored = p.get("password_hash") if p and (p.get("email") or not email) else None
            ok = verify_secret(str(password), stored or _dummy_hash()) and bool(stored)
            wrong = "That email and password don't match." if email else "That password isn't right."
        else:
            ok = False
            wrong = "Enter your password." if p and p.get("password_hash") else "Choose an available profile."
        if not ok or not p:
            self.limiter.failure(*keys)
            log.warning("Sign-in failed from %s", client)
            raise AuthError(wrong)
        self.limiter.success(*keys)
        log.info("%s signed in", p["name"])
        return p

    def viewer_for(self, token: str | None) -> Viewer | None:
        s = self.sessions.get(token)
        if not s:
            return None
        p = self.find(s.profile_id)
        if not p:
            self.sessions.delete(s)
            return None
        return Viewer(profile=p, session=s)


def visible(devices: Iterable[Any], viewer: Viewer | None) -> list:
    return [d for d in devices if viewer is None or viewer.sees(d.id)]
