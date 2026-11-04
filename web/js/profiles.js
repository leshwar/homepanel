// Settings → Profiles (admins): who can use the panel, how they sign in, which
// devices each profile sees; and "This screen" (make it the wall panel, lock time).
// Settings → Your profile (everyone): name, colour, email, PIN and password.

import { api } from "./api.js";
import { store, reload } from "./store.js";
import { $, esc, icon, toast } from "./util.js";
import { registerViews, page, row, back, rerender, currentView } from "./settings.js";
import { avatar, currentSession } from "./auth.js";

const COLORS = ["#f2b35b", "#7cc7a5", "#96a6ff", "#ff8a7a", "#e59ad8", "#6fc3df", "#c3d36b", "#b9a1ff"];
const LOCK_TIMES = [[0, "Never"], [2, "2 minutes"], [5, "5 minutes"], [10, "10 minutes"], [30, "30 minutes"], [60, "1 hour"]];

const signInText = (p) => [p.has_pin && "PIN", p.has_password && "password"].filter(Boolean).join(" and ") || "no sign-in yet";
const accessText = (p) => p.role === "admin" ? "Admin, all devices"
  : p.devices === "all" ? "Member, all devices" : `Member, ${p.devices.length} ${p.devices.length === 1 ? "device" : "devices"}`;

const colorChoices = (current) => `<span class="field"><span>Colour</span></span>
  <div class="color-choices" role="radiogroup" aria-label="Colour">${COLORS.map((c) => `
    <label class="color-choice"><input type="radio" name="color" value="${c}" ${c === current ? "checked" : ""}>
      <span style="--av:${c}" aria-label="${c}"></span></label>`).join("")}</div>`;

// PIN and password fields: blank keeps what's saved.
function secretFields(p) {
  return `
    <label class="field"><span>PIN (4 to 6 digits, for the wall panel)</span>
      <input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,6}" maxlength="6" autocomplete="off"
        placeholder="${p?.has_pin ? "Saved. Leave blank to keep it." : "No PIN"}"></label>
    ${p?.has_pin ? `<label class="check"><input type="checkbox" name="clear_pin"><span>Remove the PIN</span></label>` : ""}
    <label class="field"><span>Password (at least 8 characters, for phones and laptops)</span>
      <input name="password" type="password" autocomplete="new-password" minlength="8"
        placeholder="${p?.has_password ? "Saved. Leave blank to keep it." : "No password"}"></label>
    ${p?.has_password ? `<label class="check"><input type="checkbox" name="clear_password"><span>Remove the password</span></label>` : ""}
    <small class="field"><small>A password needs an email address: you sign in with both.</small></small>`;
}

function secretValues(fd) {
  const out = {};
  if (fd.get("pin")) out.pin = fd.get("pin");
  else if (fd.has("clear_pin")) out.pin = null;
  if (fd.get("password")) out.password = fd.get("password");
  else if (fd.has("clear_password")) out.password = null;
  return out;
}

function devicePicker(p) {
  const chosen = new Set(Array.isArray(p?.devices) ? p.devices : []);
  const all = !p || p.devices === "all";
  const groups = [...store.rooms, ""].map((r) => {
    const list = [...store.devices.values()].filter((d) => (r ? d.room === r : !store.rooms.includes(d.room)));
    if (!list.length) return "";
    return `<p class="group-label">${esc(r || "No room")}</p>${list.map((d) => `
      <label class="check"><input type="checkbox" name="device" value="${esc(d.id)}" ${chosen.has(d.id) ? "checked" : ""}>
        <span>${esc(d.name)}</span></label>`).join("")}`;
  }).join("");
  return `<div class="card" data-access ${p?.role === "admin" ? "hidden" : ""}>
    <h3>Devices this profile can use</h3>
    <label class="check"><input type="radio" name="access" value="all" ${all ? "checked" : ""}><span>All devices, including new ones</span></label>
    <label class="check"><input type="radio" name="access" value="some" ${all ? "" : "checked"}><span>Only the devices I choose</span></label>
    <div class="device-picks" ${all ? "hidden" : ""}>${groups || "<p>No devices yet.</p>"}</div>
  </div>`;
}

registerViews({
  async profiles() {
    const s = currentSession() || {};
    const lockAfter = Number(store.settings.lock_after_minutes ?? 10);
    page("Profiles and sign-in", `
      <div class="list" data-profile-list>${store.profiles.map((p) =>
        row(`data-go=profile data-arg="${esc(p.id)}"`, avatar(p), p.name + (p.id === store.me?.id ? " (you)" : ""),
            `${accessText(p)} · ${signInText(p)}`)).join("")}</div>
      <button class="btn primary" data-go="profile">${icon("plus")}Add a profile</button>
      <form class="card" data-this-screen style="margin-top:20px">
        <h3>This screen</h3>
        ${s.auto ? `<p>Demo mode: nobody needs to sign in. Start the demo with --sign-in to try it like a real panel.</p>` : `
        <label class="check"><input type="checkbox" name="panel" ${s.panel ? "checked" : ""}>
          <span>This screen is the wall panel: it stays signed in and goes back to the profile picker when nobody is using it</span></label>`}
        <label class="field"><span>The wall panel goes back to the profile picker after</span><select name="lock_after_minutes">
          ${LOCK_TIMES.map(([v, l]) => `<option value="${v}" ${lockAfter === v ? "selected" : ""}>${l}</option>`).join("")}
        </select><small>Phones and laptops stay signed in for 30 days after they're last used.</small></label>
        <div class="btn-row"><button class="btn primary" type="submit">Save</button></div>
      </form>
      <div class="card">
        <h3>Home page for new profiles</h3>
        <p>New profiles start with the same Home page. Each person can then change their own.</p>
        <div class="btn-row"><button class="btn" data-layout-default>Use my Home page for new profiles</button></div>
      </div>`);
  },

  profile(id) {
    const p = id ? store.profiles.find((x) => x.id === id) : null;
    if (id && !p) return back();
    const color = p?.color || COLORS[store.profiles.length % COLORS.length];
    page(p ? p.name : "Add a profile", `
      <form data-profile-form="${esc(id || "")}">
        <div class="card">
          <div class="profile-preview">${avatar({ ...p, color, initial: (p?.name || "?")[0] }, "lg")}</div>
          <label class="field"><span>Name</span><input name="name" value="${esc(p?.name || "")}" maxlength="24" required autocomplete="off"></label>
          ${colorChoices(color)}
          <label class="field"><span>Email (optional, to sign in with a password)</span>
            <input name="email" type="email" value="${esc(p?.email || "")}" autocomplete="off" spellcheck="false"></label>
          <label class="field"><span>Role</span><select name="role">
            <option value="member" ${p?.role !== "admin" ? "selected" : ""}>Member: uses the devices you choose</option>
            <option value="admin" ${p?.role === "admin" ? "selected" : ""}>Admin: can also add devices and change settings</option>
          </select></label>
        </div>
        <div class="card"><h3>Sign-in</h3>${secretFields(p)}</div>
        ${devicePicker(p)}
        <div class="btn-row">
          <button class="btn primary" type="submit">${p ? "Save" : "Add profile"}</button>
          ${p && p.id !== store.me?.id ? `<button class="btn danger" type="button" data-profile-del="${esc(p.id)}">${icon("trash")}Remove profile</button>` : ""}
        </div>
      </form>`);
  },

  me() {
    const p = store.me;
    if (!p) return back();
    page("Your profile", `
      <form data-me-form>
        <div class="card">
          <div class="profile-preview">${avatar(p, "lg")}</div>
          <label class="field"><span>Name</span><input name="name" value="${esc(p.name)}" maxlength="24" required autocomplete="off"></label>
          ${colorChoices(p.color)}
          <label class="field"><span>Email (to sign in with a password)</span>
            <input name="email" type="email" value="${esc(p.email || "")}" autocomplete="off" spellcheck="false"></label>
        </div>
        <div class="card"><h3>Sign-in</h3>${secretFields(p)}</div>
        <div class="btn-row"><button class="btn primary" type="submit">Save</button></div>
      </form>
      <div class="card"><h3>Your Home page</h3><p>Long-press the Home page to arrange it. Only your profile sees your changes.</p>
        <div class="btn-row"><button class="btn" data-layout-reset>Start again from the default</button></div></div>`);
  },
});

// ---------- events ----------
const root = $("#settings");

root.addEventListener("change", (e) => {
  const form = e.target.closest("[data-profile-form]");
  if (!form) return;
  if (e.target.name === "access") form.querySelector(".device-picks").hidden = e.target.value === "all";
  if (e.target.name === "role") form.querySelector("[data-access]").hidden = e.target.value === "admin";
});

root.addEventListener("click", async (e) => {
  const t = (sel) => e.target.closest(sel);
  try {
    if (t("[data-profile-del]")) {
      const p = store.profiles.find((x) => x.id === t("[data-profile-del]").dataset.profileDel);
      if (!p || !confirm(`Remove ${p.name}'s profile? Their screens are signed out.`)) return;
      await api.deleteProfile(p.id);
      toast("Profile removed");
      await reload();
      return back();
    }
    if (t("[data-layout-default]")) {
      await api.saveSettings({ home_layout: store.settings.home_layout });
      return toast("New profiles will start with your Home page");
    }
    if (t("[data-layout-reset]")) {
      if (!confirm("Put your Home page back to the default?")) return;
      await api.saveLayout(null);
      await reload();
      return toast("Home page reset");
    }
  } catch (err) { toast(err.message, true); }
});

root.addEventListener("submit", async (e) => {
  const form = e.target;
  if (!form.matches("[data-profile-form], [data-me-form], [data-this-screen]")) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  const fd = new FormData(form);
  try {
    if (form.matches("[data-this-screen]")) {
      await api.saveSettings({ lock_after_minutes: Number(fd.get("lock_after_minutes")) });
      const s = currentSession();
      if (s && !s.auto && fd.has("panel") !== !!s.panel) Object.assign(s, await api.setPanel(fd.has("panel")));
      toast("Saved");
      await reload();
      return rerender();
    }
    const base = { name: fd.get("name"), color: fd.get("color"), email: fd.get("email"), ...secretValues(fd) };
    if (form.matches("[data-me-form]")) {
      await api.updateMe(base);
      toast("Saved");
      await reload();
      return back();
    }
    const id = form.dataset.profileForm;
    const body = { ...base, role: fd.get("role"),
                   devices: fd.get("access") === "some" ? fd.getAll("device") : "all" };
    if (id) await api.updateProfile(id, body);
    else await api.addProfile(body);
    toast(id ? "Saved" : `${body.name} can now sign in`);
    await reload();
    if (currentView()?.view === "profile") back();
  } catch (err) { toast(err.message, true); }
});
