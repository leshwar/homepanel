// Sign-in: the profile picker, PIN pad, email + password form and the first-run
// "protect your panel" screen; the profile button (top right) with switch / sign out;
// and the wall panel's idle lock.
//
// The server decides everything (app/api/auth.py): this file only shows the right
// screen. Signed out, the app's data is wiped and hidden, so the last person's
// devices never show through the glass.

import { api } from "./api.js";
import { $, esc, icon, toast } from "./util.js";
import { store, onChange } from "./store.js";
import { applyTransparency } from "./glass.js";
import { openSettings } from "./settings.js";

let session = null;          // the last answer from /auth/session
let hooks = {};
let view = { name: "picker" };   // picker | pin | password | email | setup
let pin = "";
let switching = false;       // picking another profile while signed in: Cancel goes back
let busy = false;
let lastActivity = Date.now();

const root = () => $("#signin");
const MAX_PIN = 6;
const isLocalScreen = () => ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);

export const currentSession = () => session;

export function avatar(p, size = "") {
  return `<span class="avatar ${size}" style="--av:${esc(p?.color || "#f2b35b")}" aria-hidden="true">${esc(p?.initial || "?")}</span>`;
}

// hooks.signedIn(): load this profile's panel. hooks.signedOut(display): wipe it.
export async function startAuth(h) {
  hooks = h;
  window.addEventListener("hp:signin", () => { if (session?.signed_in) refresh(); });
  setupProfileButton();
  setupIdleLock();
  bind();
  await refresh(true);
}

async function refresh(first = false) {
  try {
    session = await api.session();
  } catch (e) {
    toast(e.message, true);
    setTimeout(() => refresh(first), 3000);
    return;
  }
  applyDisplay(session.display);
  if (session.signed_in) return enter(first);
  if (!first) hooks.signedOut?.(session.display);
  switching = false;
  show(session.setup ? { name: "setup" } : { name: "picker" });
}

// The look of the panel before anyone signs in (background, glass).
function applyDisplay(d = {}) {
  const r = document.documentElement;
  r.classList.toggle("glass", d.glass_effect !== false);
  if (d.background) r.dataset.bg = d.background;
  applyTransparency(d.glass_transparency ?? 45);
}

function enter(first = false) {
  switching = false;
  hide();
  renderProfileButton();
  if (!first) hooks.signedOut?.(session.display);   // the last profile's data goes first
  hooks.signedIn?.();
}

// ---------- the overlay ----------
function show(v) {
  view = v;
  pin = "";
  document.documentElement.dataset.auth = switching ? "switch" : "out";
  root().hidden = false;
  render();
  closeMenu();
}

function hide() {
  root().hidden = true;
  root().innerHTML = "";
  document.documentElement.dataset.auth = "in";
}

const homeName = () => esc(session?.display?.home_name || "Home");
const profile = (id) => session?.profiles.find((p) => p.id === id);
const errorLine = `<p class="signin-error" role="alert" id="signin-error"></p>`;
const back = `<button class="icon-btn signin-back" data-view="picker" aria-label="Back">${icon("left")}</button>`;

const VIEWS = {
  picker() {
    const list = session.profiles;
    return `<div class="signin-card">
      <div class="signin-head"><h1>${homeName()}</h1><p>${switching ? "Switch to another profile" : "Who's using the panel?"}</p></div>
      ${session.locked ? `<p class="signin-note">${icon("clock")}The panel locked itself after being idle.</p>` : ""}
      <div class="avatars" role="list">${list.map((p) => `
        <button class="avatar-choice" role="listitem" data-pick="${esc(p.id)}" aria-label="${esc(p.name)}">
          ${avatar(p, "xl")}<span class="avatar-name">${esc(p.name)}</span></button>`).join("")}</div>
      <div class="signin-foot">
        <button class="btn" data-view="email">Sign in with email</button>
        ${switching ? `<button class="btn" data-cancel>Cancel</button>` : ""}
      </div>
      ${session.demo ? `<p class="signin-hint">Demo: Owner's PIN is 1234, Sam's is 2468.</p>` : ""}
    </div>`;
  },

  pin({ id }) {
    const p = profile(id);
    const slots = Math.max(4, Math.min(MAX_PIN, pin.length));
    return `<div class="signin-card pin-card">
      ${back}
      ${avatar(p, "lg")}
      <h2>${esc(p.name)}</h2>
      <p class="signin-sub">Enter your PIN</p>
      <div class="pin-dots" aria-label="${pin.length} of ${slots} digits entered">${
        Array.from({ length: slots }, (_, i) => `<span class="${i < pin.length ? "on" : ""}"></span>`).join("")}</div>
      ${errorLine}
      <div class="pinpad">
        ${[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => `<button data-digit="${n}">${n}</button>`).join("")}
        <button data-digit="del" aria-label="Delete">${icon("back")}</button>
        <button data-digit="0">0</button>
        <button data-digit="ok" class="ok" aria-label="Sign in" ${pin.length < 4 ? "disabled" : ""}>${icon("check")}</button>
      </div>
      ${p.has_password ? `<button class="link-btn" data-view="password" data-id="${esc(p.id)}">Use password instead</button>` : ""}
    </div>`;
  },

  password({ id }) {
    const p = profile(id);
    return `<form class="signin-card" data-signin-password>
      ${back}
      ${avatar(p, "lg")}
      <h2>${esc(p.name)}</h2>
      <label class="field"><span>Password</span>
        <input name="password" type="password" autocomplete="current-password" required autofocus></label>
      ${errorLine}
      <button class="btn primary wide" type="submit">Sign in</button>
      ${p.has_pin ? `<button class="link-btn" type="button" data-pick="${esc(p.id)}">Use PIN instead</button>` : ""}
    </form>`;
  },

  email() {
    return `<form class="signin-card" data-signin-email>
      ${back}
      <h2>Sign in with email</h2>
      <label class="field"><span>Email</span>
        <input name="email" type="email" autocomplete="username" required autofocus spellcheck="false"></label>
      <label class="field"><span>Password</span>
        <input name="password" type="password" autocomplete="current-password" required></label>
      ${errorLine}
      <button class="btn primary wide" type="submit">Sign in</button>
    </form>`;
  },

  setup() {
    const usePw = view.method === "password";
    return `<form class="signin-card setup-card" data-setup>
      <div class="signin-head"><h1>Protect your panel</h1>
        <p>Anyone who can open this page can control your home. Choose a PIN or a password for the owner profile.
           You can add everyone else afterwards in Settings → Profiles.</p></div>
      <label class="field"><span>Your name</span><input name="name" value="${esc(profile(session.profiles[0]?.id)?.name || "Owner")}" maxlength="24" required></label>
      <div class="segmented" role="radiogroup" aria-label="Sign in with">
        <label><input type="radio" name="method" value="pin" ${usePw ? "" : "checked"}><span>PIN</span></label>
        <label><input type="radio" name="method" value="password" ${usePw ? "checked" : ""}><span>Email and password</span></label>
      </div>
      ${usePw ? `
        <label class="field"><span>Email</span><input name="email" type="email" autocomplete="username" required spellcheck="false"></label>
        <label class="field"><span>Password (at least 8 characters)</span>
          <input name="password" type="password" autocomplete="new-password" minlength="8" required></label>` : `
        <label class="field"><span>PIN (4 to 6 digits)</span>
          <input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,6}" maxlength="6" autocomplete="off" required></label>
        <label class="field"><span>PIN again</span>
          <input name="pin2" type="password" inputmode="numeric" pattern="[0-9]{4,6}" maxlength="6" autocomplete="off" required></label>`}
      <label class="check"><input type="checkbox" name="panel" ${isLocalScreen() ? "checked" : ""}>
        <span>This screen is the wall panel: it stays signed in and goes back to the profile picker when nobody is using it</span></label>
      ${errorLine}
      <button class="btn primary wide" type="submit">Protect the panel</button>
    </form>`;
  },
};

function render() {
  root().innerHTML = `<div class="signin-wrap">${VIEWS[view.name](view)}</div>`;
  root().querySelector("[autofocus]")?.focus();
}

function showError(msg) {
  const e = $("#signin-error");
  if (e) e.textContent = msg;
  const card = root().querySelector(".signin-card");
  if (card && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    card.animate([{ transform: "translateX(0)" }, { transform: "translateX(-10px)" }, { transform: "translateX(10px)" },
                  { transform: "translateX(0)" }], { duration: 260 });
  }
}

async function signIn(body) {
  if (busy) return;
  busy = true;
  try {
    session = await api.signIn(body);
    enter();
  } catch (e) {
    pin = "";
    if (view.name === "pin") render();
    showError(e.message);
  } finally {
    busy = false;
  }
}

function pick(id) {
  const p = profile(id);
  if (!p) return;
  show(p.has_pin ? { name: "pin", id } : { name: "password", id });
}

function typeDigit(d) {
  if (busy) return;
  if (d === "del") pin = pin.slice(0, -1);
  else if (d === "ok") { if (pin.length >= 4) signIn({ profile_id: view.id, pin }); return; }
  else if (pin.length < MAX_PIN) pin += d;
  const err = $("#signin-error")?.textContent;
  render();
  if (err && d === "del") showError("");
}

function bind() {
  const el = root();
  el.addEventListener("click", (e) => {
    const t = (sel) => e.target.closest(sel);
    if (t("[data-pick]")) return pick(t("[data-pick]").dataset.pick);
    if (t("[data-digit]")) return typeDigit(t("[data-digit]").dataset.digit);
    if (t("[data-cancel]")) { switching = false; hide(); return; }
    if (t("[data-view]")) {
      const v = t("[data-view]");
      return show({ name: v.dataset.view, id: v.dataset.id || view.id });
    }
  });
  el.addEventListener("change", (e) => {
    if (e.target.name === "method") { view = { ...view, method: e.target.value }; render(); }
  });
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const v = Object.fromEntries(new FormData(f).entries());
    if (f.matches("[data-signin-password]")) return signIn({ profile_id: view.id, password: v.password });
    if (f.matches("[data-signin-email]")) return signIn({ email: v.email, password: v.password });
    if (f.matches("[data-setup]")) {
      if (v.method !== "password" && v.pin !== v.pin2) return showError("The two PINs don't match.");
      const body = { name: v.name, panel: !!v.panel };
      if (v.method === "password") Object.assign(body, { email: v.email, password: v.password });
      else body.pin = v.pin;
      try {
        session = await api.setup(body);
        toast("Your panel is protected");
        enter();
      } catch (err) { showError(err.message); }
    }
  });
  document.addEventListener("keydown", (e) => {
    if (root().hidden || view.name !== "pin") return;
    if (/^[0-9]$/.test(e.key)) typeDigit(e.key);
    else if (e.key === "Backspace") typeDigit("del");
    else if (e.key === "Enter") typeDigit("ok");
    else if (e.key === "Escape") show({ name: "picker" });
  });
}

// ---------- the profile button and its menu ----------
function renderProfileButton() {
  const b = $("#profile-btn");
  const p = store.me || session?.me;
  document.documentElement.dataset.role = p?.role || "";
  if (!b) return;
  b.hidden = !p;
  if (!p) return;
  b.innerHTML = avatar(p);
  b.setAttribute("aria-label", `${p.name}: switch profile or sign out`);
}

function menuHtml() {
  const p = store.me || session.me;
  const admin = p.role === "admin";
  const item = (act, ic, label) => `<button role="menuitem" data-pm="${act}">${icon(ic)}<span>${label}</span></button>`;
  return `<div class="pm-head">${avatar(p, "lg")}<div><b>${esc(p.name)}</b><span>${admin ? "Admin" : "Member"}${
      session.panel ? " · wall panel" : ""}</span></div></div>
    ${item("switch", "users", "Switch profile")}
    ${item("me", "gear", "Your profile")}
    ${admin ? item("profiles", "users", "Profiles and sign-in") : ""}
    ${session.auto ? "" : session.panel ? item("lock", "door", "Lock the panel") : item("signout", "door", "Sign out")}`;
}

function closeMenu() {
  const m = $("#profile-menu");
  if (m) m.hidden = true;
  $("#profile-btn")?.setAttribute("aria-expanded", "false");
}

async function signOut() {
  try {
    session = await api.signOut();
  } catch (e) { toast(e.message, true); }
  hooks.signedOut?.(session?.display || {});
  refresh();
}

export async function lockNow() {
  try { await api.lock(); } catch { /* already locked */ }
  await refresh();
}

export function switchProfile() {
  switching = true;
  hooks.closeAll?.();
  show({ name: "picker" });
}

function setupProfileButton() {
  const b = $("#profile-btn");
  const m = $("#profile-menu");
  if (!b || !m) return;
  b.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!m.hidden) return closeMenu();
    m.innerHTML = menuHtml();
    m.hidden = false;
    b.setAttribute("aria-expanded", "true");
    m.querySelector("button")?.focus();
  });
  m.addEventListener("click", (e) => {
    const a = e.target.closest("[data-pm]")?.dataset.pm;
    if (!a) return;
    closeMenu();
    if (a === "switch") return switchProfile();
    if (a === "me") return openSettings("me");
    if (a === "profiles") return openSettings("profiles");
    if (a === "lock") return lockNow();
    if (a === "signout") return signOut();
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#profile-menu")) closeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  onChange((what) => { if (what === "all" && session?.signed_in) renderProfileButton(); });
}

// ---------- the wall panel's idle lock ----------
function setupIdleLock() {
  const wake = () => { lastActivity = Date.now(); };
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, wake, { capture: true }));
  setInterval(() => {
    if (!session?.signed_in || !session.panel || session.auto) return;
    const mins = Number(store.settings.lock_after_minutes ?? session.display?.lock_after_minutes ?? 10);
    if (mins > 0 && Date.now() - lastActivity > mins * 60_000) lockNow();
  }, 15_000);
}
