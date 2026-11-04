"""
Voice commands: a sentence in, device commands out.

    "turn off the lamp and vacuum the kitchen"
        │  parser.parse(text, home)     rules-based today (RulesParser); see Parser to plug in another
        ▼
    Plan  steps [device + generic Action + value], or a question ("Which lamp?"), or "Are you sure?"
        │  Voice.handle()
        ▼
    HomeService.command() / run_scene() / all_off()   the normal pipeline: validation, logs, retries,
        ▼                                             and any access rules added with service.use()
    {"say": "Turned off the Floor lamp. The Robot vacuum is cleaning the Kitchen.", ...}

Everything the parser knows comes from the generic vocabulary: device names, kinds and rooms,
capabilities (Cap), and the options each device lists in device.meta (apps, inputs, sound modes,
vacuum rooms, suction levels, clean modes, station jobs). It never knows about brands.

Speech to text happens in the browser (Web Speech API). See Transcriber for where an offline
recogniser on the panel itself (Vosk, whisper.cpp) would fit.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .adapter import Action, AdapterError, Cap, Clean, Device, Key, Kind

log = logging.getLogger("homepanel.voice")

MAX_TEXT = 300


# ---------------------------------------------------------------------------
# What a parser produces
# ---------------------------------------------------------------------------

@dataclass
class Step:
    """One thing to do. kind: command | scene | all_off | room_off | query."""
    kind: str = "command"
    device_id: str = ""
    action: str = ""
    value: Any = None
    target: str | None = None    # scene id, or the room for room_off / query (None = the whole home)
    repeat: int = 1              # e.g. volume_up three times
    clause: int = 0              # steps from one clause run together; clauses run in order


@dataclass
class Choice:
    label: str                   # what the button says, e.g. "Floor lamp"
    text: str                    # the sentence to send back when it's picked
    detail: str = ""             # e.g. the room


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    question: str = ""           # set when the sentence could mean several devices
    choices: list[Choice] = field(default_factory=list)
    confirm: str = ""            # set when a step is risky: run it only after a yes
    notes: list[str] = field(default_factory=list)   # things to say besides what was done
    error: str = ""              # nothing understood: what to tell the person


@dataclass
class Home:
    """What a parser may look at. Devices are read-only here."""
    devices: list[Device]
    rooms: list[str]
    scenes: list[dict]


class Parser(Protocol):
    """Turns a sentence into a Plan. RulesParser is the built-in one. Something smarter (for example a
    language model given the device list and the Action vocabulary) can replace it with
    `service.voice.parser = MyParser()`; it must only return Steps, never call devices itself, so the
    service still runs everything through its normal pipeline."""

    async def parse(self, text: str, home: Home) -> Plan: ...


class Transcriber(Protocol):
    """Speech to text on the panel itself, for screens whose browser can't do it (not built yet).
    An offline recogniser such as Vosk or whisper.cpp would implement this; a route such as
    POST /api/v1/voice/audio would call it and pass the text to Voice.handle(). Nothing else changes."""

    async def transcribe(self, audio: bytes, content_type: str) -> str: ...


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------

ONES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}

# Words that mean the same thing when matching names. A match through a synonym scores a little
# lower than the word itself, so "lamp" picks lamps before other lights.
SYNONYMS = [
    {"light", "lamp", "bulb", "lighting"},
    {"tv", "telly", "television", "tele", "telie"},
    {"vacuum", "robot", "hoover", "vac", "roomba", "vacuumer", "cleaner"},
    {"plug", "socket", "outlet"},
    {"speaker", "soundbar"},
    {"bin", "dustbin"},
]
SYN_OF = {w: g for g in SYNONYMS for w in g}

# Words that name a kind of device: "the lights" means every light.
KIND_WORDS = {
    Kind.LIGHT: SYNONYMS[0], Kind.TV: SYNONYMS[1], Kind.VACUUM: SYNONYMS[2], Kind.PLUG: SYNONYMS[3],
    Kind.SPEAKER: SYNONYMS[4], Kind.FAN: {"fan"}, Kind.SWITCH: {"switch"},
}
KIND_LABEL = {Kind.TV: "TV", Kind.LIGHT: "light", Kind.PLUG: "plug", Kind.SPEAKER: "speaker",
              Kind.VACUUM: "vacuum", Kind.FAN: "fan", Kind.SWITCH: "switch"}

ROOM_ALIASES = {"lounge": "living room", "family room": "living room", "sitting room": "living room",
                "front room": "living room", "master bedroom": "bedroom"}

FILLER = {"the", "my", "a", "an", "our", "this", "that", "those", "these", "please", "of", "in", "at",
          "all", "both", "every", "each", "some", "for", "with", "device", "devices"}
PRONOUNS = {"it", "them", "they", "that", "those", "this", "one"}
WHOLE = {"everything", "stuff", "all", "devices", "things", "everything else"}
HOUSE = {"house", "home", "flat", "apartment", "everywhere", "whole house", "the house", "the whole house",
         "the home", "all rooms", "all the rooms", "everything", "floor", "floors", "the floor", "the floors"}

# Colors a light can be made. Whites are kelvin (color_temp); the rest are RGB.
WHITES = {"warm white": 2700, "soft white": 2700, "warm": 2700, "candle": 2200, "candlelight": 2200,
          "candle light": 2200, "cool white": 5000, "cold white": 5000, "cool": 5000, "daylight": 6000,
          "day light": 6000, "white": 4000, "neutral white": 4000, "bright white": 5000}
COLORS = {
    "red": (255, 30, 20), "orange": (255, 130, 20), "yellow": (255, 220, 40), "green": (40, 220, 70),
    "lime": (160, 255, 40), "blue": (40, 90, 255), "light blue": (110, 180, 255), "sky blue": (110, 190, 255),
    "dark blue": (20, 40, 200), "navy": (20, 30, 160), "cyan": (40, 230, 230), "teal": (20, 180, 170),
    "turquoise": (50, 220, 200), "purple": (150, 60, 255), "violet": (140, 80, 255),
    "indigo": (80, 50, 220), "lavender": (190, 150, 255), "pink": (255, 90, 180), "magenta": (255, 40, 220),
    "hot pink": (255, 50, 150), "gold": (255, 180, 30), "amber": (255, 150, 20),
}
COLOR_WORDS = sorted([*WHITES, *COLORS], key=len, reverse=True)

VERBS = {"turn", "switch", "set", "make", "start", "stop", "pause", "resume", "play", "run", "activate",
         "open", "launch", "put", "change", "dim", "brighten", "mute", "unmute", "send", "vacuum", "clean",
         "mop", "hoover", "sweep", "dock", "what", "whats", "which", "is", "are", "lower", "raise",
         "increase", "decrease", "go", "find", "locate", "empty", "wash", "shut", "kill", "power", "watch",
         "show", "next", "previous", "louder", "quieter", "return", "bring", "take", "trigger", "begin",
         "continue", "unpause", "rewind", "where", "wheres", "silence", "lights", "light", "volume"}
STRONG = re.compile(r"\b(volume|louder|quieter|softer|mute|unmute|channel)\b|\b(on|off|up|down)$")

# Which device.meta list each option-taking action reads, in the order "set X to Y" tries them.
OPTION_ACTIONS = [("inputs", Action.SET_INPUT, Cap.INPUTS), ("sound_modes", Action.SET_SOUND_MODE, Cap.SOUND_MODE),
                  ("suction_levels", Action.SET_SUCTION, Cap.SUCTION), ("clean_modes", Action.SET_CLEAN_MODE, Cap.CLEAN_MODE),
                  ("apps", Action.LAUNCH_APP, Cap.APPS)]
OPTION_NOISE = {"mode", "input", "source", "setting", "level", "power", "suction", "sound", "the", "to", "app",
                "channel", "on"}


def _numbers(tokens: list[str]) -> list[str]:
    """'twenty five' → '25', 'a hundred' → '100'. Other words pass through."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "a" and i + 1 < len(tokens) and tokens[i + 1] == "hundred":
            t, tokens = "one", tokens[:i] + ["one"] + tokens[i + 1:]
        if t in ONES or t in TENS:
            total, j = 0, i
            while j < len(tokens):
                w = tokens[j]
                if w in TENS and total % 100 == 0:
                    total += TENS[w]
                elif w in ONES and total % 10 == 0 and not (total % 100 and ONES[w] >= 10):
                    total += ONES[w]
                elif w == "hundred" and 0 < total < 10:
                    total *= 100
                elif w == "and" and j + 1 < len(tokens) and total >= 100 and tokens[j + 1] in {*ONES, *TENS}:
                    pass
                else:
                    break
                j += 1
            out.append(str(total))
            i = j
            continue
        out.append(t)
        i += 1
    return out


def normalize(text: str) -> str:
    """Lowercase, plain words, numbers as digits: "Set the lamp to thirty %" → "set the lamp to 30 percent"."""
    s = str(text or "").lower().replace("’", "'")
    s = re.sub(r"\b(?:[a-z]\.){2,}", lambda m: m[0].replace(".", ""), s)     # T.V. → tv
    s = s.replace("'", "").replace("&", " and ").replace("+", " plus ").replace("%", " percent ")
    s = re.sub(r"[,;.!?:]+", " and ", s)          # pauses between commands
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", s)   # hdmi2 → hdmi 2, 30percent → 30 percent
    s = re.sub(r"\bper cent\b", "percent", s)
    s = re.sub(r"\bsound bar\b", "soundbar", s)
    s = re.sub(r"\bt v\b", "tv", s)
    s = re.sub(r"\btv s\b", "tvs", s)
    toks = _numbers(s.split())
    s = " ".join(toks)
    s = re.sub(r"^(and )+|( and)+$", "", s)
    return re.sub(r"( and)+ ", " and ", s).strip()


def stem(t: str) -> str:
    if t in ("tvs", "tellys"):
        return "tv"
    if len(t) > 3 and t.endswith("es") and t[:-2].endswith(("sh", "ch", "x")):
        return t[:-2]                       # switches, boxes
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is")):
        return t[:-1]
    return t


def tok_sim(a: str, b: str) -> float:
    """How well one spoken word matches one word of a name (0-1)."""
    a, b = stem(a), stem(b)
    if a == b:
        return 1.0
    if a in SYN_OF and SYN_OF[a] is SYN_OF.get(b):
        return 0.85
    if len(a) >= 4 and len(b) >= 4:
        r = difflib.SequenceMatcher(None, a, b).ratio()
        if r >= 0.8:
            return r * 0.9
    return 0.0


def name_score(words: list[str], name: str, kind: str | None = None) -> tuple[float, float]:
    """(coverage, completeness): how many spoken words the name explains, and how much of the name was said."""
    if not words:
        return 0.0, 0.0
    nw = normalize(name).split()
    if not nw:
        return 0.0, 0.0
    if "".join(words) == "".join(nw):          # "you tube" = "YouTube"
        return 1.0, 1.0
    kind_words = KIND_WORDS.get(kind or "", set())
    total = 0.0
    used: set[int] = set()
    for w in words:
        best, at = 0.0, -1
        for i, n in enumerate(nw):
            s = tok_sim(w, n)
            if s > best:
                best, at = s, i
        if stem(w) in kind_words and best < 0.9:
            best, at = 0.9, -1
        total += best
        if best >= 0.8 and at >= 0:
            used.add(at)
    return total / len(words), len(used) / len(nw)


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _the(d: Device | str) -> str:
    return f"the {d.name if isinstance(d, Device) else d}"


def _The(d: Device | str) -> str:     # at the start of a sentence; the name keeps its own capitals
    return "T" + _the(d)[1:]


# ---------------------------------------------------------------------------
# The rules-based parser
# ---------------------------------------------------------------------------

class Ask(Exception):
    """The sentence could mean several devices or options: ask which."""

    def __init__(self, question: str, choices: list[tuple[str, str, str]]):
        super().__init__(question)
        self.question = question
        self.choices = choices          # (label, replacement clause, detail)


class Fail(Exception):
    """This part of the sentence can't be done; the message is said to the person."""


@dataclass
class Targets:
    devices: list[Device]
    room: str | None = None          # a room was named
    whole_room: bool = False         # nothing but the room was named: "turn off the kitchen"
    plural: bool = False
    rooms: list[str] = field(default_factory=list)       # every room named on its own
    named: list[Device] = field(default_factory=list)    # devices named directly (not as a whole room)


class _Ctx:
    def __init__(self, home: Home):
        self.home = home
        self.last: list[Device] = []
        self.clause = ""
        self.notes: list[str] = []
        self.confirm: list[str] = []

    def room_of(self, d: Device) -> str:
        return d.room if d.room in self.home.rooms else ""


class RulesParser:
    """Understands everyday sentences with a list of rules, tried in order. Each rule either returns
    steps, returns None (not mine), raises Ask (which one?) or raises Fail (can't do that)."""

    async def parse(self, text: str, home: Home) -> Plan:
        return self.parse_now(text, home)

    # --- the whole sentence ------------------------------------------------
    def parse_now(self, text: str, home: Home) -> Plan:
        ctx = _Ctx(home)
        clauses = self._clauses(normalize(text), home)
        if not clauses:
            return Plan(error="I didn't catch anything. Try again?")
        plan = Plan()
        failed: list[str] = []
        for i, clause in enumerate(clauses):
            ctx.clause = clause
            try:
                steps = self._clause(clause, ctx)
            except Ask as a:
                def sentence(replacement: str, at: int = i) -> str:
                    return " and ".join(replacement if j == at else c for j, c in enumerate(clauses))
                return Plan(question=a.question,
                            choices=[Choice(label, sentence(repl), detail) for label, repl, detail in a.choices])
            except Fail as f:
                failed.append(str(f))
                continue
            for s in steps:
                s.clause = i
            plan.steps += steps
        plan.notes = ctx.notes + failed
        if not plan.steps:
            plan.error = " ".join(plan.notes) or "Sorry, I didn't understand that."
            plan.notes = []
        if ctx.confirm and plan.steps:
            plan.confirm = " ".join(ctx.confirm)
        return plan

    def _clauses(self, text: str, home: Home) -> list[str]:
        """Split "turn off the lamp and start the vacuum" in two, but keep "vacuum the kitchen and hall"
        and "turn off the lamp and the TV" whole (their second half has no verb of its own)."""
        names = [normalize(n) for n in self._all_names(home)]
        for n in names:                                  # names with "and" in them stay whole
            if " and " in n:
                text = text.replace(n, n.replace(" and ", " nameand "))
        parts = [p.strip() for p in re.split(r"\b(?:and then|and also|and|then|also|after that)\b", text)]
        clauses: list[str] = []
        for p in parts:
            if not p:
                continue
            first = p.split()[0]
            if not clauses or first in VERBS or STRONG.search(p):
                if first not in VERBS and re.search(r"\b(on|off)$", p) and clauses:
                    p = "turn " + p                      # "turn the lamp on and the TV off"
                clauses.append(p)
            else:
                clauses[-1] += " and " + p
        return [c.replace(" nameand ", " and ") for c in clauses]

    @staticmethod
    def _all_names(home: Home) -> list[str]:
        out = [d.name for d in home.devices] + [s.get("name", "") for s in home.scenes] + list(home.rooms)
        for d in home.devices:
            for key in ("apps", "inputs", "sound_modes", "suction_levels", "clean_modes", "rooms", "station_actions"):
                out += [str(o.get("name", "")) for o in d.meta.get(key, []) if isinstance(o, dict)]
        return out

    def _clause(self, c: str, ctx: _Ctx) -> list[Step]:
        c = re.sub(r"^(?:(?:hey|hi|ok|okay|so|um|uh|now)\s+)*(?:(?:home ?panel|panel)\s+)?", "", c)
        c = re.sub(r"^(?:(?:please|can you|could you|would you|will you|i want to|i wanna|id like to|"
                   r"i would like to|lets|let us|go ahead and|just)\s+)+", "", c)
        c = re.sub(r"(?:\s+(?:please|for me|now|right now|thanks|thank you|again))+$", "", c).strip()
        if not c:
            raise Fail("I didn't catch anything.")
        for rule in (self._query, self._everything, self._scene, self._mute, self._volume, self._channel,
                     self._vacuum_rooms, self._dock, self._locate, self._station, self._app, self._media_key,
                     self._start, self._set, self._dim, self._up_down, self._power, self._bare):
            steps = rule(c, ctx)
            if steps is not None:
                return steps
        raise Fail(f"Sorry, I don't know how to “{c}”.")

    # --- finding devices ---------------------------------------------------
    def _take_room(self, words: list[str], ctx: _Ctx) -> tuple[str | None, list[str]]:
        """Find a room name in the words; return it and the words without it."""
        rooms = sorted(ctx.home.rooms, key=lambda r: -len(r))
        text = " ".join(words)
        for alias, real in ROOM_ALIASES.items():
            if re.search(rf"\b{alias}\b", text) and not any(normalize(r) == alias for r in rooms):
                text = re.sub(rf"\b{alias}\b", real, text)
        words = text.split()
        for r in rooms:
            rw = normalize(r).split()
            n = len(rw)
            for i in range(len(words) - n + 1):
                if all(tok_sim(words[i + k], rw[k]) >= 0.85 for k in range(n)):
                    rest = words[:i] + words[i + n:]
                    if rest[-1:] == ["room"] and rw[-1] != "room":
                        rest = rest[:-1]
                    while i > 0 and i - 1 < len(rest) and rest[i - 1] in ("in", "the", "of", "from"):
                        rest.pop(i - 1)
                        i -= 1
                    return r, rest
        return None, words

    def _targets(self, phrase: str, ctx: _Ctx, need: str | None = None, prefer_on: bool = False,
                 pool: list[Device] | None = None, what: str = "") -> Targets:
        """The devices a phrase names, e.g. "the lamp", "kitchen lights", "the tv in the bedroom",
        "the lamp and the tv", "it". Raises Ask when one device was meant but several fit."""
        phrase = re.sub(r"^(?:on|for|of|to) (?=the |my )", "", phrase.strip())
        parts = [p for p in re.split(r"\band\b", phrase) if p.strip()] or [""]
        if len(parts) > 1:
            out = Targets([], plural=True)
            for p in parts:
                t = self._targets(p, ctx, need, prefer_on, pool, what)
                out.devices += [d for d in t.devices if d not in out.devices]
                out.rooms += [r for r in t.rooms if r not in out.rooms]
                out.named += [d for d in t.named if d not in out.named]
            out.whole_room = bool(out.rooms) and not out.named
            out.room = out.rooms[0] if out.rooms else None
            ctx.last = out.devices
            return out
        raw = phrase.strip()
        pool = list(ctx.home.devices if pool is None else pool)
        words = raw.split()
        pronoun = bool(words) and all(w in PRONOUNS or w == "the" for w in words)
        plural = any(w in ("all", "every", "both", "everything") for w in words) or any(
            w.endswith("s") and stem(w) in SYN_OF for w in words if w not in ("this", "is"))
        words = [w for w in words if w not in FILLER or w == "all" and len(words) == 1]
        words = [w for w in words if w != "all"]

        if pronoun or not words:
            if pronoun and ctx.last:
                found = [d for d in ctx.last if not need or need in d.caps]
                if not found:
                    raise Fail(f"{_The(ctx.last[0])} can't do that.")
                return Targets(found, plural=len(found) > 1, named=found)
            if pronoun:
                raise Fail(f"I'm not sure what “{raw.removeprefix('the ')}” is. Say its name, like “the floor lamp”.")
            found = self._default(pool, raw, ctx, need, prefer_on, what)
            return Targets(found, named=found)

        joined = " ".join(words)
        exact = [d for d in pool if normalize(d.name) == joined]
        if exact:
            return self._pick(exact, raw, ctx, need, prefer_on, plural, what)

        room, words = self._take_room(words, ctx)
        if room is not None:
            pool = [d for d in pool if ctx.room_of(d) == room]
            if not words or all(w in WHOLE for w in words):
                found = [d for d in pool if not need or need in d.caps]
                if not found:
                    raise Fail(f"Nothing in the {room} can do that.")
                ctx.last = found
                return Targets(found, room=room, whole_room=True, plural=True, rooms=[room])
            exact = [d for d in pool if normalize(d.name) == " ".join(words)]
            if exact:
                return self._pick(exact, raw, ctx, need, prefer_on, plural, what)

        scored = []
        for d in pool:
            cov, comp = name_score(words, d.name, d.kind)
            if cov >= 0.6:
                kind_bonus = 0.3 if any(stem(w) in KIND_WORDS.get(d.kind, ()) for w in words) else 0
                scored.append((cov * 2 + kind_bonus + comp * 0.1, cov, d))   # how much of the name: a tie-break only
        if not scored:
            where = f" in the {room}" if room else ""
            raise Fail(f"I couldn't find “{' '.join(words)}”{where}.")
        scored.sort(key=lambda x: -x[0])
        if plural:
            found = [d for _s, _c, d in scored]
        else:
            top = scored[0][0]
            found = [d for s, _c, d in scored if s >= top - 0.05]
        return self._pick(found, raw, ctx, need, prefer_on, plural, what, room=room, words=words)

    def _pick(self, found: list[Device], raw: str, ctx: _Ctx, need: str | None, prefer_on: bool,
              plural: bool, what: str, room: str | None = None, words: list[str] | None = None) -> Targets:
        if need:
            able = [d for d in found if need in d.caps]
            if not able:
                raise Fail(f"{_The(found[0])} can't do that." if len(found) == 1
                           else "None of those can do that.")
            found = able
        if len(found) > 1 and not plural:
            if prefer_on:
                want = prefer_on != "off"     # "turn on the TV": the one that's off
                on = [d for d in found if bool(d.state.get("on")) == want and d.state.get("online") is not False]
                if len(on) == 1:
                    found = on
            if len(found) > 1:
                word = self._word(words or raw.split())
                raise self._ask(found, raw, ctx, what if word == "one" and what else word)
        ctx.last = found
        return Targets(found, room=room, plural=plural, named=list(found))

    def _default(self, pool: list[Device], raw: str, ctx: _Ctx, need: str | None, prefer_on: bool, what: str):
        """Nothing was named ("volume up"): use the one device that fits, or ask."""
        able = [d for d in pool if not need or need in d.caps]
        if prefer_on:
            on = [d for d in able if d.state.get("on") and d.state.get("online") is not False]
            able = on or able
        if not able:
            raise Fail("Nothing here can do that.")
        if len(able) > 1:
            raise self._ask(able, raw, ctx, what)
        ctx.last = able
        return able

    @staticmethod
    def _word(words: list[str]) -> str:
        for w in reversed(words):
            if stem(w) in SYN_OF or stem(w) in ("fan", "switch"):
                for kind, ws in KIND_WORDS.items():
                    if stem(w) in ws:
                        return "TV" if kind == Kind.TV else stem(w) if stem(w) in ("lamp", "light") else KIND_LABEL[kind]
        return "one"

    def _ask(self, found: list[Device], raw: str, ctx: _Ctx, word: str) -> Ask:
        names = [d.name for d in found]
        choices = []
        for d in found[:8]:
            name = normalize(d.name)
            if names.count(d.name) > 1 and ctx.room_of(d):
                name += f" in the {normalize(ctx.room_of(d))}"
            if raw.strip():
                repl = re.sub(rf"\b{re.escape(raw.strip())}\b", f"the {name}", ctx.clause, count=1)
            else:
                repl = f"{ctx.clause} on the {name}"
            choices.append((d.name, repl, ctx.room_of(d)))
        return Ask(f"Which {word or 'one'}?", choices)

    # --- matching options (apps, inputs, sound modes, vacuum rooms …) -------------------------------
    @staticmethod
    def _options(phrase: str, options: list[dict], strict: bool = False) -> list[dict]:
        words = [w for w in phrase.split() if w not in ("the", "a", "my")]
        if not words:
            return []
        best, out = 0.0, []
        for o in options or []:
            if not isinstance(o, dict):
                continue
            scores = [name_score(words, str(o.get(k, ""))) for k in ("name", "id")]
            cov, comp = max(scores)
            if cov < (0.85 if strict else 0.75) or comp < (0.5 if strict else 0.34):
                continue
            s = cov * 2 + comp
            if s > best + 0.05:
                best, out = s, [o]
            elif s >= best - 0.05:
                out.append(o)
        return out

    def _option_devices(self, phrase: str, key: str, cap: str, ctx: _Ctx, pool=None):
        """Devices that list an option matching the phrase: [(device, option)]."""
        out = []
        for d in (ctx.home.devices if pool is None else pool):
            if cap in d.caps:
                hits = self._options(phrase, d.meta.get(key, []))
                if len(hits) == 1:
                    out.append((d, hits[0]))
                elif len(hits) > 1:
                    raise Ask(f"Which {key.rstrip('s').replace('_', ' ')}?",
                              [(str(h["name"]), re.sub(rf"\b{re.escape(phrase)}\b", normalize(str(h["name"])),
                                                       ctx.clause, count=1), "") for h in hits])
        return out

    # --- the rules ---------------------------------------------------------
    def _query(self, c: str, ctx: _Ctx):
        m = re.match(r"^(?:what|whats|which|tell me what)(?: is| are| s)?(?: things| devices| lights| stuff)?"
                     r"(?: is| are)? (?:on|running|playing|happening)(?: right now)?(?: (?:in|at) (?P<r>.+))?$", c)
        if m:
            room = None
            if m["r"]:
                room, rest = self._take_room(m["r"].split(), ctx)
                if room is None:
                    raise Fail(f"I don't know a room called “{m['r'].removeprefix('the ')}”.")
            return [Step("query", target=room)]
        m = re.match(r"^(?:is|are) (?P<t>.+?) (?:on|off|running|playing)$", c)
        if m:
            t = self._targets(m["t"], ctx)
            if t.whole_room:
                return [Step("query", target=t.room)]
            return [Step("query", device_id=d.id) for d in t.devices]
        return None

    def _everything(self, c: str, ctx: _Ctx):
        every = r"(?:everything|all|all devices|all the devices|every device|the whole house|the house|it all)"
        verb = r"(?:turn|switch|shut|power|put)"
        if re.match(rf"^(?:{verb} {every} off|{verb} off {every}|all off|everything off|shut down {every}|"
                    rf"shut {every} down|power down {every})$", c):
            on = [d for d in ctx.home.devices if Cap.POWER in d.caps and d.state.get("on") and not d.keep_on]
            n = len(on)
            ctx.confirm.append(f"Turn off everything? {n} {'device is' if n == 1 else 'devices are'} on."
                               if n else "Turn off everything?")
            return [Step("all_off")]
        if re.match(rf"^(?:{verb} {every} on|{verb} on {every}|all on|everything on)$", c):
            raise Fail("I won't turn everything on at once. Name a room or a device, like “turn on the kitchen”.")
        return None

    def _scene(self, c: str, ctx: _Ctx):
        if not ctx.home.scenes:
            return None
        m = re.match(r"^(?P<v>run|start|activate|trigger|begin|do|play|set|turn on|switch on|put on|go to|"
                     r"its|it is|time for|scene|start the scene|run the scene)?\s*(?:the )?(?P<s>.+?)"
                     r"(?P<k> scene| mode| routine)?$", c)
        if not m or not m["s"]:
            return None
        explicit = m["v"] in ("run", "activate", "trigger", "scene") or bool(m["k"])
        hits = self._options(m["s"], [{"id": s["id"], "name": s.get("name", "")} for s in ctx.home.scenes],
                             strict=not explicit)
        if len(hits) == 1:
            return [Step("scene", target=hits[0]["id"])]
        if len(hits) > 1:
            raise Ask("Which scene?", [(h["name"], f"run {normalize(h['name'])}", "") for h in hits])
        if m["v"] in ("run", "activate", "trigger", "scene") and not self._looks_like_device(m["s"], ctx):
            raise Fail(f"I don't know a scene called “{m['s']}”.")
        return None

    def _looks_like_device(self, phrase: str, ctx: _Ctx) -> bool:
        words = [w for w in phrase.split() if w not in FILLER]
        return any(name_score(words, d.name, d.kind)[0] >= 0.6 for d in ctx.home.devices)

    def _mute(self, c: str, ctx: _Ctx):
        m = re.search(r"\b(unmute|mute|silence)\b", c)
        if not m:
            return None
        value = m[1] != "unmute"
        rest = re.sub(r"\b(unmute|mute|silence|the sound|sound|audio|volume|turn|on)\b", " ", c)
        t = self._targets(" ".join(rest.split()), ctx, need=Cap.MUTE, prefer_on=True, what="one")
        return [Step(device_id=d.id, action=Action.MUTE, value=value) for d in t.devices]

    def _volume(self, c: str, ctx: _Ctx):
        if not re.search(r"\b(volume|louder|quieter|softer)\b", c):
            return None
        up = bool(re.search(r"\b(up|louder|raise|increase|higher|more|turn up)\b", c))
        down = bool(re.search(r"\b(down|quieter|softer|lower|decrease|reduce|less)\b", c))
        by = re.search(r"\bby (\d+)\b", c)
        level = None if by else re.search(r"\b(?:to|at|volume) (\d+)\b", c)
        rest = re.sub(r"\b(volume|louder|quieter|softer|up|down|raise|increase|higher|more|lower|decrease|reduce|"
                      r"less|turn|set|make|put|change|by|to|at|on|a bit|a little|bit|little|lot|percent|\d+)\b", " ", c)
        rest = " ".join(rest.split())
        if level:
            t = self._targets(rest, ctx, need=Cap.VOLUME_LEVEL, prefer_on=True, what="one")
            return [Step(device_id=d.id, action=Action.VOLUME, value=int(level[1])) for d in t.devices]
        if not (up or down):
            raise Fail("Say volume up, volume down, or a level like “volume 20”.")
        n = int(by[1]) if by else 0
        t = self._targets(rest, ctx, need=Cap.VOLUME, prefer_on=True, what="one")
        return [self._volume_step(d, up, n) for d in t.devices]

    @staticmethod
    def _volume_step(d: Device, up: bool, n: int) -> Step:
        cur = d.state.get("volume")
        if Cap.VOLUME_LEVEL in d.caps and isinstance(cur, (int, float)):
            step = n or 5
            return Step(device_id=d.id, action=Action.VOLUME, value=max(0, min(100, int(cur) + (step if up else -step))))
        return Step(device_id=d.id, action=Action.VOLUME_UP if up else Action.VOLUME_DOWN, repeat=max(1, min(n or 3, 10)))

    def _channel(self, c: str, ctx: _Ctx):
        m = re.search(r"\b(?:(next|previous|prev|last) channel|channel (up|down))\b", c)
        if not m:
            return None
        up = (m[1] or m[2]) in ("next", "up")
        rest = re.sub(r"\b(next|previous|prev|last|channel|up|down|change|the|go|to|on|turn)\b", " ", c)
        t = self._targets(" ".join(rest.split()), ctx, need=Cap.CHANNEL, prefer_on=True, what="TV")
        return [Step(device_id=d.id, action=Action.CHANNEL_UP if up else Action.CHANNEL_DOWN) for d in t.devices]

    def _vacuums(self, ctx: _Ctx, need: str = Cap.CLEAN) -> list[Device]:
        return [d for d in ctx.home.devices if need in d.caps]

    def _vacuum_rooms(self, c: str, ctx: _Ctx):
        """'vacuum the kitchen and hall', 'mop the kitchen', 'clean the house', 'vacuum'."""
        m = re.match(r"^(?P<v>vacuum|clean|hoover|mop|sweep)(?: up)?(?: in)?(?: (?P<rest>.+))?$", c)
        if not m or not self._vacuums(ctx):
            return None
        rest = (m["rest"] or "").strip()
        rest = re.sub(r"^(?:the )?(?:whole )?", "", rest) if rest else rest
        vac_named = None
        mm = re.match(r"^(?P<r>.*?)\s*(?:with|using) (?P<t>.+)$", rest)
        if mm:
            rest, vac_named = mm["r"], mm["t"]
        pool = self._vacuums(ctx)
        if vac_named:
            pool = self._targets(vac_named, ctx, need=Cap.CLEAN, pool=pool, what="vacuum").devices
        steps: list[Step] = []
        if not rest or rest in HOUSE or self._only_vacuum_words(rest, pool):
            t = self._targets("" if not rest or rest in HOUSE else rest, ctx, need=Cap.CLEAN, pool=pool, what="vacuum")
            for d in t.devices:
                steps += self._mop_first(m["v"], d)
                steps.append(Step(device_id=d.id, action=Action.CLEAN, value=Clean.START))
            return steps
        if not any(Cap.ROOMS in d.caps for d in pool):
            raise Fail("The vacuum can't clean single rooms. Say “start the vacuum” to clean everywhere.")
        parts = [p.strip() for p in re.split(r"\band\b|\bplus\b", rest) if p.strip()]
        best = None
        for d in pool:
            if Cap.ROOMS not in d.caps:
                continue
            rooms = d.meta.get("rooms", [])
            got, missing = [], []
            for p in parts:
                p = re.sub(r"^(?:the|my)\s+", "", p)
                hit = self._options(p, rooms)
                (got.append(hit[0]) if hit else missing.append(p))
            if best is None or len(got) > len(best[1]):
                best = (d, got, missing)
        d, got, missing = best
        if not got:
            names = _join([str(r.get("name")) for r in d.meta.get("rooms", [])])
            raise Fail(f"{_The(d)} doesn't know a room called “{_join(missing)}”."
                       + (f" Its rooms are {names}." if names else " Its map has no rooms yet."))
        if missing:
            ctx.notes.append(f"It doesn't know “{_join(missing)}”, so I left that out.")
        ctx.last = [d]
        ids = []
        for r in got:
            if r["id"] not in ids:
                ids.append(r["id"])
        return self._mop_first(m["v"], d) + [Step(device_id=d.id, action=Action.CLEAN_ROOMS, value=ids)]

    @staticmethod
    def _only_vacuum_words(rest: str, pool: list[Device]) -> bool:
        words = [w for w in rest.split() if w not in FILLER]
        return bool(words) and all(stem(w) in KIND_WORDS[Kind.VACUUM] or any(
            tok_sim(w, n) >= 0.85 for d in pool for n in normalize(d.name).split()) for w in words)

    def _mop_first(self, verb: str, d: Device) -> list[Step]:
        if verb != "mop" or Cap.CLEAN_MODE not in d.caps:
            return []
        modes = d.meta.get("clean_modes", [])
        hit = [o for o in modes if normalize(str(o.get("name"))) == "mop"] or self._options("mop", modes)
        return [Step(device_id=d.id, action=Action.SET_CLEAN_MODE, value=hit[0]["id"])] if hit else []

    def _dock(self, c: str, ctx: _Ctx):
        if not self._vacuums(ctx, Cap.DOCK):
            return None
        if not (re.search(r"\b(send|take|bring|return|dock|go|head)\b", c)
                and re.search(r"\b(home|back|dock|base|charger|charge|charging|recharge)\b", c)) \
                and not re.match(r"^(?:dock|return)\b", c):
            return None
        rest = re.sub(r"\b(send|take|bring|return|dock|go|head|home|back|base|charger|charge|charging|recharge|to|"
                      r"its|it s|the dock|and)\b", " ", c)
        t = self._targets(" ".join(rest.split()), ctx, need=Cap.DOCK, pool=self._vacuums(ctx, Cap.DOCK), what="vacuum")
        return [Step(device_id=d.id, action=Action.DOCK) for d in t.devices]

    def _locate(self, c: str, ctx: _Ctx):
        m = re.match(r"^(?:find|locate|where is|wheres|where s|where are)(?: is)? (?P<t>.+)$", c)
        if not m or not self._vacuums(ctx, Cap.LOCATE):
            return None
        t = self._targets(m["t"], ctx, need=Cap.LOCATE, what="one")
        return [Step(device_id=d.id, action=Action.LOCATE) for d in t.devices]

    def _station(self, c: str, ctx: _Ctx):
        m = re.match(r"^(?:empty|wash|dry|clean|rinse|start|run)\b", c)
        if not m:
            return None
        phrase = " ".join(w for w in c.split() if w not in FILLER and stem(w) not in KIND_WORDS[Kind.VACUUM])
        for d in self._vacuums(ctx, Cap.STATION):
            hits = self._options(phrase, d.meta.get("station_actions", []), strict=True)
            if hits:
                ctx.last = [d]
                return [Step(device_id=d.id, action=Action.STATION, value=hits[0]["id"])]
        return None

    def _app(self, c: str, ctx: _Ctx):
        m = re.match(r"^(?:open|launch|start|play|put on|go to|switch to|change to|turn on|watch|show|load|run|"
                     r"put)\s+(?P<rest>.+)$", c)
        if not m:
            return None
        rest = m["rest"]
        tries = [(rest, "")]
        for sep in (" on ", " in "):
            idx = rest.rfind(sep)
            if idx > 0:
                tries.append((rest[:idx], rest[idx + len(sep):]))
        for app, target in tries:
            pairs = self._option_devices(app, "apps", Cap.APPS, ctx)
            if not pairs:
                continue
            devices = [d for d, _o in pairs]
            if target:
                devices = self._targets(target, ctx, need=Cap.APPS, pool=devices, what="TV").devices
            elif len(devices) > 1:
                devices = self._targets("", ctx, need=Cap.APPS, prefer_on=True, pool=devices, what="TV").devices
            ctx.last = devices
            by_dev = {d.id: o for d, o in pairs}
            return [Step(device_id=d.id, action=Action.LAUNCH_APP, value=by_dev[d.id]["id"]) for d in devices]
        return None

    def _media_key(self, c: str, ctx: _Ctx):
        m = re.match(r"^(?P<v>pause|play|resume|unpause|continue|stop|fast forward|rewind|skip ahead|skip back)"
                     r"(?: (?P<t>.+))?$", c)
        if not m:
            return None
        verb, phrase = m["v"], (m["t"] or "")
        phrase = re.sub(r"^(?:playing|cleaning|the show|the movie|the music)\b", "", phrase).strip()
        if verb == "play" and phrase and not self._looks_like_device(phrase, ctx):
            return None                            # "play something": not a device, not an app we know
        busy_vacuums = [d for d in self._vacuums(ctx) if d.state.get("activity") in ("cleaning", "paused", "returning")]
        media = [d for d in ctx.home.devices if (Cap.REMOTE in d.caps or Cap.MEDIA in d.caps)]
        pool = media + busy_vacuums if not phrase else media + self._vacuums(ctx)
        t = self._targets(phrase, ctx, prefer_on=True, pool=pool, what="one")
        key = {"pause": Key.PAUSE, "play": Key.PLAY, "resume": Key.PLAY, "unpause": Key.PLAY, "continue": Key.PLAY,
               "stop": Key.STOP, "fast forward": Key.FORWARD, "skip ahead": Key.FORWARD, "rewind": Key.REWIND,
               "skip back": Key.REWIND}[verb]
        clean = {Key.PAUSE: Clean.PAUSE, Key.PLAY: Clean.RESUME, Key.STOP: Clean.STOP}
        steps = []
        for d in t.devices:
            if Cap.CLEAN in d.caps:
                if key not in clean:
                    raise Fail(f"{_The(d)} can't do that.")
                steps.append(Step(device_id=d.id, action=Action.CLEAN, value=clean[key]))
            else:
                steps.append(Step(device_id=d.id, action=Action.KEY, value=key))
        return steps

    def _start(self, c: str, ctx: _Ctx):
        m = re.match(r"^(?:start|begin|run|resume|continue|kick off)(?: up)?(?: (?P<t>.+))?$", c)
        if not m:
            return None
        phrase = re.sub(r"\b(cleaning|clean|a clean|the clean)\b", " ", m["t"] or "").strip()
        resume = c.startswith(("resume", "continue"))
        if not phrase and "clean" in c:
            pool = self._vacuums(ctx)
        else:
            pool = None
        t = self._targets(phrase, ctx, pool=pool, what="one")
        steps = []
        for d in t.devices:
            if Cap.CLEAN in d.caps:
                steps.append(Step(device_id=d.id, action=Action.CLEAN, value=Clean.RESUME if resume else Clean.START))
            elif Cap.POWER in d.caps:
                steps.append(Step(device_id=d.id, action=Action.POWER, value=True))
            else:
                raise Fail(f"{_The(d)} can't be started.")
        return steps

    def _set(self, c: str, ctx: _Ctx):
        """'set the lamp to 30%', 'make the backlight blue', 'switch to HDMI 2', 'set the vacuum to max'."""
        colors = "|".join(re.escape(w) for w in COLOR_WORDS)
        m = (re.match(r"^(?:set|switch|change|put|turn|make|go|bring|dim|brighten|adjust)(?: (?P<t>.+?))?"
                      r" (?:to|at) (?P<v>.+)$", c)
             or re.match(rf"^(?:make|turn|set|change|colou?r|paint)(?: (?P<t>.+?))? (?P<v>(?:{colors}))(?: colou?r)?$", c)
             or re.match(r"^(?:input|source) (?:to )?(?P<v>.+)$()", c)
             or re.match(r"^(?P<t>.+?) (?:to|at) (?P<v>\d+(?: percent)?)$", c))
        if not m:
            return None
        target = (m.groupdict().get("t") or "").strip()
        value = m["v"].strip()
        if re.fullmatch(r"(?:on|off)", value):
            return None                                     # "set the lamp to off": the power rule
        volume = bool(re.search(r"\bvolume\b", target))
        bright = bool(re.search(r"\bbrightness\b", target)) or value.endswith("percent") and not volume
        target = re.sub(r"\b(?:the )?(brightness|color|colour|level)( of)?\b", " ", target)
        target = " ".join(re.sub(r"\b(?:input|source|suction|suction power|cleaning mode|clean mode|mode)\b", " ",
                                 target).split())
        target = " ".join(re.sub(r"\bvolume\b", " ", target).split())

        def ask_target(need, what="one"):
            try:   # a TV that's on is the one meant; for lights, ask
                return self._targets(target, ctx, need=need, prefer_on=need == Cap.VOLUME_LEVEL,
                                     what=what)
            except Ask as a:
                if target:
                    raise
                raise Ask(a.question, [(lbl, f"set the {normalize(lbl)} to {value}", det)
                                       for lbl, _r, det in a.choices]) from None

        num = re.fullmatch(r"(\d+)(?: percent)?", value)
        word_num = {"max": 100, "maximum": 100, "full": 100, "full brightness": 100, "half": 50,
                    "minimum": 1, "min": 1, "low": 20, "dim": 20, "bright": 100}.get(value)
        color = self._color(value)

        named = self._targets(target, ctx, prefer_on=True).devices if target and word_num is not None else None
        if num or (word_num is not None and not self._any_option(value, ctx, named)):
            n = int(num[1]) if num else word_num
            if volume:
                t = ask_target(Cap.VOLUME_LEVEL)
                return [Step(device_id=d.id, action=Action.VOLUME, value=n) for d in t.devices]
            t = ask_target(Cap.BRIGHTNESS if bright else None, "light" if bright else "one")
            steps = []
            for d in t.devices:
                if Cap.BRIGHTNESS in d.caps:
                    steps.append(Step(device_id=d.id, action=Action.BRIGHTNESS, value=max(1, min(100, n))))
                elif Cap.VOLUME_LEVEL in d.caps:
                    steps.append(Step(device_id=d.id, action=Action.VOLUME, value=max(0, min(100, n))))
                elif not t.plural:
                    raise Fail(f"{_The(d)} can't be set to a number.")
            if not steps:
                raise Fail("None of those can be dimmed.")
            return steps

        if color:
            t = ask_target(None, "light")
            steps = []
            for d in t.devices:
                if color[0] == "temp" and Cap.COLOR_TEMP in d.caps:
                    steps.append(Step(device_id=d.id, action=Action.COLOR_TEMP, value=color[1]))
                elif Cap.COLOR in d.caps:
                    rgb = color[1] if color[0] == "rgb" else (255, 255, 255)
                    steps.append(Step(device_id=d.id, action=Action.COLOR, value=dict(zip("rgb", rgb, strict=True))))
                elif Cap.COLOR_TEMP in d.caps and not t.plural:
                    raise Fail(f"{_The(d)} can only change its shade of white.")
                elif not t.plural:
                    raise Fail(f"{_The(d)} can't change color.")
            if not steps:
                raise Fail("None of those can change color.")
            return steps

        phrase = " ".join(w for w in value.split() if w not in OPTION_NOISE) or value
        pool = self._targets(target, ctx, prefer_on=True).devices if target else None
        for key, action, cap in OPTION_ACTIONS:
            pairs = self._option_devices(phrase, key, cap, ctx, pool=pool)
            if not pairs:
                continue
            devices = [d for d, _o in pairs]
            if len(devices) > 1:
                devices = self._targets("", ctx, need=cap, prefer_on=True, pool=devices, what="one").devices
            ctx.last = devices
            opt = {d.id: o for d, o in pairs}
            return [Step(device_id=d.id, action=action, value=opt[d.id]["id"]) for d in devices]
        if target:
            raise Fail(f"{_The(pool[0]) if pool and len(pool) == 1 else 'That'} "
                       f"doesn't have “{value}”.")
        return None

    def _any_option(self, value: str, ctx: _Ctx, devices: list[Device] | None = None) -> bool:
        return any(self._options(value, d.meta.get(k, [])) for d in (ctx.home.devices if devices is None else devices)
                   for k, _a, _c in OPTION_ACTIONS)

    @staticmethod
    def _color(value: str):
        v = re.sub(r"\s*colou?r$", "", value.strip())
        if v in WHITES:
            return ("temp", WHITES[v])
        if v in COLORS:
            return ("rgb", COLORS[v])
        return None

    def _dim(self, c: str, ctx: _Ctx):
        m = (re.match(r"^(?P<v>dim|brighten|lighten|darken)(?: (?P<t>.+?))?(?: (?:a bit|a little|a lot|down|up))?$", c)
             or re.match(r"^(?:make|turn) (?P<t>.+?) (?P<v>brighter|dimmer|darker|lighter)$", c))
        if not m:
            return None
        up = m["v"] in ("brighten", "lighten", "brighter", "lighter")
        t = self._targets(m["t"] or "", ctx, need=Cap.BRIGHTNESS, prefer_on=True, what="light")
        return [self._bright_step(d, up) for d in t.devices]

    @staticmethod
    def _bright_step(d: Device, up: bool) -> Step:
        cur = d.state.get("brightness") if d.state.get("on") else None
        cur = cur if isinstance(cur, (int, float)) else (30 if up else 60)
        return Step(device_id=d.id, action=Action.BRIGHTNESS, value=max(1, min(100, int(cur) + (25 if up else -25))))

    def _up_down(self, c: str, ctx: _Ctx):
        m = (re.match(r"^(?:turn|bring|put) (?P<t>.+?) (?P<v>up|down)$", c)
             or re.match(r"^(?:turn|bring) (?P<v>up|down) (?P<t>.+)$", c))
        if not m:
            return None
        up = m["v"] == "up"
        t = self._targets(m["t"], ctx, prefer_on=True)
        steps = []
        for d in t.devices:
            if Cap.VOLUME in d.caps:
                steps.append(self._volume_step(d, up, 0))
            elif Cap.BRIGHTNESS in d.caps:
                steps.append(self._bright_step(d, up))
            else:
                raise Fail(f"{_The(d)} can't be turned {m['v']}.")
        return steps

    def _power(self, c: str, ctx: _Ctx):
        verb = r"(?:turn|switch|power|shut|put|flip|set|light|lights)"
        m = (re.match(rf"^{verb} (?P<v>on|off) (?P<t>.+)$", c)
             or re.match(rf"^{verb} (?P<t>.+?) (?P<v>on|off)$", c)
             or re.match(r"^(?:kill|cut|shut down|power down)(?P<v>) (?P<t>.+)$", c)
             or re.match(r"^(?P<t>.+?) (?P<v>on|off)$", c)
             or re.match(r"^(?P<v>on|off) (?P<t>.+)$", c))
        if not m:
            if re.match(rf"^{verb} (?:on|off)$", c):
                raise Fail(f"What should I turn {c.split()[-1]}? Say its name, like “turn {c.split()[-1]} the kitchen”.")
            return None
        on = m["v"] == "on"
        t = self._targets(m["t"], ctx, prefer_on="off" if on else True)
        steps, kept = [], []
        for room in t.rooms:              # "turn off the kitchen": like the room's Turn off button
            if not on:
                steps.append(Step("room_off", target=room))
                continue
            inside = [d for d in t.devices if ctx.room_of(d) == room and d not in t.named]
            lights = [d for d in inside if d.kind == Kind.LIGHT and Cap.POWER in d.caps]
            targets = lights or [d for d in inside if Cap.POWER in d.caps]
            if not targets:
                raise Fail(f"Nothing in the {room} can be turned on.")
            steps += [Step(device_id=d.id, action=Action.POWER, value=True) for d in targets]
        for d in (t.named if t.rooms else t.devices):
            if Cap.POWER in d.caps:
                if not on and d.keep_on:
                    if t.plural and len(t.devices) > 1:
                        kept.append(d.name)
                        continue
                    ctx.confirm.append(f"{_The(d)} is set to stay on. Turn it off anyway?")
                steps.append(Step(device_id=d.id, action=Action.POWER, value=on))
            elif Cap.CLEAN in d.caps:
                steps.append(Step(device_id=d.id, action=Action.CLEAN, value=Clean.START) if on
                             else Step(device_id=d.id, action=Action.DOCK))
            elif not t.plural:
                raise Fail(f"{_The(d)} can't be turned {m['v']}.")
        if kept:
            ctx.notes.append(f"Left {_join([_the(n) for n in kept])} on, because "
                             f"{'it is' if len(kept) == 1 else 'they are'} set to stay on.")
        if not steps:
            raise Fail("None of those can be turned on or off.")
        return steps

    def _bare(self, c: str, ctx: _Ctx):
        """A name on its own: an app ("YouTube") or an input ("HDMI 2")."""
        for key, action, cap in (("apps", Action.LAUNCH_APP, Cap.APPS), ("inputs", Action.SET_INPUT, Cap.INPUTS),
                                 ("sound_modes", Action.SET_SOUND_MODE, Cap.SOUND_MODE)):
            phrase = " ".join(w for w in c.split() if w not in OPTION_NOISE) or c
            pairs = []
            for d in ctx.home.devices:
                if cap in d.caps:
                    hits = self._options(phrase, d.meta.get(key, []), strict=True)
                    if len(hits) == 1:
                        pairs.append((d, hits[0]))
            if pairs:
                devices = [d for d, _o in pairs]
                if len(devices) > 1:
                    devices = self._targets("", ctx, need=cap, prefer_on=True, pool=devices, what="one").devices
                opt = {d.id: o for d, o in pairs}
                return [Step(device_id=d.id, action=action, value=opt[d.id]["id"]) for d in devices]
        return None


# ---------------------------------------------------------------------------
# Running a plan and saying what happened
# ---------------------------------------------------------------------------

def _opt_name(d: Device, key: str, value) -> str:
    for o in d.meta.get(key, []):
        if isinstance(o, dict) and str(o.get("id")) == str(value):
            return str(o.get("name", value))
    return str(value)


def describe(step: Step, d: Device | None) -> tuple[str, str, str]:
    """(verb, object, rest) in the past tense, e.g. ("Turned off", "the Floor lamp", "")."""
    a, v = step.action, step.value
    name = _the(d) if d else "it"
    if a == Action.POWER:
        return ("Turned on" if v else "Turned off", name, "")
    if a == Action.BRIGHTNESS:
        return ("Set", name, f"to {v}%")
    if a == Action.COLOR_TEMP:
        word = next((w for w, k in WHITES.items() if k == v and " " in w), None) or f"{v} K white"
        return ("Made", name, word)
    if a == Action.COLOR:
        rgb = (v.get("r"), v.get("g"), v.get("b")) if isinstance(v, dict) else None
        word = next((w for w, c in COLORS.items() if c == rgb), None) or ("white" if rgb == (255, 255, 255) else "that color")
        return ("Made", name, word)
    if a == Action.VOLUME:
        return ("Set", name, f"volume to {v}")
    if a in (Action.VOLUME_UP, Action.VOLUME_DOWN):
        return ("Turned", name, "up" if a == Action.VOLUME_UP else "down")
    if a == Action.MUTE:
        return ("Muted" if v else "Unmuted", name, "")
    if a in (Action.CHANNEL_UP, Action.CHANNEL_DOWN):
        return ("Changed the channel on", name, "")
    if a == Action.LAUNCH_APP:
        return ("Opened", _opt_name(d, "apps", v) if d else str(v), f"on {name}")
    if a == Action.SET_INPUT:
        return ("Switched", name, f"to {_opt_name(d, 'inputs', v) if d else v}")
    if a == Action.SET_SOUND_MODE:
        return ("Set", name, f"to {_opt_name(d, 'sound_modes', v) if d else v}")
    if a == Action.SET_SUCTION:
        return ("Set", name, f"to {_opt_name(d, 'suction_levels', v) if d else v} suction")
    if a == Action.SET_CLEAN_MODE:
        return ("Set", name, f"to {_opt_name(d, 'clean_modes', v) if d else v}")
    if a == Action.CLEAN:
        return ({Clean.START: "Started", Clean.PAUSE: "Paused", Clean.RESUME: "Resumed",
                 Clean.STOP: "Stopped"}.get(v, "Told"), name, "")
    if a == Action.CLEAN_ROOMS:
        rooms = _join([f"the {_opt_name(d, 'rooms', r)}" if d else str(r) for r in (v or [])])
        return ("Sent", name, f"to clean {rooms}")
    if a == Action.DOCK:
        return ("Sent", name, "home")
    if a == Action.LOCATE:
        return ("Asked", name, "to play a sound")
    if a == Action.STATION:
        return ("Told", name, f"to {(_opt_name(d, 'station_actions', v) if d else str(v)).lower()}")
    if a == Action.KEY:
        verb = {Key.PAUSE: "Paused", Key.PLAY: "Pressed play on", Key.STOP: "Stopped",
                Key.FORWARD: "Skipped ahead on", Key.REWIND: "Rewound"}.get(v, f"Pressed {v} on")
        return (verb, name, "")
    return ("Sent", f"{a} to {name}", "")


def sentence(parts: list[tuple[str, str, str]]) -> str:
    """Merge "Turned off the lamp" + "Turned off the TV" into "Turned off the lamp and the TV"."""
    groups: list[tuple[str, list[str], str]] = []
    for verb, obj, rest in parts:
        if groups and groups[-1][0] == verb and groups[-1][2] == rest:
            groups[-1][1].append(obj)
        else:
            groups.append((verb, [obj], rest))
    out = []
    for i, (verb, objs, rest) in enumerate(groups):
        s = " ".join(x for x in (verb if i == 0 else verb[0].lower() + verb[1:], _join(objs), rest) if x)
        out.append(s)
    text = _join(out)
    return text + "." if text else ""


class Voice:
    """Runs voice commands through the HomeService, so they go through the same pipeline as a tap."""

    def __init__(self, service):
        self.service = service
        self.parser: Parser = RulesParser()

    def home(self) -> Home:
        st = self.service.store
        return Home(devices=list(st.devices.values()), rooms=list(st.rooms), scenes=list(st.scenes))

    async def handle(self, text: str, confirm: bool = False) -> dict:
        text = " ".join(str(text or "").split())[:MAX_TEXT]
        if not text:
            raise AdapterError("Say or type a command, like “turn off the kitchen”.")
        plan = await self.parser.parse(text, self.home())
        out: dict = {"heard": text, "understood": not plan.error, "say": "", "done": [], "failed": [],
                     "question": "", "choices": [], "confirm": ""}
        if plan.error:
            out["say"] = plan.error
            log.info("Voice: %r not understood (%s)", text, plan.error)
            return out
        if plan.question:
            out.update(question=plan.question, say=plan.question, choices=[asdict(c) for c in plan.choices])
            return out
        if plan.confirm and not confirm:
            out.update(confirm=plan.confirm, say=plan.confirm)
            return out
        log.info("Voice: %r → %d step(s)", text, len(plan.steps))
        said: list[tuple[str, str, str]] = []
        extra: list[str] = []
        for clause in sorted({s.clause for s in plan.steps}):
            steps = [s for s in plan.steps if s.clause == clause]
            groups = self._by_device(steps)
            results = await asyncio.gather(*(self._run(g) for g in groups), return_exceptions=True)
            for group, res in zip(groups, results, strict=True):
                if isinstance(res, Exception):
                    msg = str(res) if isinstance(res, (AdapterError, KeyError)) else f"Something went wrong: {res}"
                    if isinstance(res, KeyError):
                        msg = "That device or scene is gone."
                    out["failed"].append({"device_id": group[0].device_id, "action": group[0].action, "error": msg})
                    extra.append(msg if msg.endswith(".") else msg + ".")
                    continue
                for s, (part, info) in zip(group, res, strict=True):
                    if part:
                        said.append(part)
                    if info:
                        extra.append(info)
                    out["done"].append({"kind": s.kind, "device_id": s.device_id, "action": s.action,
                                        "value": s.value, "target": s.target})
        text_done = sentence(said)
        out["say"] = " ".join(x for x in [text_done, *extra, *plan.notes] if x) or "Done."
        return out

    @staticmethod
    def _by_device(steps: list[Step]) -> list[list[Step]]:
        """Steps for one device run in order; different devices run at the same time."""
        groups: dict[str, list[Step]] = {}
        order: list[list[Step]] = []
        for s in steps:
            key = s.device_id or f"_{id(s)}"
            if key not in groups:
                groups[key] = []
                order.append(groups[key])
            groups[key].append(s)
        return order

    async def _run(self, group: list[Step]) -> list[tuple[tuple[str, str, str] | None, str]]:
        out = []
        for s in group:
            out.append(await self._run_one(s))
        return out

    async def _run_one(self, s: Step) -> tuple[tuple[str, str, str] | None, str]:
        svc = self.service
        if s.kind == "scene":
            scene = next((x for x in svc.store.scenes if x["id"] == s.target), None)
            res = await svc.run_scene(s.target)
            name = scene.get("name", "the scene") if scene else "the scene"
            if res.get("failed"):
                return ("Ran", name, ""), f"Some of it didn't work: {_join(res['failed'])}."
            return ("Ran", name, ""), ""
        if s.kind in ("all_off", "room_off"):
            n = await svc.all_off(None if s.kind == "all_off" else s.target)
            where = f" in the {s.target}" if s.kind == "room_off" and s.target else ""
            if s.kind == "room_off" and s.target == "":
                where = " that aren't in a room"
            if not n:
                return None, f"Everything{where} was already off."
            return ("Turned off", f"{n} {'device' if n == 1 else 'devices'}{where}", ""), ""
        if s.kind == "query":
            return None, self._status(s)
        d = svc.get(s.device_id)
        for _ in range(max(1, s.repeat)):
            await svc.command(s.device_id, s.action, s.value)
        return describe(s, d), ""

    def _status(self, s: Step) -> str:
        svc = self.service
        if s.device_id:
            d = svc.get(s.device_id)
            return f"{_The(d)} is {self._state_words(d)}."
        rooms = svc.store.rooms
        devices = [d for d in svc.store.devices.values()
                   if s.target is None or (d.room if d.room in rooms else "") == s.target]
        busy = [d for d in devices if self._is_busy(d)]
        where = f"in the {s.target}" if s.target else "at home" if s.target is None else "outside any room"
        if not busy:
            return f"Nothing is on {where}."
        on = [d for d in busy if Cap.CLEAN not in d.caps]
        out = []
        if on:
            items = []
            for d in on:
                detail = re.sub(r"^on (at )?", "", self._state_words(d)).replace(" (", ", ").replace(")", "")
                items.append(f"{_the(d)} ({detail})" if detail != "on" else _the(d))
            out.append(f"On {where}: {_join(items)}.")
        for d in busy:
            if Cap.CLEAN in d.caps:
                out.append(f"{_The(d)} is {self._state_words(d)}.")
        return " ".join(out)

    @staticmethod
    def _is_busy(d: Device) -> bool:
        s = d.state
        if s.get("online") is False:
            return False
        return bool(s.get("on")) or s.get("activity") in ("cleaning", "paused", "returning")

    @staticmethod
    def _state_words(d: Device) -> str:
        s = d.state
        if s.get("online") is False:
            return "offline"
        if d.kind == Kind.VACUUM or Cap.CLEAN in d.caps:
            return {"cleaning": "cleaning", "paused": "paused", "returning": "going back to its dock",
                    "docked": "docked", "idle": "ready", "error": "stuck and needs help"}.get(s.get("activity"), "ready")
        if not s.get("on"):
            return "off"
        if Cap.BRIGHTNESS in d.caps and s.get("brightness") is not None and d.kind == Kind.LIGHT:
            return f"on at {s['brightness']}%"
        if s.get("app"):
            return f"on {_opt_name(d, 'apps', s['app'])}"
        if s.get("input"):
            return f"on {_opt_name(d, 'inputs', s['input'])}"
        return "on"
