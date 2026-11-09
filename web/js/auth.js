// One-tap profile picker, optional password sign-in, and switch / sign out.
//
// The server decides everything (app/api/auth.py): this file only shows the right
// screen. Signed out, the app's data is wiped and hidden, so the last person's
// devices never show through the glass.

import { api } from "./api.js";
import { $, esc, icon, toast } from "./util.js";
import { store, onChange } from "./store.js";
import { applyTransparency } from "./glass.js";
import { openSettings } from "./settings.js";
import { applyTypography } from "./typography.js";

let session = null;          // the last answer from /auth/session
let hooks = {};
let view = { name: "picker" };   // picker | password | email
let switching = false;       // picking another profile while signed in: Cancel goes back
let busy = false;

const root = () => $("#signin");

export const currentSession = () => session;

export function avatar(p, size = "") {
  return `<span class="avatar ${size}" style="--av:${esc(p?.color || "#f2b35b")}" aria-hidden="true">${esc(p?.initial || "?")}</span>`;
}

// hooks.signedIn(): load this profile's panel. hooks.signedOut(display): wipe it.
export async function startAuth(h) {
  hooks = h;
  window.addEventListener("hp:signin", () => { if (session?.signed_in) refresh(); });
  setupProfileButton();
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
  show({ name: "picker" });
}

// The look of the panel before anyone signs in (background, glass).
function applyDisplay(d = {}) {
  const r = document.documentElement;
  applyTypography(d.font_size);
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
      <div class="avatars" role="list">${list.map((p) => `
        <button class="avatar-choice" role="listitem" data-pick="${esc(p.id)}" aria-label="${esc(p.name)}">
          ${avatar(p, "xl")}<span class="avatar-name">${esc(p.name)}</span></button>`).join("")}</div>
      <div class="signin-foot">
        <button class="btn" data-view="email">Sign in with email</button>
        ${switching ? `<button class="btn" data-cancel>Cancel</button>` : ""}
      </div>
      ${errorLine}
      <p class="signin-hint">Profiles without a password open with one tap. Use a trusted network.</p>
      ${session.demo ? `<p class="signin-hint">Demo: choose Sam, or use Owner's password: homepanel.</p>` : ""}
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
    showError(e.message);
  } finally {
    busy = false;
  }
}

function pick(id) {
  const p = profile(id);
  if (!p) return;
  if (p.has_password) show({ name: "password", id });
  else signIn({ profile_id: id });
}

function bind() {
  const el = root();
  el.addEventListener("click", (e) => {
    const t = (sel) => e.target.closest(sel);
    if (t("[data-pick]")) return pick(t("[data-pick]").dataset.pick);
    if (t("[data-cancel]")) { switching = false; hide(); return; }
    if (t("button[data-view]")) {
      const v = t("button[data-view]");
      return show({ name: v.dataset.view, id: v.dataset.id || view.id });
    }
  });
  el.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const v = Object.fromEntries(new FormData(f).entries());
    if (f.matches("[data-signin-password]")) return signIn({ profile_id: view.id, password: v.password });
    if (f.matches("[data-signin-email]")) return signIn({ email: v.email, password: v.password });
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
    ${admin ? item("profiles", "users", "Profiles") : ""}
    ${session.auto ? "" : item("signout", "door", "Sign out")}`;
}

function closeMenu() {
  const m = $("#profile-menu");
  if (m) m.hidden = true;
  $("#profile-btn")?.setAttribute("aria-expanded", "false");
}

async function signOut() {
  try {
    session = await api.signOut();
  } catch (e) { toast(e.message, true); return; }
  hooks.signedOut?.(session?.display || {});
  refresh();
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
    if (a === "signout") return signOut();
  });
  document.addEventListener("click", (e) => { if (!e.target.closest("#profile-menu")) closeMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  onChange((what) => { if (what === "all" && session?.signed_in) renderProfileButton(); });
}
