// A filtered snapshot supplies both attention rows and their safe panel links.
import { store } from "./store.js";
import { icon, needsAttention, wornPart } from "./util.js";
import { vacuumStatus } from "./vacuum-status.js";

export function attentionItems(devices) {
  const items = new Map();
  for (const d of devices) {
    const s = d.state || {};
    let text = "", priority = 9;
    if (s.needs_pairing) { text = "Needs pairing"; priority = 1; }
    else if (s.online === false) { text = "Offline · Check connection"; priority = 2; }
    else if (s.problem) { text = s.problem; priority = 0; }
    else if ((d.kind === "vacuum" || d.caps?.includes("clean")) && vacuumStatus(s).phase === "attention") {
      text = "Needs attention · Open controls"; priority = 0;
    } else if (needsAttention(d)) { text = `${wornPart(s)?.name || "Device"} needs attention`; priority = 3; }
    else if (d.caps?.includes("filter_life") && Number.isFinite(s.filter_life) && s.filter_life <= 10) {
      text = `Filter life ${s.filter_life}% · Check filter`; priority = 3;
    }
    if (text) items.set(d.id, {id:d.id,name:d.name,text,priority});
  }
  return [...items.values()].sort((a,b) => a.priority-b.priority || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

export function notificationsWidget() {
  return `<section class="w-fill home-attention" aria-label="Device notifications">
      <header><h2>Notifications</h2><span class="attention-count" role="status"></span></header>
      <div class="attention-list"></div><p class="attention-clear" hidden>${icon("check")}All clear · No devices need attention</p>
    </section>`;
}

export function refreshAttention(root) {
  const panel = root.querySelector(".home-attention");
  if (!panel) return;
  const items = attentionItems(store.devices.values()), list = panel.querySelector(".attention-list");
  const count = panel.querySelector(".attention-count"), text = `${items.length} ${items.length === 1 ? "device" : "devices"}`;
  if (count.textContent !== text) count.textContent = text;
  panel.querySelector(".attention-clear").hidden = items.length > 0;
  for (const row of list.querySelectorAll("[data-attention]")) if (!items.some(i=>i.id === row.dataset.attention)) {
    const focused = row === document.activeElement;
    row.remove();
    if (focused) {
      const heading=panel.querySelector("h2");
      heading.tabIndex=-1;
      heading.focus({preventScroll:true});
    }
  }
  for (const [index, item] of items.entries()) {
    let row = [...list.children].find(r=>r.dataset.attention === item.id);
    if (!row) {
      row = document.createElement("button");
      row.className = "attention-item";
      row.dataset.attention = item.id;
      row.innerHTML = `${icon("info")}<span><b></b><small></small></span>${icon("right")}`;
    }
    row.setAttribute("aria-label", `${item.name}: ${item.text}. Open controls`);
    row.querySelector("b").textContent = item.name;
    row.querySelector("small").textContent = item.text;
    if (list.children[index] !== row) list.insertBefore(row, list.children[index] || null);
  }
}
