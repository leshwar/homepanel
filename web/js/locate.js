// "Use my location": find the home's latitude/longitude and a place name, only when
// the user taps the button. Nothing is saved here; callers fill a form for the user to check.
//
// 1. This device's location, if the browser can ask for it (HTTPS or localhost only).
// 2. Otherwise the server looks up the home's approximate location from its internet address.

import { api } from "./api.js";

const round2 = (v) => Math.round(v * 100) / 100;

// Plain-HTTP pages (e.g. http://panel:8080 over Tailscale) can't ask for device location.
export const canUseDeviceLocation = () => !!(window.isSecureContext && navigator.geolocation);

function deviceCoords() {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: round2(p.coords.latitude), longitude: round2(p.coords.longitude) }),
      () => resolve(null),                     // denied or unavailable: fall back to the internet address
      { timeout: 15000, maximumAge: 10 * 60e3, enableHighAccuracy: false });
  });
}

// → {latitude, longitude, place_name, source: "device" | "approximate"}; throws ApiError with a plain message.
export async function findLocation() {
  const coords = canUseDeviceLocation() ? await deviceCoords() : null;
  return api.lookupLocation(coords || {});
}

// One line saying what happened, e.g. "Found Seattle, WA (approximate, from your internet address)."
export function describeFound(r) {
  const where = r.place_name || `${r.latitude}, ${r.longitude}`;
  const how = r.source === "device" ? "from this device" : "approximate, from your internet address";
  return `Found ${where} (${how}).`;
}
