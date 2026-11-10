// Automations in words, and the "when" part of the New automation form.
// Pure helpers (no page, no server) so they can be checked on their own.

// values: { when, at, days, offset_min, watch_id } as read from the form.
export function buildWhen(values) {
  const w = values.when;
  if (w === "time") return { type: "time", at: values.at, days: (values.days || []).map(Number) };
  if (w === "sunset" || w === "sunrise") return { type: "sun", event: w, offset_min: Number(values.offset_min) || 0 };
  if (w === "device_on" || w === "device_off") return { type: "device", device_id: values.watch_id, event: w.slice(7) };
  return { type: "presence", event: w };
}

// The line under an automation's name. nameOf(id) gives a device's name (or nothing if it is gone).
export function whenText(a, nameOf = () => "") {
  const w = a.when;
  if (!a.enabled) return "Paused";
  if (w.type === "presence") return w.event === "all_away" ? "When everyone leaves" : "When someone comes home";
  if (w.type === "device") return `When ${nameOf(w.device_id) || "a device"} turns ${w.event === "off" ? "off" : "on"}`;
  const next = a.next_run ? new Date(a.next_run * 1000).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }) : "";
  return next ? `Next: ${next}` : "No upcoming run";
}
