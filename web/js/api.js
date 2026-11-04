// Thin client for the HomePanel REST API (see docs/API.md).
// Every UI action goes through here, so swapping the backend never touches the UI.

const BASE = "/api/v1";

export class ApiError extends Error {}

async function call(method, path, body) {
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the panel's server. Is it running?");
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError((data && data.error) || `Request failed (${res.status})`);
  return data;
}

export const api = {
  state: () => call("GET", "/state"),
  health: () => call("GET", "/health"),
  logs: (level = "") => call("GET", `/logs${level ? `?level=${level}` : ""}`),

  command: (id, action, value) => call("POST", `/devices/${id}/command`, { action, value }),
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
        method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
    } catch {
      throw new ApiError("Can't reach the panel's server. Is it running?");
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new ApiError((data && data.error) || `Upload failed (${res.status})`);
    return data;
  },
};

// Live updates. Calls onEvent(event) for each server event, onStatus(connected).
export function connectEvents(onEvent, onStatus) {
  let es;
  let retry;
  const open = () => {
    es = new EventSource(`${BASE}/events`);
    es.onopen = () => onStatus(true);
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch { /* ignore */ } };
    es.onerror = () => {
      onStatus(false);
      es.close();
      clearTimeout(retry);
      retry = setTimeout(open, 2500);
    };
  };
  open();
}
