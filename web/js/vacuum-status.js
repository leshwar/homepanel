// Shared, read-only vacuum presentation. Battery and previous jobs never imply progress.
const ACTIVITY = {
  cleaning: ["Cleaning...", "vacuum"], paused: ["Paused", "pause"], returning: ["Returning to dock", "home"],
  docked: ["Docked", "home"], idle: ["Ready", "vacuum"], error: ["Needs attention", "info"],
};
const ACTIVE = ["cleaning", "paused", "returning"];
const finite = value => typeof value === "number" && Number.isFinite(value) && value >= 0;

export function vacuumStatus(s = {}) {
  if (s.online === false) return { phase: "offline", label: "Offline", glyph: "info", metrics: "" };
  if (s.needs_pairing) return { phase: "unknown", label: "Needs pairing", glyph: "info", metrics: "" };
  const job = s.cleaning;
  const active = ACTIVE.includes(s.activity);
  const metrics = active && job?.run_id && job.status === s.activity && !job.stats_stale
    ? [finite(job.elapsed_seconds) ? `${Math.floor(job.elapsed_seconds / 60)} min reported` : "",
       finite(job.area_m2) ? `${job.area_m2} m² cleaned` : ""].filter(Boolean).join(" · ") : "";
  if (s.problem || s.activity === "error" || job?.status === "attention") {
    return { phase: "attention", label: "Needs attention", glyph: "info", metrics };
  }
  if ((job?.status === "completed" && job.run_id) || job?.status === "stopped") {
    return { phase: job.status, label: job.status === "completed" ? "Clean complete" : "Cleaning stopped",
             glyph: job.status === "completed" ? "check" : "stop", metrics: "" };
  }
  const [label, glyph] = ACTIVITY[s.activity] || ["Status not reported", "vacuum"];
  return { phase: ACTIVITY[s.activity] ? s.activity : "unknown",
           label: s.activity === "docked" && finite(s.battery) && s.battery < 100 ? "Charging" : label,
           glyph, metrics, active, stale: !!job?.stats_stale };
}

export function idleVacuumLine(devices) {
  const priority = { attention: 0, cleaning: 1, paused: 2, returning: 3, offline: 4 };
  const relevant = [...devices].filter(d => d.kind === "vacuum" || d.caps?.includes("clean"))
    .map(d => ({ d, status: vacuumStatus(d.state) }))
    .filter(({ status }) => Object.hasOwn(priority, status.phase))
    .sort((a, b) => priority[a.status.phase] - priority[b.status.phase] || String(a.d.id).localeCompare(String(b.d.id)));
  if (!relevant.length) return "";
  const { d, status } = relevant[0];
  return `${d.name} · ${status.label}${relevant.length > 1 ? ` · +${relevant.length - 1} more` : ""}`;
}
