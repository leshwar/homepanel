// Thin client for the HomePanel REST API (see docs/API.md).
// Every UI action goes through here, so swapping the backend never touches the UI.
//
// Sign-in: the server keeps the session in an HttpOnly cookie, so this file never
// sees a token. When the server says "sign in first" (401 with signin: true), the
// error is thrown as usual and a "hp:signin" event goes to window (js/auth.js shows
// the profile picker).

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(message, status = 0, data = null) { super(message); this.status = status; this.data = data; }
}

function signinNeeded(data) {
  if (data && data.signin) window.dispatchEvent(new CustomEvent("hp:signin", { detail: data }));
}

async function call(method, path, body) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the panel's server. Is it running?");
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/auth/")) signinNeeded(data);
    throw new ApiError((data && data.error) || `Request failed (${res.status})`, res.status, data);
  }
  return data;
}

export const api = {
  // sign-in and profiles
  session: () => call("GET", "/auth/session"),
  signIn: (body) => call("POST", "/auth/sign-in", body),       // {profile_id, pin} | {profile_id, password} | {email, password}
  setup: (body) => call("POST", "/auth/setup", body),
  signOut: (forget = false) => call("POST", "/auth/sign-out", { forget }),
  lock: () => call("POST", "/auth/lock"),
  setPanel: (panel) => call("POST", "/auth/panel", { panel }),
  profiles: () => call("GET", "/profiles"),
  addProfile: (p) => call("POST", "/profiles", p),
  updateProfile: (id, p) => call("PATCH", `/profiles/${encodeURIComponent(id)}`, p),
  deleteProfile: (id) => call("DELETE", `/profiles/${encodeURIComponent(id)}`),
  updateMe: (p) => call("PATCH", "/profiles/me", p),
  saveLayout: (layout) => call("PUT", "/profiles/me/layout", { home_layout: layout }),   // null = back to the default

  state: () => call("GET", "/state"),
  health: () => call("GET", "/health"),
  logs: (level = "") => call("GET", `/logs${level ? `?level=${level}` : ""}`),

  command: (id, action, value) => call("POST", `/devices/${id}/command`, { action, value }),
  // Move / click / scroll a TV's on-screen pointer: {dx, dy} | {click: true} | {scroll: dy}.
  pointer: (id, value) => call("POST", `/devices/${id}/command`, { action: "pointer", value }),
  addDevice: (body) => call("POST", "/devices", body),
  updateDevice: (id, changes) => call("PATCH", `/devices/${id}`, changes),
  removeDevice: (id) => call("DELETE", `/devices/${id}`),
  pair: (id) => call("POST", `/devices/${id}/pair`),
  refresh: (id) => call("POST", `/devices/${id}/refresh`),
  allOff: (room = null) => call("POST", "/all-off", room == null ? {} : { room }),   // "" = devices with no room

  mapUrl: (id, rev = 0) => `${BASE}/devices/${encodeURIComponent(id)}/map?v=${encodeURIComponent(rev)}`,
  discoverAll: () => call("POST", "/discover"),
  discover: (adapter) => call("POST", `/adapters/${adapter}/discover`),
  getAccount: (adapter) => call("GET", `/adapters/${adapter}/account`),
  saveAccount: (adapter, values) => call("PUT", `/adapters/${adapter}/account`, values),
  accountAction: (adapter, action) => call("POST", `/adapters/${adapter}/actions/${action}`),

  setRooms: (rooms) => call("PUT", "/rooms", { rooms }),
  saveScene: (scene) => call("POST", "/scenes", scene),
  deleteScene: (id) => call("DELETE", `/scenes/${id}`),
  runScene: (id) => call("POST", `/scenes/${id}/run`),
  saveSettings: (s) => call("PUT", "/settings", s),

  energy: (id, days = 7) => call("GET", `/devices/${id}/energy?days=${days}`),
  saveAutomation: (a) => call("POST", "/automations", a),
  deleteAutomation: (id) => call("DELETE", `/automations/${id}`),
  runAutomation: (id) => call("POST", `/automations/${id}/run`),
  presence: () => call("GET", "/presence"),
  sun: () => call("GET", "/sun"),
  weather: () => call("GET", "/weather"),

  photos: () => call("GET", "/photos"),
  deletePhoto: (id) => call("DELETE", `/photos/${encodeURIComponent(id)}`),
  // One photo per request; the body is the file itself (no multipart needed).
  uploadPhoto: async (file) => {
    let res;
    try {
      res = await fetch(`${BASE}/photos?name=${encodeURIComponent(file.name || "photo")}`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
    } catch {
      throw new ApiError("Can't reach the panel's server. Is it running?");
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError((data && data.error) || `Upload failed (${res.status})`);
    return data;
  },
};

// Live updates. Calls onEvent(event) for each server event, onStatus(connected).
// Returns {stop, restart}: stop while signed out, restart after switching profile
// (the stream belongs to the session that opened it).
export function connectEvents(onEvent, onStatus) {
  let es;
  let retry;
  let stopped = false;
  const open = () => {
    if (stopped) return;
    es = new EventSource(`${BASE}/events`);
    es.onopen = () => onStatus(true);
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch { /* ignore */ } };
    es.onerror = () => {
      es.close();
      if (stopped) return;
      onStatus(false);
      clearTimeout(retry);
      retry = setTimeout(open, 2500);
    };
  };
  open();
  return {
    stop() { stopped = true; clearTimeout(retry); es?.close(); },
    restart() { stopped = false; clearTimeout(retry); es?.close(); open(); },
  };
}
