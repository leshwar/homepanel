// Settings: add devices (search or by IP), edit devices, rooms, scenes, display, diagnostics.
// Text entry (API keys etc.) is easiest from a phone or laptop: open http://<panel>.local:8080

import { api } from "./api.js";
import { store, reload, addRoom, saveRooms } from "./store.js";
import { roomGrip, roomEditButton, roomNameField, roomNameHelp, editableRoomNames, syncRoomSorters, isSortingRooms, isEditingRooms, isEditingRoomName, canLeaveRoomNames, toggleRoomEditing } from "./room-sort.js";
import { $, esc, icon, kindIcon, toast } from "./util.js";
import { applyTransparency } from "./glass.js";
import { openFrame } from "./photoframe.js";
import { FACES, faceId, faceHTML, faceInfo } from "./clockfaces.js";
import { findLocation, describeFound, canUseDeviceLocation } from "./locate.js";
import { DEVICE_ICONS, deviceIconName, svg } from "./icons.js";
import { invalidateWallpapers, previewWallpaper } from "./wallpaper.js";
import { previewTiles } from "./tone.js";
import { devicePicture } from "./art.js";
import { FONT_SIZES, FONT_SIZE_NAMES, previewTypography } from "./typography.js";
import { buildWhen, whenText } from "./automation-text.js";

const SCENE_ICONS = ["sun", "moon", "film", "sparkle", "coffee", "door"];
let stack = [];
let brandState = {};          // per-visit state of the "brand" screen
let searchAll = {};           // per-visit state of "Search all brands" on the "add" screen
let photoSettingsEpoch = 0;

export const isSettingsOpen = () => !$("#settings").hidden;

export function openSettings(view = "home", arg = null) {
  stack = view === "home" ? [{ view: "home" }] : [{ view: "home" }, { view, arg }];
  if (view === "scene-new") stack = [{ view: "home" }, { view: "scenes" }, { view, arg }];
  $("#settings").hidden = false;
  render();
}

function close() { $("#settings").hidden = true; stack = []; dropPreview(); }
// Leaving Display settings without saving: back to the saved look.
function dropPreview() { previewWallpaper(null); previewTiles(null); previewTypography(null); }
export const closeSettings = close;
export function go(view, arg = null) { stack.push({ view, arg }); if (view === "brand") brandState = {}; if (view === "add") searchAll = {}; render(); $("#settings").scrollTop = 0; }
export function back() {
  if (!canLeaveRoomNames()) return;
  if (stack.at(-1)?.view === "display") dropPreview();
  stack.pop(); stack.length ? render() : close();
}

export function refreshSettings() {
  if (!isSettingsOpen() || isSortingRooms() || isEditingRoomName()) return;
  const top = stack.at(-1);
  if (top && ["home", "devices", "scenes", "rooms", "automations", "location", "profiles"].includes(top.view)) render();
}

// ---------- rendering ----------
export function page(title, body, { closeBtn = false } = {}) {
  $("#settings").innerHTML = `<div class="page-inner">
    <div class="page-head">
      <button class="icon-btn" data-back aria-label="${stack.length > 1 ? "Back" : "Close"}">${icon(stack.length > 1 ? "left" : "close")}</button>
      <h1>${esc(title)}</h1>
      ${closeBtn && stack.length > 1 ? `<button class="icon-btn" data-close aria-label="Close">${icon("close")}</button>` : ""}
    </div>${body}</div>`;
  syncRoomSorters();
}

export const row = (attrs, iconName, title, sub = "", extra = "") =>
  `<button class="row" ${attrs}>${iconName?.startsWith?.("<") ? iconName : iconName ? icon(iconName, "dim") : ""}<span class="grow">
    <span class="title">${esc(title)}</span>${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</span>${extra}${icon("right", "dim")}</button>`;

export const roomAddForm = (className = "card", value = "") => `<form class="${className}" data-room-add>
  <label class="field"><span>New room</span><input name="room" maxlength="24" placeholder="Office" value="${esc(value)}" required></label>
  <button class="btn primary" type="submit">Add room</button>
  <button class="btn" type="button" data-room-add-cancel>Cancel</button>
</form>`;

function searchAllResults(r) {
  const found = r.found.length ? `<div class="list" data-search-all-results>${r.found.map((f) => `
      <div class="row">${icon(kindIcon({ kind: f.kind }), "dim")}
        <span class="grow"><span class="title">${esc(f.name)}</span><span class="sub">${esc(f.adapter_name)}${f.detail ? ` · ${esc(f.detail)}` : ""}</span></span>
        ${f.added ? `<span class="sub">Added</span>` :
          `<button class="btn small primary" data-add-found="${esc(f.uid)}" data-adapter="${esc(f.adapter)}" data-name="${esc(f.name)}">Add</button>`}
      </div>`).join("")}</div>` :
    `<div class="card"><h3>Nothing found</h3><p>Make sure the devices are set up in their own app first and are on the same Wi-Fi as this panel.
           If they still don't show up, choose the brand below and add them by IP address.</p></div>`;
  const extra = [
    ...r.needs_account.map((b) => row(`data-go=brand data-arg="${esc(b.adapter)}"`, "link", b.adapter_name, "Not searched. Connect your account first.")),
    ...r.failed.map((b) => row(`data-go=brand data-arg="${esc(b.adapter)}"`, "wifi-off", b.adapter_name, b.error)),
  ];
  return found + (extra.length ? `<div class="list" data-search-all-skipped>${extra.join("")}</div>` : "");
}

const VIEWS = {
  home() {
    if (store.me && store.me.role !== "admin") return VIEWS.member();
    const n = store.devices.size;
    const attention = [...store.devices.values()].filter((d) => d.state?.online === false || d.state?.needs_pairing).length;
    page("Settings", `
      ${store.demo ? `<div class="note">You're in demo mode. These are pretend devices; nothing on your network is changed.</div>` : ""}
      <div class="list">
        ${row("data-go=add", "plus", "Add a device", "Plugs, lights and TVs on your Wi-Fi")}
        ${row("data-go=devices", "bulb", "Devices", `${n} ${n === 1 ? "device" : "devices"}`,
              attention ? `<span class="badge">${attention} need attention</span>` : "")}
        ${row("data-go=scenes", "sparkle", "Scenes", `${store.scenes.length} saved`)}
        ${row("data-go=automations", "clock", "Schedules and automations",
              `${store.automations.filter((a) => a.enabled).length} active`)}
        ${row("data-go=rooms", "home", "Rooms", store.rooms.join(", ") || "None yet")}
      </div>
      <div class="list">
        ${row("data-go=location", "users", "Location and presence",
              store.settings.latitude != null ? `${store.presence.length} ${store.presence.length === 1 ? "person" : "people"} watched` : "Set your location for sunrise and sunset")}
        ${row("data-go=photos", "image", "Photo frame", store.settings.idle_screen === "photos"
              ? "Shows when the panel is idle" : "Slideshow of your photos")}
        ${row('data-go="photo-library"', "image", "Photo library", "Connect an album for the Home Photos tile")}
        ${row("data-go=display", "sun", "Display and clock")}
        ${row("data-go=profiles", "users", "Profiles", profilesSummary())}
        ${row("data-go=diagnostics", "pulse", "Diagnostics and logs")}
      </div>
      <p class="group-label">Tip: typing is easier from a phone or laptop. Open this panel's address in any browser on your Wi-Fi.</p>`);
  },

  // Members: their own profile only. Devices, rooms and settings are for admins.
  member() {
    page("Settings", `
      <div class="list">${row("data-go=me", "users", "Your profile", "Name, colour and optional password")}</div>
      <div class="card"><h3>Want more devices here?</h3>
        <p>Adding devices, rooms and panel settings is for admins. Ask an admin to share more devices with your profile.</p></div>`);
  },

  devices() {
    const groups = [...store.rooms, ""].map((r) => {
      const list = [...store.devices.values()].filter((d) => (r ? d.room === r : !store.rooms.includes(d.room)));
      if (!list.length) return "";
      return `<p class="group-label">${esc(r || "No room")}</p><div class="list">${list.map((d) => {
        const s = d.state || {};
        const warn = s.needs_pairing ? "Needs pairing" : s.online === false ? "Offline" : "";
        return row(`data-go=device data-arg="${esc(d.id)}"`, svg(deviceIconName(d), "dim"), d.name, d.adapter_name,
                   warn ? `<span class="badge">${warn}</span>` : "");
      }).join("")}</div>`;
    }).join("");
    page("Devices", (groups || `<div class="card"><h3>No devices yet</h3><p>Add plugs, lights and TVs from your Wi-Fi.</p></div>`) +
      `<button class="btn primary" data-go="add">${icon("plus")}Add a device</button>`);
  },

  device(id) {
    const d = store.devices.get(id);
    if (!d) return back();
    const s = d.state || {};
    page(d.name, `
      ${s.needs_pairing ? `<div class="note">${esc(s.error || "Needs pairing.")}</div>` : ""}
      ${s.online === false ? `<div class="note warn">${esc(s.error || "Not responding.")}</div>` : ""}
      <div class="card">
        <label class="field"><span>Name</span><input id="d-name" value="${esc(d.name)}" maxlength="40"></label>
        <label class="field"><span>Room</span><select id="d-room">
          <option value="">No room</option>
          ${store.rooms.map((r) => `<option ${r === d.room ? "selected" : ""}>${esc(r)}</option>`).join("")}
        </select></label>
        <span class="field"><span>Picture</span></span>
        <div class="dev-pic-row">
          <div class="tile-icon pic ${devicePicture(d)?.kind || ""}" id="d-pic-preview">${devicePicture(d)?.html || svg(deviceIconName(d))}</div>
          <div class="btn-row" style="margin:0">
            <label class="btn">${icon("image")}${d.picture ? "Change photo" : "Choose a photo"}
              <input type="file" id="d-pic-input" data-device="${esc(id)}" accept="image/*,.tif,.tiff" hidden></label>
            ${d.picture ? `<button class="btn" type="button" data-clear-pic="${esc(id)}">Remove photo</button>` : ""}
          </div>
        </div>
        <small class="field"><small>A photo of your own ${esc(d.name)} shows on its tile. A PNG with a see-through
          background looks best. Without a photo, "Auto" below shows a drawing of the device.</small></small>
        <span class="field"><span>Icon</span></span>
        <div class="icon-choices" role="radiogroup" aria-label="Icon">
          <label class="icon-choice"><input type="radio" name="d-icon" value="" ${!d.icon ? "checked" : ""}>
            <span>${svg(deviceIconName({ ...d, icon: "" }))}<small>Auto</small></span></label>
          ${DEVICE_ICONS.map((ic) => `<label class="icon-choice"><input type="radio" name="d-icon" value="${ic}" ${d.icon === ic ? "checked" : ""}>
            <span aria-label="${ic}">${svg(ic)}</span></label>`).join("")}
        </div>
        ${d.kind === "tv" ? `<label class="field"><span>MAC address (used to turn the TV on)</span>
          <input id="d-mac" value="${esc(d.mac || "")}" placeholder="AA:BB:CC:DD:EE:FF" autocomplete="off" spellcheck="false">
          <small>${d.mac ? "Found automatically." : "Usually found automatically after the panel has talked to the TV while it's on."}
            On the TV: Settings → General → Network → Advanced settings.</small></label>` : ""}
        ${["plug", "switch"].includes(d.kind) ? `<label class="check"><input type="checkbox" id="d-keep" ${d.keep_on ? "checked" : ""}>
          <span>Keep on during "All off" (for a fridge, router or aquarium)</span></label>` : ""}
        <div class="btn-row"><button class="btn primary" data-save-device="${esc(id)}">Save</button></div>
      </div>
      <div class="card">
        <h3>Connection</h3>
        <p>${esc(d.adapter_name)}${d.meta?.model ? `, ${esc(d.meta.model)}` : ""}</p>
        <div class="btn-row" style="margin-top:0">
          ${d.kind === "tv" || s.needs_pairing ? `<button class="btn" data-pair="${esc(id)}">${icon("link")}Pair again</button>` : ""}
          <button class="btn" data-refresh="${esc(id)}">${icon("search")}Check now</button>
          <button class="btn danger" data-remove="${esc(id)}">${icon("trash")}Remove</button>
        </div>
      </div>`, { closeBtn: true });
  },

  add() {
    const list = store.adapters.filter((a) => !a.hidden);
    const st = searchAll;
    page("Add a device", `
      <div class="card" data-search-all-card>
        <h3>Search all brands</h3>
        <p>Look for every plug, light and TV on your Wi-Fi at once. This can take up to half a minute.</p>
        <label class="field"><span>Put new devices in</span><select id="add-room">
          <option value="">No room</option>${store.rooms.map((r) => `<option ${r === st.room ? "selected" : ""}>${esc(r)}</option>`).join("")}
        </select></label>
        <div class="btn-row"><button class="btn primary" data-discover-all ${st.searching ? "disabled" : ""}>
          ${icon("search")}${st.searching ? "Searching all brands…" : st.result ? "Search again" : "Search all brands"}</button></div>
      </div>
      ${st.result ? searchAllResults(st.result) : ""}
      <p class="group-label">Or choose the brand. Most plugs sold as "works with Smart Life" use Tuya.</p>
      <div class="list">${list.map((a) => row(`data-go=brand data-arg="${esc(a.id)}"`, kindIcon({ kind: a.kinds[0] }), a.name,
        a.available ? a.brands : a.unsupported ? `Not available on this panel: ${a.unsupported}`
          : `Not installed on this panel (needs ${a.missing.join(", ")})`)).join("")}</div>`, { closeBtn: true });
  },

  brand(id) {
    const a = store.adapters.find((x) => x.id === id);
    if (!a) return back();
    const st = brandState;
    if (!a.available && a.unsupported) {
      return page(a.name, `<div class="note warn">${esc(a.name)} can't run on this panel. ${esc(a.unsupported)}.
        See docs/DEVICE_SETUP.md for how to set it up.</div>`, { closeBtn: true });
    }
    if (!a.available) {
      return page(a.name, `<div class="note warn">Support for ${esc(a.name)} isn't installed. On the panel, run
        <b>./scripts/install.sh</b> again, or <b>pip install ${esc(a.missing.join(" "))}</b>.</div>`, { closeBtn: true });
    }
    const needsAccount = a.account_fields.some((f) => f.required) && !a.account_set;
    const accountCard = a.account_fields.length ? `
      <div class="card">
        <h3>${a.account_set ? "Account connected" : "Connect your account"}</h3>
        <p>${esc(a.description)}</p>
        <form data-account="${esc(id)}">
          ${a.account_fields.map((f) => fieldHtml(f, st.account?.[f.key])).join("")}
          <div class="btn-row"><button class="btn primary" type="submit">Save</button>
          ${a.account_actions.map((x) => `<button class="btn" type="button" data-account-action="${esc(x.id)}">${esc(x.label)}</button>`).join("")}</div>
          ${a.account_actions.map((x) => x.help ? `<small class="field"><small>${esc(x.help)}</small></small>` : "").join("")}
        </form>
      </div>` : `<p class="group-label">${esc(a.description)}</p>`;

    const found = st.found;
    const results = found ? (found.length ? `<div class="list">${found.map((f) => `
        <div class="row">${icon(kindIcon({ kind: f.kind }), "dim")}
          <span class="grow"><span class="title">${esc(f.name)}</span><span class="sub">${esc(f.detail)}</span></span>
          ${f.added ? `<span class="sub">Added</span>` :
            `<button class="btn small primary" data-add-uid="${esc(f.uid)}" data-name="${esc(f.name)}">Add</button>`}
        </div>`).join("")}</div>` :
      `<div class="card"><h3>Nothing found</h3><p>Make sure the devices are set up in their own app first and are on the same Wi-Fi as this panel.
             If they still don't show up, add them by IP address.</p></div>`) : "";

    page(a.name, `
      ${store.demo ? `<div class="note">Internal test fixtures, not household data. Use the existing native panel on port 8080 for real devices.</div>` : ""}
      ${accountCard}
      ${needsAccount ? "" : `
      <div class="card">
        <h3>Find devices</h3>
        <label class="field"><span>Put new devices in</span><select id="add-room">
          <option value="">No room</option>${store.rooms.map((r) => `<option ${r === st.room ? "selected" : ""}>${esc(r)}</option>`).join("")}
        </select></label>
        <div class="btn-row">
          ${a.can_discover ? `<button class="btn primary" data-discover ${st.searching ? "disabled" : ""}>${icon("search")}${st.searching ? "Searching…" : "Search my Wi-Fi"}</button>` : ""}
          ${a.manual_fields.length ? `<button class="btn" data-manual-toggle>Add by IP address</button>` : ""}
        </div>
      </div>
      ${results}
      ${st.manual ? `<div class="card"><h3>Add by IP address</h3><form data-manual>
          ${a.manual_fields.map((f) => fieldHtml(f)).join("")}
          <div class="btn-row"><button class="btn primary" type="submit">Add device</button></div></form></div>` : ""}`}
    `, { closeBtn: true });
    if (!st.account && a.account_fields.length) {
      st.account = {};
      api.getAccount(id).then((v) => { st.account = v; if (stack.at(-1)?.arg === id) VIEWS.brand(id); }).catch(() => {});
    }
  },

  scenes() {
    page("Scenes", `
      <p class="group-label">A scene sets several devices at once with one tap.</p>
      ${store.scenes.length ? `<div class="list">${store.scenes.map((s) => `
        <div class="row">${icon(SCENE_ICONS.includes(s.icon) ? s.icon : "sparkle", "dim")}
          <span class="grow"><span class="title">${esc(s.name)}</span><span class="sub">${s.actions.length} ${s.actions.length === 1 ? "step" : "steps"}</span></span>
          <button class="btn small danger" data-del-scene="${esc(s.id)}" aria-label="Delete ${esc(s.name)}">${icon("trash")}</button>
        </div>`).join("")}</div>` : ""}
      <button class="btn primary" data-go="scene-new">${icon("plus")}New scene</button>`);
  },

  "scene-new"() {
    const devices = [...store.devices.values()].filter((d) => d.caps.includes("power"));
    page("New scene", `
      <form data-scene-form>
        <div class="card">
          <label class="field"><span>Name</span><input name="name" required maxlength="24" placeholder="Movie night"></label>
          <span class="field"><span>Icon</span></span>
          <div class="chips" role="radiogroup">${SCENE_ICONS.map((ic, i) => `
            <label class="chip" style="display:grid;place-items:center;width:64px;padding:0">
              <input type="radio" name="icon" value="${ic}" ${i === 0 ? "checked" : ""} style="position:absolute;opacity:0">${icon(ic)}</label>`).join("")}</div>
        </div>
        <p class="group-label">First set the devices the way you want them, then pick them here. The scene saves how each one is right now.</p>
        <div class="list">${devices.map((d) => `
          <label class="row check"><input type="checkbox" name="capture" value="${esc(d.id)}">
            <span class="grow"><span class="title">${esc(d.name)}</span><span class="sub">${esc(d.room || "No room")}, ${d.state?.on ? "on" : "off"}</span></span></label>`).join("")}</div>
        <button class="btn primary" type="submit">Save scene</button>
      </form>`, { closeBtn: true });
    const form = $("[data-scene-form]");
    form.addEventListener("change", (e) => {
      if (e.target.name === "icon") form.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", c.contains(e.target)));
    });
    form.querySelector(".chip")?.setAttribute("aria-pressed", "true");
  },

  rooms(focus) {
    const editing = isEditingRooms();
    page("Rooms", `
      <div class="room-settings-tools">${roomEditButton()}</div>
      ${editing ? roomNameHelp() + '<p class="group-label">Drag the handles to reorder rooms. With a keyboard, focus a handle and use the arrow keys.</p>' : ""}
      <div class="list" data-room-sort="vertical">${(editing ? editableRoomNames(store.rooms) : store.rooms).map((r) => `
        <div class="row room-settings-row" data-sort-room="${esc(r)}">${editing ? roomNameField(r) : `<span class="grow"><span class="title">${esc(r)}</span></span>`}
          ${editing ? `<button class="btn small" data-room-layout="${esc(r)}" aria-label="Edit ${esc(r)} tiles">Edit tiles</button>
          ${roomGrip(r)}
          <button class="btn small danger" data-room-del="${store.rooms.indexOf(r)}" aria-label="Delete ${esc(r)}" ${store.rooms.includes(r) ? "" : "disabled"}>${icon("trash")}</button>` : ""}</div>`).join("")}</div>
      ${editing ? roomAddForm() : ""}`);
    if (focus === "add" && editing) {
      const input = $("#settings [data-room-add] input");
      input.focus();
      input.scrollIntoView({ block: "center" });
    }
  },

  automations() {
    const items = store.automations;
    page("Schedules and automations", `
      <p class="group-label">Run a scene or switch things on and off by themselves.</p>
      ${items.length ? `<div class="list">${items.map((a) => `
        <div class="row">
          <label class="check" style="min-height:0"><input type="checkbox" data-auto-toggle="${esc(a.id)}" ${a.enabled ? "checked" : ""}
            aria-label="${a.enabled ? "Turn off" : "Turn on"} ${esc(a.name)}"></label>
          <span class="grow"><span class="title">${esc(a.name)}</span>
            <span class="sub">${esc(whenText(a, (id) => store.devices.get(id)?.name))}${a.last_result && !String(a.last_result).startsWith("ok") ? `. Last run: ${esc(a.last_result)}` : ""}</span></span>
          <button class="btn small" data-auto-run="${esc(a.id)}">Run now</button>
          <button class="btn small danger" data-auto-del="${esc(a.id)}" aria-label="Delete ${esc(a.name)}">${icon("trash")}</button>
        </div>`).join("")}</div>` : ""}
      <button class="btn primary" data-go="automation-new">${icon("plus")}New automation</button>`);
  },

  "automation-new"() {
    const plugsAndLights = [...store.devices.values()].filter((d) => d.caps.includes("power"));
    const hasLoc = store.settings.latitude != null;
    const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    page("New automation", `
      <form data-auto-form>
        <div class="card">
          <h3>When</h3>
          <label class="field"><span>Trigger</span><select name="when">
            <option value="time">At a time of day</option>
            <option value="sunset" ${hasLoc ? "" : "disabled"}>At sunset${hasLoc ? "" : " (set your location first)"}</option>
            <option value="sunrise" ${hasLoc ? "" : "disabled"}>At sunrise${hasLoc ? "" : " (set your location first)"}</option>
            <option value="all_away">When everyone leaves home</option>
            <option value="someone_home">When someone comes home</option>
            <option value="device_on" ${plugsAndLights.length ? "" : "disabled"}>When a device turns on</option>
            <option value="device_off" ${plugsAndLights.length ? "" : "disabled"}>When a device turns off</option>
          </select></label>
          <div data-show="time">
            <label class="field"><span>Time</span><input type="time" name="at" value="07:00"></label>
            <div class="chips" role="group" aria-label="Days">${days.map((d, i) => `
              <label class="chip day"><input type="checkbox" name="days" value="${i}" checked>${d}</label>`).join("")}</div>
          </div>
          <div data-show="sun" hidden>
            <label class="field"><span>Offset</span><select name="offset_min">
              ${[[-60, "1 hour before"], [-30, "30 minutes before"], [-15, "15 minutes before"], [0, "Exactly then"],
                 [15, "15 minutes after"], [30, "30 minutes after"], [60, "1 hour after"]].map(([v, l]) =>
                `<option value="${v}" ${v === 0 ? "selected" : ""}>${l}</option>`).join("")}
            </select></label>
          </div>
          <div data-show="watch" hidden>
            <label class="field"><span>Device to watch</span><select name="watch_id">
              ${plugsAndLights.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}${d.room ? ` (${esc(d.room)})` : ""}</option>`).join("")}
            </select></label>
            <p>It runs however the device was switched: from the panel, its own remote or an app.</p>
          </div>
          <div data-show="presence" hidden>
            <p>${store.presence.length ? `Watching ${store.presence.map((p) => esc(p.name)).join(", ")}.` :
              `Add people's phones first in Location and presence.`}</p>
          </div>
        </div>
        <div class="card">
          <h3>Do</h3>
          <label class="field"><span>Action</span><select name="do">
            ${store.scenes.map((sc) => `<option value="scene:${esc(sc.id)}">Run scene: ${esc(sc.name)}</option>`).join("")}
            <option value="all_off">Turn everything off</option>
            <option value="device">Turn a device on or off</option>
          </select></label>
          <div data-show="device" hidden>
            <label class="field"><span>Device</span><select name="device_id">
              ${plugsAndLights.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}${d.room ? ` (${esc(d.room)})` : ""}</option>`).join("")}
            </select></label>
            <label class="field"><span>Turn it</span><select name="value"><option value="on">On</option><option value="off">Off</option></select></label>
          </div>
        </div>
        <div class="card">
          <label class="field"><span>Name (optional)</span><input name="name" maxlength="40" placeholder="Made for you if left blank"></label>
          <button class="btn primary" type="submit">Save automation</button>
        </div>
      </form>`, { closeBtn: true });
    const form = $("[data-auto-form]");
    const sync = () => {
      const w = form.when.value, d = form.do.value;
      form.querySelector('[data-show="time"]').hidden = w !== "time";
      form.querySelector('[data-show="sun"]').hidden = !["sunset", "sunrise"].includes(w);
      form.querySelector('[data-show="presence"]').hidden = !["all_away", "someone_home"].includes(w);
      form.querySelector('[data-show="watch"]').hidden = !w.startsWith("device_");
      form.querySelector('[data-show="device"]').hidden = d !== "device";
      form.querySelectorAll(".chip.day").forEach((c) => c.setAttribute("aria-pressed", c.querySelector("input").checked));
    };
    form.addEventListener("change", sync);
    sync();
  },

  async location(arg) {
    const s = store.settings;
    const forWeather = arg === "weather";      // from the Home weather card's "Turn on weather"
    page("Location and presence", `
      <form class="card" data-location>
        <h3>Your location</h3>
        <p>${forWeather && s.latitude == null
          ? "To show the weather, the panel needs to know where home is. Tap Use my location, check it, then tap Save location."
          : "Used on this panel for sunrise and sunset times and, if you turn it on, the weather."}</p>
        <button class="btn locate" type="button" data-locate>${PIN}<span>Use my location</span></button>
        <p class="locate-note"><small>${canUseDeviceLocation()
          ? "Asks this device for its location (do this at home). If it can't, the panel"
          : "The panel"} looks up your home's approximate location from its internet address at ipapi.co (or ipwho.is), and gets the place name from BigDataCloud. Nothing is sent until you tap the button, and nothing is saved until you tap Save location. Or type it in: in Google Maps, long-press your home to see its coordinates.</small></p>
        <p id="locate-status" role="status" hidden></p>
        <label class="field"><span>Latitude</span><input name="latitude" inputmode="decimal" value="${s.latitude ?? ""}" placeholder="47.61"></label>
        <label class="field"><span>Longitude</span><input name="longitude" inputmode="decimal" value="${s.longitude ?? ""}" placeholder="-122.33"></label>
        <p id="sun-today"></p>
        <label class="field"><span>Place name (optional)</span><input name="place_name" maxlength="40" value="${esc(s.place_name || "")}" placeholder="Seattle">
          <small>Shown on the resting clock. Type it, or let "Use my location" fill it in.</small></label>
        <label class="check"><input type="checkbox" name="weather_enabled" ${s.weather_enabled || forWeather ? "checked" : ""}>
          <span>Show the weather on the resting clock</span></label>
        <p><small>Weather data by <a class="link" href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>
          (<a class="link" href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>).
          The panel asks about every 20 minutes, sending your location rounded to about 1 km. No account is needed.
          Without internet it uses a recent cached reading or shows weather as unavailable.</small></p>
        <label class="field"><span>Temperature</span><select name="temperature_unit">
          ${[["F", "°F (Fahrenheit)"], ["C", "°C (Celsius)"]].map(([v, l]) => `<option value="${v}" ${(s.temperature_unit || "F") === v ? "selected" : ""}>${l}</option>`).join("")}
        </select></label>
        <div class="btn-row"><button class="btn primary" type="submit">Save location</button></div>
      </form>
      <div class="card">
        <h3>People</h3>
        <p>The panel checks whether each person's phone is on the home Wi-Fi. Give each phone a fixed IP address in your router. Someone counts as away after about 10 minutes without their phone.</p>
        ${store.presence.length ? `<div class="list" style="margin-bottom:14px">${store.presence.map((p, i) => `
          <div class="row"><span class="grow"><span class="title">${esc(p.name)}</span>
            <span class="sub">${esc(p.ip)}, ${p.home == null ? "checking…" : p.home ? "home" : "away"}</span></span>
            <button class="btn small danger" data-person-del="${i}" aria-label="Remove ${esc(p.name)}">${icon("trash")}</button></div>`).join("")}</div>` : ""}
        <form data-person-add>
          <label class="field"><span>Name</span><input name="name" maxlength="24" required placeholder="Asha"></label>
          <label class="field"><span>Phone's IP address</span><input name="ip" required placeholder="192.168.1.23" inputmode="decimal"></label>
          <button class="btn" type="submit">${icon("plus")}Add person</button>
        </form>
      </div>`);
    try {
      const sun = await api.sun();
      const fmt = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      if (sun.sunrise && $("#sun-today")) $("#sun-today").textContent = `Today: sunrise ${fmt(sun.sunrise)}, sunset ${fmt(sun.sunset)}.`;
    } catch { /* location not set */ }
  },

  async "photo-library"() {
    const epoch = ++photoSettingsEpoch;
    page("Photo library", '<div class="card"><p role="status">Loading connection settings...</p></div>');
    let config, albums = [], error = "";
    try {
      config = await api.photoLibrary();
      if (config.key_set) {
        try { albums = (await api.photoAlbums()).albums; }
        catch (e) { error = e.message; }
      }
    } catch (e) {
      if (stack.at(-1)?.view === "photo-library" && epoch === photoSettingsEpoch) {
        page("Photo library", `<div class="card"><p class="note warn">${esc(e.message)}</p>
          <button class="btn" data-go="photo-library">Try again</button></div>`);
      }
      return;
    }
    if (stack.at(-1)?.view !== "photo-library" || epoch !== photoSettingsEpoch) return;
    page("Photo library", `<form class="card" data-photo-connect>
      <h3>${esc(config.name)}</h3>
      <p>Use a read-only API key, not your account password. Required permissions:
        <b>${config.permissions.map(esc).join(", ")}</b>. Supports server versions 2.x and 3.x.</p>
      <label class="field"><span>Server URL</span><input name="url" type="url" required
        placeholder="http://laptop.local:2283" value="${esc(config.url)}" autocomplete="off"></label>
      <label class="field"><span>Read-only API key</span><input name="key" type="password" autocomplete="new-password"
        ${config.key_set ? 'placeholder="Saved; leave blank to keep"' : "required"}></label>
      <p class="group-label">${config.key_set ? "A key is saved on the panel." : "Not connected."}
        Use a trusted private network or HTTPS. The key is never sent to photo tiles.</p>
      <p class="note warn" data-photo-error hidden role="alert"></p>
      <div class="btn-row"><button type="submit" class="btn primary">Connect and verify</button>
        ${config.key_set ? '<button type="button" class="btn danger" data-photo-disconnect>Disconnect</button>' : ""}</div>
    </form>
    ${config.key_set ? `<form class="card" data-photo-source><h3>Display source</h3>
      <p>Only selected albums will be used. Photos will be visible to the permitted panel profiles below.</p>
      ${error ? `<p class="note warn" role="alert">${esc(error)}</p>` : ""}
      <fieldset><legend>Albums</legend>${albums.length ? albums.map(album => `<label class="check">
        <input type="checkbox" name="album" value="${esc(album.id)}" ${config.albums.includes(album.id) ? "checked" : ""}>
        <span>${esc(album.name)}</span></label>`).join("") : "<p>No albums available. Create an album on the server, then verify the connection again.</p>"}</fieldset>
      <fieldset><legend>Permitted profiles</legend>${store.profiles.map(profile => `<label class="check">
        <input type="checkbox" name="profile" value="${esc(profile.id)}" ${config.profiles.includes(profile.id) ? "checked" : ""}>
        <span>${esc(profile.name)}</span></label>`).join("")}</fieldset>
      <label class="field"><span>Seconds between photos</span><input type="number" name="seconds" min="30" max="300" step="1" value="${config.seconds}" required></label>
      <p class="note warn" data-photo-error hidden role="alert"></p>
      <button class="btn primary" type="submit" ${!albums.length ? "disabled" : ""}>Save photo source</button>
      <p class="group-label">Then open Home, choose Edit, Add, Photos. Existing uploaded photo-frame pictures are unchanged.</p>
    </form>` : ""}`);
    const bind = (selector, action) => {
      const form = $(selector);
      if (!form) return;
      form.addEventListener("submit", async e => {
        e.preventDefault(); e.stopPropagation();
        const values = new FormData(form), controls = [...form.querySelectorAll("button,input")];
        controls.forEach(control => { control.disabled = true; });
        const error = form.querySelector("[data-photo-error]"); error.hidden = true;
        try {
          await action(values); await reload();
          if (stack.at(-1)?.view === "photo-library" && epoch === photoSettingsEpoch) VIEWS["photo-library"]();
        } catch (e) {
          error.textContent = e.message; error.hidden = false;
          controls.forEach(control => { control.disabled = false; });
        }
      });
    };
    bind("[data-photo-connect]", values => api.connectPhotoLibrary({ url: String(values.get("url")).trim(), key: values.get("key") }));
    bind("[data-photo-source]", values => api.selectPhotoAlbums({
      albums: values.getAll("album"), profiles: values.getAll("profile"), seconds: Number(values.get("seconds")),
    }));
    $("[data-photo-disconnect]")?.addEventListener("click", async e => {
      e.stopPropagation();
      e.currentTarget.disabled = true;
      try {
        await api.disconnectPhotoLibrary(); await reload();
        if (stack.at(-1)?.view === "photo-library") VIEWS["photo-library"]();
      } catch (error) { toast(error.message, true); e.target.disabled = false; }
    });
  },

  async photos() {
    const s = store.settings;
    page("Photo frame", `
      <div class="card">
        <h3>Photos</h3>
        <p id="photo-count">Loading…</p>
        <div class="thumbs" id="thumbs"></div>
        <div class="btn-row" style="margin-top:0">
          <label class="btn primary upload-btn">${icon("upload")}<span>Add photos</span>
            <input type="file" id="photo-input" accept="image/*" multiple></label>
          <button class="btn" data-start-frame>${icon("image")}Start slideshow</button>
        </div>
        <small class="field"><small>Easiest from your phone: open this panel's address in its browser and add photos here.
          Photos are rotated upright, resized for the screen, and stored on the panel without location data.</small></small>
      </div>
      <form class="card" data-frame-settings>
        <h3>Slideshow</h3>
        <label class="field"><span>Each photo shows for</span><select name="frame_seconds">
          ${[[8, "8 seconds"], [15, "15 seconds"], [30, "30 seconds"], [60, "1 minute"], [300, "5 minutes"]].map(([v, l]) =>
            `<option value="${v}" ${Number(s.frame_seconds || 15) === v ? "selected" : ""}>${l}</option>`).join("")}
        </select></label>
        <label class="check"><input type="checkbox" name="frame_shuffle" ${s.frame_shuffle !== false ? "checked" : ""}><span>Shuffle</span></label>
        <label class="check"><input type="checkbox" name="frame_clock" ${s.frame_clock !== false ? "checked" : ""}><span>Show the time over photos</span></label>
        <label class="field" style="margin-top:12px"><span>When the panel is idle, show</span><select name="idle_screen">
          <option value="clock" ${s.idle_screen !== "photos" ? "selected" : ""}>The resting clock</option>
          <option value="photos" ${s.idle_screen === "photos" ? "selected" : ""}>The photo frame</option>
        </select><small>How long until idle is set in Display and clock.</small></label>
        <label class="check"><input type="checkbox" name="frame_night_clock" ${s.frame_night_clock !== false ? "checked" : ""}>
          <span>From 10 PM to 7 AM, show the dim clock instead of photos</span></label>
        <div class="btn-row"><button class="btn primary" type="submit">Save</button></div>
      </form>`);
    await loadThumbs();
  },

  display() {
    const s = store.settings;
    const now = new Date();
    const info = faceInfo();
    const opts = [[0, "Never"], [30, "30 seconds"], [60, "1 minute"], [90, "90 seconds"], [180, "3 minutes"], [600, "10 minutes"]];
    page("Display and clock", `
      <form class="card" data-display>
        <h3>Text</h3>
        <label class="field"><span>Font size <b id="font-size-value">${FONT_SIZE_NAMES[s.font_size || "medium"]}</b></span>
          <input class="glass-range font-size-range" type="range" name="font_size" min="0" max="2" step="1"
            value="${Math.max(0, FONT_SIZES.indexOf(s.font_size || "medium"))}" aria-valuetext="${FONT_SIZE_NAMES[s.font_size || "medium"]}"
            aria-describedby="font-size-help">
        </label>
        <div class="font-size-labels" aria-hidden="true"><span>Small</span><span>Medium</span><span>Large</span></div>
        <p id="font-size-help">Manrope is stored on the panel and works offline. Preview the size here, then Save to apply it to all profiles and screens.</p>
        <label class="field"><span>Show the resting clock after</span><select name="dim_after_seconds">
          ${opts.map(([v, l]) => `<option value="${v}" ${Number(s.dim_after_seconds) === v ? "selected" : ""}>${l}</option>`).join("")}
        </select><small>The screen goes dark with a dim clock so it doesn't light up the room. Touch to wake.</small></label>
        <span class="field"><span>Clock face</span></span>
        <div class="face-choices" role="radiogroup" aria-label="Clock face">
          ${FACES.map((f) => `
            <label class="face-choice"><input type="radio" name="clock_face" value="${f.id}" ${faceId(s.clock_face) === f.id ? "checked" : ""}>
              <span class="face-preview">${faceHTML(f.id, now, info)}</span><span>${esc(f.name)}</span></label>`).join("")}
        </div>
        <label class="check"><input type="checkbox" name="clock_24h" ${s.clock_24h ? "checked" : ""}><span>24-hour clock</span></label>
        <span class="field"><span>Background</span></span>
        <div class="bg-choices" role="radiogroup" aria-label="Background">
          ${[["sky", "Sky"], ["ocean", "Ocean"], ["aurora", "Aurora"], ["night", "Night"], ["wallpaper", "Wallpaper"]].map(([v, l]) => `
            <label class="bg-choice"><input type="radio" name="background" value="${v}" ${(s.background || "sky") === v ? "checked" : ""}>
              <span class="bg-swatch swatch-${v}">${v === "wallpaper" ? icon("image") : ""}</span><span>${l}</span></label>`).join("")}
        </div>
        <div class="wall-panel" id="wall-panel" ${(s.background || "sky") === "wallpaper" ? "" : "hidden"}>
          <span class="field"><span>Wallpaper</span></span>
          <div class="wall-grid" id="wall-grid" role="radiogroup" aria-label="Wallpaper"><p class="sub">Loading…</p></div>
          <div class="btn-row" style="margin-top:8px">
            <label class="btn">${icon("plus")}Add wallpapers<input type="file" id="wall-input" accept="image/*,.tif,.tiff" multiple hidden></label>
          </div>
          <small class="field"><small>Pictures from your phone or computer (JPEG, PNG, WebP or TIFF). They're resized for the
            screen and their location data is removed. Portrait pictures are used on phones, landscape on the panel.</small></small>
          <label class="field"><span>When shuffling, change every</span><select name="wallpaper_every">
            ${[[15, "15 minutes"], [60, "hour"], [240, "4 hours"], [1440, "day"], [0, "time the screen opens"]].map(([v, l]) =>
              `<option value="${v}" ${Number(s.wallpaper_every ?? 60) === v ? "selected" : ""}>${l}</option>`).join("")}
          </select></label>
          <label class="field"><span>Darken <b id="wall-dim-val">${s.wallpaper_dim ?? 25}%</b></span>
            <input class="glass-range" type="range" name="wallpaper_dim" min="0" max="80" step="5" value="${s.wallpaper_dim ?? 25}">
            <small>A little darker keeps the clock and tiles easy to read.</small></label>
        </div>
        <span class="field"><span>Tiles</span></span>
        <div class="seg" role="radiogroup" aria-label="Tiles">
          ${[["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) => `
            <label class="seg-choice"><input type="radio" name="tile_style" value="${v}" ${(s.tile_style || "auto") === v ? "checked" : ""}>
              <span>${l}</span></label>`).join("")}
        </div>
        <small class="field"><small>Auto picks light tiles on a dark background and dark tiles on a light one, so they always stand out.</small></small>
        <label class="field"><span>Glass transparency <b id="glass-val">${s.glass_transparency ?? 45}%</b></span>
          <input class="glass-range" type="range" name="glass_transparency" min="0" max="100" step="5" value="${s.glass_transparency ?? 45}">
          <small>Lower is more solid; higher shows more of the background. Tiles keep a minimum backing so their labels stay readable.</small></label>
        <label class="check"><input type="checkbox" name="glass_effect" ${s.glass_effect !== false ? "checked" : ""}>
          <span>Frosted blur (turn off if the screen feels slow)</span></label>
        <div class="btn-row"><button class="btn primary" type="submit">Save</button></div>
      </form>`);
    loadWallGrid();
  },

  async diagnostics() {
    page("Diagnostics and logs", `<div class="card" id="health"><p>Checking…</p></div>
      <div class="btn-row" style="margin:0 0 12px">
        <button class="btn small" data-logs="">All logs</button>
        <button class="btn small" data-logs="WARNING">Problems only</button>
        <a class="btn small" href="/api/v1/logs?format=text" download="homepanel-log.txt">Download log file</a>
      </div>
      <div class="logs" id="logs">Loading…</div>`);
    try {
      const h = await api.health();
      $("#health").innerHTML = `<h3>${h.online} of ${h.devices} devices responding</h3>
        <p>Running for ${fmtDuration(h.uptime_s)}. Brands available: ${esc(h.adapters.join(", "))}.
        ${Object.keys(h.unavailable).length ? `<br>Not installed: ${esc(Object.keys(h.unavailable).join(", "))}.` : ""}
        ${Object.keys(h.unsupported || {}).length ? `<br>Not available on this Python: ${esc(Object.keys(h.unsupported).join(", "))}.` : ""}</p>
        <h3 class="phone-title">Use it on your phone</h3>
        <p id="phone-url">${phoneHint(h)}</p>`;
    } catch (e) { $("#health").innerHTML = `<p>${esc(e.message)}</p>`; }
    loadLogs("");
  },
};

// Where to open the panel from a phone or tablet on the same Wi-Fi.
function phoneHint(h) {
  if (h.phone_url) return `On a phone or tablet on the same Wi-Fi, open <b>${esc(h.phone_url)}</b> in the browser.`;
  const port = location.port || "80";
  return `On a phone or tablet on the same Wi-Fi, open <b>http://</b><i>this computer's address</i><b>:${esc(port)}</b>.
    On a Mac, find the address in System Settings → Wi-Fi → Details.`;
}

function profilesSummary() {
  const n = store.profiles.length;
  return `${n} ${n === 1 ? "profile" : "profiles"}`;
}

// More views from other files (js/profiles.js): {name(arg) {...}}
export function registerViews(views) { Object.assign(VIEWS, views); }
export const rerender = () => render();
export const currentView = () => stack.at(-1);

async function loadThumbs() {
  const el = $("#thumbs");
  if (!el) return;
  try {
    const { photos } = await api.photos();
    $("#photo-count").textContent = photos.length ? `${photos.length} ${photos.length === 1 ? "photo" : "photos"} on this panel.`
      : "No photos yet. Add some to start the slideshow.";
    el.innerHTML = photos.map((p) => `<div class="thumb" style="background-image:url('${esc(p.url)}')">
      <button data-del-photo="${esc(p.id)}" aria-label="Remove this photo">${icon("trash")}</button></div>`).join("");
  } catch (e) { $("#photo-count").textContent = e.message; }
}

async function uploadFiles(files) {
  const list = [...files];
  let done = 0, failed = 0;
  for (const f of list) {
    $("#photo-count").textContent = `Adding ${done + failed + 1} of ${list.length}…`;
    try { await api.uploadPhoto(f); done += 1; }
    catch (e) { failed += 1; toast(`${f.name}: ${e.message}`, true); }
  }
  if (done) toast(`Added ${done} ${done === 1 ? "photo" : "photos"}`);
  await loadThumbs();
}

function fmtDuration(s) {
  if (s < 90) return `${Math.round(s)} seconds`;
  if (s < 5400) return `${Math.round(s / 60)} minutes`;
  if (s < 172800) return `${Math.round(s / 3600)} hours`;
  return `${Math.round(s / 86400)} days`;
}

async function loadLogs(level) {
  const el = $("#logs");
  if (!el) return;
  try {
    const { logs } = await api.logs(level);
    el.innerHTML = logs.length ? logs.slice().reverse().map((l) =>
      `<div class="${esc(l.level)}"><span class="t">${new Date(l.time * 1000).toLocaleTimeString()}</span> ${esc(l.level)} ${esc(l.message)}</div>`).join("")
      : "Nothing logged yet.";
  } catch (e) { el.textContent = e.message; }
}

function fieldHtml(f, value) {
  const v = value ?? f.default ?? "";
  if (f.type === "select") {
    return `<label class="field"><span>${esc(f.label)}</span><select name="${esc(f.key)}">${f.options.map((o) =>
      `<option value="${esc(o.value)}" ${String(o.value) === String(v) ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select>
      ${f.help ? `<small>${esc(f.help)}</small>` : ""}</label>`;
  }
  const type = f.type === "password" ? "password" : f.type === "number" ? "number" : "text";
  const isMasked = f.type === "password" && v === "••••••";
  return `<label class="field"><span>${esc(f.label)}</span>
    <input name="${esc(f.key)}" type="${type}" value="${isMasked ? "" : esc(v)}" ${f.required && !isMasked ? "required" : ""}
      placeholder="${esc(isMasked ? "Saved. Leave blank to keep it." : f.placeholder || "")}" autocomplete="off" spellcheck="false">
    ${f.help ? `<small>${esc(f.help)}</small>` : ""}</label>`;
}

async function loadWallGrid() {
  const grid = $("#wall-grid");
  if (!grid) return;
  let walls = [];
  try { walls = (await api.wallpapers()).wallpapers || []; } catch (e) { grid.innerHTML = `<p class="sub">${esc(e.message)}</p>`; return; }
  const current = $("[data-display]")?.dataset.wall ?? store.settings.wallpaper ?? "shuffle";
  grid.innerHTML = `
    <label class="wall-choice shuffle"><input type="radio" name="wallpaper" value="shuffle" ${current === "shuffle" ? "checked" : ""}>
      <span class="wall-thumb">${icon("shuffle")}</span><span>Shuffle</span></label>
    ${walls.map((w) => `
      <div class="wall-item">
        <label class="wall-choice"><input type="radio" name="wallpaper" value="${esc(w.id)}" ${current === w.id ? "checked" : ""}>
          <span class="wall-thumb" style="background-image:url('${esc(w.url)}')"></span>
          <span>${w.width && w.height ? (w.height > w.width ? "Portrait" : "Landscape") : ""}</span></label>
        <button type="button" class="wall-del" data-del-wall="${esc(w.id)}" aria-label="Remove this wallpaper">${icon("trash")}</button>
      </div>`).join("")}
    ${walls.length ? "" : `<p class="sub">No wallpapers yet. Add some below.</p>`}`;
}

function displayPreview() {
  const form = $("[data-display]");
  if (!form) return;
  const v = formValues(form);
  previewWallpaper({ background: v.background, wallpaper: v.wallpaper || store.settings.wallpaper,
                     wallpaper_dim: Number(v.wallpaper_dim ?? 25) });
  previewTiles({ background: v.background, wallpaper_dim: Number(v.wallpaper_dim ?? 25), tile_style: v.tile_style || "auto" });
}

async function uploadWallpapers(files) {
  const list = [...files];
  let done = 0;
  for (const f of list) {
    toast(`Adding wallpaper ${done + 1} of ${list.length}…`);
    try { await api.uploadWallpaper(f); done++; } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  invalidateWallpapers();
  if (done) toast(done === 1 ? "Wallpaper added" : `${done} wallpapers added`);
  await loadWallGrid();
  displayPreview();
}

const formValues = (form) => Object.fromEntries(new FormData(form).entries());

function render() {
  const top = stack.at(-1);
  if (!top) return close();
  VIEWS[top.view]?.(top.arg);
}

// ---------- events ----------
const root = $("#settings");

const PIN = `<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/></svg>`;

// Fill the location form from "Use my location". The user checks it and taps Save.
async function useMyLocation(btn) {
  const form = btn.closest("form");
  const status = $("#locate-status");
  const label = btn.querySelector("span");
  btn.disabled = true;
  label.textContent = "Finding your location…";
  status.hidden = true;
  status.classList.remove("error");
  try {
    const r = await findLocation();
    form.elements.latitude.value = r.latitude;
    form.elements.longitude.value = r.longitude;
    if (r.place_name) form.elements.place_name.value = r.place_name;
    status.textContent = `${describeFound(r)} Check it and tap Save location.`;
  } catch (err) {
    status.textContent = err.message;
    status.classList.add("error");
  }
  status.hidden = false;
  btn.disabled = false;
  label.textContent = "Use my location";
}

root.addEventListener("click", async (e) => {
  const t = (sel) => e.target.closest(sel);
  if (t("[data-room-add-cancel]")) {
    const form = t("[data-room-add]"); form.reset(); syncRoomSorters(); form.querySelector("input").focus(); return;
  }
  if (t("[data-room-add]")) return;
  if (t("[data-edit-rooms]")) {
    if (await toggleRoomEditing("#settings")) $("#settings [data-edit-rooms]")?.focus();
    return;
  }
  if (t("[data-cancel-room-names], [data-room-name], [data-room-grip]")) return;
  if (!canLeaveRoomNames()) return;
  const roomLayout = t("[data-room-layout]");
  if (roomLayout) return document.dispatchEvent(new CustomEvent("hp:edit-room", { detail: roomLayout.dataset.roomLayout }));
  if (t("[data-back]")) return back();
  if (t("[data-close]")) return close();
  const goEl = t("[data-go]");
  if (goEl) return go(goEl.dataset.go, goEl.dataset.arg || null);
  const locateBtn = t("[data-locate]");
  if (locateBtn) return useMyLocation(locateBtn);

  const top = stack.at(-1);
  try {
    if (t("[data-save-device]")) {
      const id = t("[data-save-device]").dataset.saveDevice;
      const changes = { name: $("#d-name").value.trim() || "Device", room: $("#d-room").value,
                        keep_on: !!$("#d-keep")?.checked, icon: $("input[name=d-icon]:checked")?.value || "" };
      if ($("#d-mac")) changes.mac = $("#d-mac").value.trim();
      await api.updateDevice(id, changes);
      toast("Saved");
      await reload();
      return back();
    }
    if (t("[data-pair]")) {
      const b = t("[data-pair]"); b.disabled = true; b.textContent = "Accept the prompt on the TV…";
      await api.pair(b.dataset.pair); toast("Paired"); await reload(); return render();
    }
    if (t("[data-refresh]")) { await api.refresh(t("[data-refresh]").dataset.refresh); await reload(); toast("Checked"); return render(); }
    if (t("[data-remove]")) {
      const id = t("[data-remove]").dataset.remove;
      const d = store.devices.get(id);
      if (!confirm(`Remove ${d?.name || "this device"} from the panel? It stays set up in its own app.`)) return;
      await api.removeDevice(id); await reload(); toast("Removed"); return back();
    }
    if (t("[data-discover-all]")) {
      searchAll.searching = true; searchAll.room = $("#add-room")?.value; render();
      try { searchAll.result = await api.discoverAll(); }
      finally { searchAll.searching = false; if (stack.at(-1)?.view === "add") render(); }
      return;
    }
    if (t("[data-add-found]")) {
      const b = t("[data-add-found]");
      b.disabled = true; b.textContent = "Adding…";
      const room = $("#add-room")?.value || "";
      searchAll.room = room;
      const d = await api.addDevice({ adapter: b.dataset.adapter, uid: b.dataset.addFound, name: b.dataset.name, room });
      const f = searchAll.result?.found.find((x) => x.adapter === b.dataset.adapter && x.uid === b.dataset.addFound);
      if (f) f.added = true;
      toast(d.pairing ? `${d.name} added. Look at the TV and accept the prompt, then tap Pair.` : `${d.name} added`, d.pairing);
      await reload();
      return render();
    }
    if (t("[data-discover]")) {
      brandState.searching = true; brandState.room = $("#add-room")?.value; render();
      try { brandState.found = (await api.discover(top.arg)).found; }
      finally { brandState.searching = false; render(); }
      return;
    }
    if (t("[data-manual-toggle]")) { brandState.manual = !brandState.manual; brandState.room = $("#add-room")?.value; return render(); }
    if (t("[data-add-uid]")) {
      const b = t("[data-add-uid]");
      b.disabled = true; b.textContent = "Adding…";
      const room = $("#add-room")?.value || "";
      brandState.room = room;
      const d = await api.addDevice({ adapter: top.arg, uid: b.dataset.addUid, name: b.dataset.name, room });
      const f = brandState.found?.find((x) => x.uid === b.dataset.addUid);
      if (f) f.added = true;
      toast(d.pairing ? `${d.name} added. Look at the TV and accept the prompt, then tap Pair.` : `${d.name} added`, d.pairing);
      await reload();
      return render();
    }
    if (t("[data-account-action]")) {
      const b = t("[data-account-action]"); b.disabled = true;
      const form = b.closest("form");      // save what was typed first, so the action can use it
      if (form) brandState.account = await api.saveAccount(top.arg, formValues(form));
      const r = await api.accountAction(top.arg, b.dataset.accountAction);
      brandState.account = r.account; toast(r.message); await reload(); return render();
    }
    if (t("[data-auto-run]")) { const r = await api.runAutomation(t("[data-auto-run]").dataset.autoRun); toast(`${r.name}: ${r.last_result}`); await reload(); return render(); }
    if (t("[data-auto-del]")) { await api.deleteAutomation(t("[data-auto-del]").dataset.autoDel); await reload(); return render(); }
    if (t("[data-auto-toggle]")) {
      const a = store.automations.find((x) => x.id === t("[data-auto-toggle]").dataset.autoToggle);
      await api.saveAutomation({ ...a, enabled: t("[data-auto-toggle]").checked }); await reload(); return render();
    }
    if (t("[data-person-del]")) {
      const people = store.settings.presence.filter((_, i) => i !== +t("[data-person-del]").dataset.personDel);
      await api.saveSettings({ presence: people }); await reload(); return render();
    }
    if (t("[data-start-frame]")) { close(); return openFrame(); }
    if (t("[data-clear-pic]")) {
      await api.clearDevicePicture(t("[data-clear-pic]").dataset.clearPic);
      await reload(); toast("Photo removed"); return render();
    }
    if (t("[data-del-wall]")) {
      if (!confirm("Remove this wallpaper from the panel?")) return;
      await api.deleteWallpaper(t("[data-del-wall]").dataset.delWall);
      invalidateWallpapers();
      await loadWallGrid();
      return displayPreview();
    }
    if (t("[data-del-photo]")) {
      if (!confirm("Remove this photo from the panel?")) return;
      await api.deletePhoto(t("[data-del-photo]").dataset.delPhoto); return loadThumbs();
    }
    if (t("[data-del-scene]")) { await api.deleteScene(t("[data-del-scene]").dataset.delScene); await reload(); return render(); }
    if (t("[data-room-del]")) {
      const rooms = store.rooms.filter((_, i) => i !== +t("[data-room-del]").dataset.roomDel);
      await saveRooms(rooms); return render();
    }
    if (t("[data-logs]") !== null && t("[data-logs]")) return loadLogs(t("[data-logs]").dataset.logs);
  } catch (err) {
    toast(err.message, true);
    render();
  }
});

root.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const top = stack.at(-1);
  try {
    if (form.matches("[data-account]")) {
      brandState.account = await api.saveAccount(top.arg, formValues(form));
      toast("Saved"); await reload(); return render();
    }
    if (form.matches("[data-manual]")) {
      const values = formValues(form);
      const d = await api.addDevice({ adapter: top.arg, manual: values, name: values.name, room: $("#add-room")?.value || "" });
      toast(d.pairing ? `${d.name} added. Accept the prompt on the TV, then tap Pair.` : `${d.name} added`, d.pairing);
      await reload(); brandState.manual = false; return render();
    }
    if (form.matches("[data-scene-form]")) {
      const fd = new FormData(form);
      const capture = fd.getAll("capture");
      if (!capture.length) return toast("Pick at least one device", true);
      await api.saveScene({ name: fd.get("name"), icon: fd.get("icon"), capture });
      toast("Scene saved"); await reload(); return back();
    }
    if (form.matches("[data-auto-form]")) {
      const fd = new FormData(form);
      const when = buildWhen({ when: fd.get("when"), at: fd.get("at"), days: fd.getAll("days"),
                               offset_min: fd.get("offset_min"), watch_id: fd.get("watch_id") });
      const d = fd.get("do");
      const doIt = d.startsWith("scene:") ? { type: "scene", scene_id: d.slice(6) }
        : d === "all_off" ? { type: "all_off" }
        : { type: "command", device_id: fd.get("device_id"), action: "power", value: fd.get("value") === "on" };
      if (when.type === "time" && !when.days.length) return toast("Pick at least one day", true);
      await api.saveAutomation({ name: fd.get("name"), when, do: doIt, enabled: true });
      toast("Automation saved"); await reload(); return back();
    }
    if (form.matches("[data-location]")) {
      const v = formValues(form);
      await api.saveSettings({ latitude: v.latitude.trim() || null, longitude: v.longitude.trim() || null,
                               place_name: v.place_name.trim(), weather_enabled: !!v.weather_enabled,
                               temperature_unit: v.temperature_unit });
      toast("Location saved"); await reload(); return render();
    }
    if (form.matches("[data-person-add]")) {
      const v = formValues(form);
      await api.saveSettings({ presence: [...(store.settings.presence || []), { name: v.name.trim(), ip: v.ip.trim() }] });
      toast(`Watching ${v.name.trim()}'s phone`); await reload(); return render();
    }
    if (form.matches("[data-room-add]")) {
      if (!canLeaveRoomNames(true)) return;
      const room = await addRoom(formValues(form).room);
      toast(`${room} added`); return render();
    }
    if (form.matches("[data-frame-settings]")) {
      const fd = new FormData(form);
      await api.saveSettings({ frame_seconds: Number(fd.get("frame_seconds")), frame_shuffle: fd.has("frame_shuffle"),
                               frame_clock: fd.has("frame_clock"), idle_screen: fd.get("idle_screen"),
                               frame_night_clock: fd.has("frame_night_clock") });
      toast("Saved"); await reload(); return back();
    }
    if (form.matches("[data-display]")) {
      const v = formValues(form);
      await api.saveSettings({ dim_after_seconds: Number(v.dim_after_seconds), clock_24h: !!v.clock_24h,
                               font_size: FONT_SIZES[Number(v.font_size)],
                               glass_effect: !!v.glass_effect, background: v.background, clock_face: v.clock_face,
                               glass_transparency: Number(v.glass_transparency),
                               ...(v.wallpaper ? { wallpaper: v.wallpaper } : {}),
                               wallpaper_every: Number(v.wallpaper_every ?? 60), wallpaper_dim: Number(v.wallpaper_dim ?? 25),
                               tile_style: v.tile_style || "auto" });
      previewWallpaper(null);
      previewTiles(null);
      toast("Saved"); await reload(); return back();
    }
  } catch (err) { toast(err.message, true); }
});

// Live preview of background and glass changes before saving
root.addEventListener("input", (e) => {
  const el = e.target;
  if (!el.closest("[data-display]")) return;
  if (el.name === "font_size") {
    const size = FONT_SIZES[Number(el.value)];
    previewTypography(size);
    el.setAttribute("aria-valuetext", FONT_SIZE_NAMES[size]);
    $("#font-size-value").textContent = FONT_SIZE_NAMES[size];
  }
  if (el.name === "glass_transparency") {
    applyTransparency(el.value);
    const label = $("#glass-val");
    if (label) label.textContent = `${el.value}%`;
  }
  if (el.name === "background") {
    document.documentElement.dataset.bg = el.value;
    const panel = $("#wall-panel");
    if (panel) panel.hidden = el.value !== "wallpaper";
  }
  if (el.name === "wallpaper_dim") {
    const label = $("#wall-dim-val");
    if (label) label.textContent = `${el.value}%`;
  }
  if (["background", "wallpaper", "wallpaper_dim", "tile_style"].includes(el.name)) displayPreview();
  if (el.name === "glass_effect") document.documentElement.classList.toggle("glass", el.checked);
});

root.addEventListener("change", (e) => {
  if (e.target.id === "photo-input" && e.target.files.length) uploadFiles(e.target.files);
  if (e.target.id === "wall-input" && e.target.files.length) { uploadWallpapers(e.target.files); e.target.value = ""; }
  if (e.target.id === "d-pic-input" && e.target.files.length) {
    const input = e.target;
    toast("Adding the photo…");
    api.setDevicePicture(input.dataset.device, input.files[0])
      .then(async () => { await reload(); toast("Photo added"); render(); })
      .catch((err) => toast(err.message, true));
  }
});

document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isSettingsOpen()) back(); });
