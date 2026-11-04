// Voice commands: tap or hold the mic, say "turn off the kitchen", and the panel does it.
//
// Speech → text happens in the browser (Web Speech API: Safari on iPhone/iPad, Chrome).
// The text goes to the server (POST /api/v1/voice via api.js), which works out the commands
// and runs them like a tap. Where the browser can't listen (e.g. Chromium on the Pi, or a
// page opened over plain http), the same sheet shows a box to type the command instead.
//
// Recognisers: `browserSpeech` below is the only one today. A recogniser on the panel itself
// (Vosk, whisper.cpp) could be added as another { available, start } object that records audio
// and sends it to the server; the rest of this file doesn't change.

import { api } from "./api.js";
import { store } from "./store.js";
import { $, esc, icon, toast, storage } from "./util.js";

const HOLD_MS = 350;               // pressed longer than this: push-to-talk (stops when let go)
const FATAL = new Set(["not-allowed", "service-not-allowed", "network", "audio-capture", "language-not-supported"]);
const IOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

let state = "closed";              // closed | notice | listening | working | reply
let typed = storage.get("voice_typed", false);
let broken = "";                   // why speech stopped working on this screen
let heard = "";                    // what was said or typed
let reply = null;                  // the server's answer
let errorText = "";
let session = null;                // the current recognition
let held = null;                   // { timer, long } while a mic button is pressed
let levelStop = null;

// ---------- the browser's speech recogniser ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

const browserSpeech = {
  available: () => !!SR && window.isSecureContext !== false && !broken,
  // Calls onText(text, final) as words arrive, onEnd(text, error) when it stops.
  start({ onText, onEnd, onSound }) {
    const rec = new SR();
    rec.lang = navigator.language || "en-US";
    rec.interimResults = true;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let text = "", error = "";
    rec.onresult = (e) => {
      let final = "", interim = "";
      for (const r of e.results) (r.isFinal ? (final += r[0].transcript) : (interim += r[0].transcript));
      text = (final || interim).trim();
      onSound?.(1);
      onText(text, !!final && !interim);
    };
    rec.onsoundstart = () => onSound?.(0.6);
    rec.onerror = (e) => { error = e.error || "error"; };
    rec.onend = () => onEnd(text, error);
    try { rec.start(); } catch { setTimeout(() => onEnd("", "start-failed"), 0); }
    return { stop: () => { try { rec.stop(); } catch { /* already stopped */ } },
             abort: () => { rec.onend = null; try { rec.abort(); } catch { /* already stopped */ } } };
  },
};

const speechOk = () => browserSpeech.available();
const useSpeech = () => speechOk() && !typed;

// ---------- the level ring ----------
// Chrome: a real microphone level. Safari shares the microphone badly with its recogniser,
// so there the ring breathes and jumps when words arrive.
function setLevel(v) {
  $("#voice")?.style.setProperty("--level", Math.max(0, Math.min(1, v)).toFixed(2));
}
async function startLevel() {
  stopLevel();
  if (IOS || !navigator.mediaDevices?.getUserMedia || !window.AudioContext) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (state !== "listening") { stream.getTracks().forEach((t) => t.stop()); return; }
    const ctx = new AudioContext();
    const an = ctx.createAnalyser();
    an.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    let raf;
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const b of buf) sum += (b - 128) ** 2;
      setLevel(Math.sqrt(sum / buf.length) / 30);
      raf = requestAnimationFrame(tick);
    };
    tick();
    levelStop = () => { cancelAnimationFrame(raf); stream.getTracks().forEach((t) => t.stop()); ctx.close().catch(() => {}); };
  } catch { /* no level: the ring just breathes */ }
}
function stopLevel() { levelStop?.(); levelStop = null; setLevel(0); }

// ---------- open / close ----------
export const isVoiceOpen = () => state !== "closed";

export function openVoice({ listen = true } = {}) {
  heard = ""; reply = null; errorText = "";
  $("#voice-scrim").hidden = false;
  $("#voice").hidden = false;
  if (useSpeech() && !storage.get("voice_notice_seen", false)) state = "notice";
  else if (useSpeech() && listen) return listen_();
  else state = "reply";
  render();
  focusBox();
}

export function closeVoice() {
  session?.abort(); session = null;
  stopLevel();
  window.speechSynthesis?.cancel();
  state = "closed";
  $("#voice").hidden = true;
  $("#voice-scrim").hidden = true;
}

function focusBox() {
  if (!useSpeech()) setTimeout(() => $("#voice-text")?.focus(), 60);
}

// ---------- listening ----------
function listen_() {
  session?.abort();
  heard = ""; reply = null; errorText = "";
  state = "listening";
  render();
  startLevel();
  session = browserSpeech.start({
    onText: (text) => { heard = text; renderHeard(); },
    onSound: (v) => { if (!levelStop) setLevel(v); },
    onEnd: (text, error) => {
      session = null;
      stopLevel();
      if (state !== "listening") return;
      if (FATAL.has(error) || error === "start-failed") {
        broken = error;
        state = "reply";
        errorText = error === "not-allowed" || error === "service-not-allowed"
          ? "The microphone isn't allowed here. You can type the command instead."
          : "Speech recognition isn't working on this screen. You can type the command instead.";
        render(); focusBox();
        return;
      }
      if (text) return send(text);
      state = "reply";
      errorText = "I didn't hear anything. Tap the mic and try again.";
      render();
    },
  });
}

function stopListening() { session?.stop(); }

// ---------- talking to the server ----------
async function send(text, confirm = false) {
  text = String(text || "").trim();
  if (!text) return;
  heard = text; reply = null; errorText = "";
  state = "working";
  render();
  try {
    reply = await api.voice(text, confirm);
  } catch (e) {
    reply = null;
    errorText = e.message;
  }
  state = "reply";
  if (reply) speak(reply.say);
  const done = reply && reply.understood && !reply.question && !reply.confirm && !reply.failed?.length;
  if (done) {
    closeVoice();
    toast(reply.say);
    return;
  }
  render();
  focusBox();
}

function speak(text) {
  if (!text || !storage.get("voice_speak", false) || !window.speechSynthesis) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = navigator.language || "en-US";
    speechSynthesis.speak(u);
  } catch { /* no voice: the reply is on screen anyway */ }
}

// ---------- drawing ----------
// A few things to try, built from this home's real names.
function suggestions() {
  const out = [];
  const room = store.rooms.find((r) => [...store.devices.values()].some((d) => d.room === r));
  if (room) out.push(`Turn off the ${room.toLowerCase()}`);
  const scene = store.scenes[0];
  if (scene) out.push(`Run ${scene.name}`);
  const dim = [...store.devices.values()].find((d) => d.caps.includes("brightness"));
  if (dim) out.push(`Set the ${dim.name.toLowerCase()} to 30%`);
  if ([...store.devices.values()].some((d) => d.caps.includes("clean"))) out.push("Start the vacuum");
  out.push("What's on?");
  return out.slice(0, 4);
}

function micButton(big) {
  const listening = state === "listening";
  return `<button class="voice-mic${big ? " big" : ""}${listening ? " live" : ""}" data-voice-mic
            aria-label="${listening ? "Stop listening" : "Tap or hold to speak"}">
            <span class="voice-ring" aria-hidden="true"></span>${icon("mic")}</button>`;
}

function bubbles() {
  let html = "";
  if (heard) html += `<p class="voice-bubble you" id="voice-heard">${esc(heard)}</p>`;
  else if (state === "listening") html += `<p class="voice-bubble you hint" id="voice-heard">Listening…</p>`;
  if (state === "working") html += `<p class="voice-bubble panel working" aria-label="Working on it"><span></span><span></span><span></span></p>`;
  if (errorText) html += `<p class="voice-bubble panel error">${esc(errorText)}</p>`;
  if (reply) {
    html += `<p class="voice-bubble panel${reply.understood && !reply.failed?.length ? "" : " error"}">${esc(reply.say)}</p>`;
    if (reply.choices?.length) {
      html += `<div class="voice-choices">${reply.choices.map((c, i) =>
        `<button class="chip" data-voice-choice="${i}">${esc(c.label)}${c.detail ? `<small>${esc(c.detail)}</small>` : ""}</button>`).join("")}</div>`;
    }
    if (reply.confirm) {
      html += `<div class="voice-choices"><button class="btn primary" data-voice-confirm>${icon("check")}Yes, do it</button>
        <button class="btn" data-voice-close>Cancel</button></div>`;
    }
  }
  return html;
}

function render() {
  const el = $("#voice");
  if (state === "closed") return;
  el.classList.toggle("listening", state === "listening");
  const head = `<div class="grab"></div><div class="sheet-head"><div class="grow"><h2>Voice</h2>
      <p>${state === "listening" ? "Listening… tap the mic or let go when done" : "Say or type what to do"}</p></div>
      <button class="icon-btn" data-voice-close aria-label="Close">${icon("close")}</button></div>`;

  if (state === "notice") {
    el.innerHTML = `${head}<div class="voice-notice">${icon("mic")}
        <p>Your browser turns your speech into text. <b>Chrome sends the recording to Google</b>, and
        <b>Safari may use Apple's servers</b>. HomePanel only gets the text. Typed commands stay on the panel.</p></div>
      <div class="btn-row"><button class="btn primary" data-voice-ok>${icon("mic")}Use my voice</button>
        <button class="btn" data-voice-type>Type instead</button></div>`;
    return;
  }

  const speech = useSpeech();
  const tips = !heard && !reply && state !== "listening"
    ? `<div class="voice-try"><p>Try</p><div class="voice-choices">${suggestions().map((s) =>
        `<button class="chip" data-voice-say="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>` : "";
  const controls = speech
    ? `<div class="voice-controls">${micButton(true)}
        <button class="btn small" data-voice-type>Type instead</button></div>`
    : `<form class="voice-form" id="voice-form" autocomplete="off">
        <input id="voice-text" type="text" enterkeyhint="go" placeholder="Turn off the kitchen" aria-label="Command"
               maxlength="300" value="">
        <button class="btn primary" type="submit" ${state === "working" ? "disabled" : ""}>Go</button></form>
      ${speechOk() ? `<button class="btn small voice-switch" data-voice-talk>${icon("mic")}Use my voice</button>` : ""}`;
  const speakToggle = window.speechSynthesis
    ? `<label class="voice-speak"><input type="checkbox" data-voice-speak ${storage.get("voice_speak", false) ? "checked" : ""}>
        Read replies aloud</label>` : "";
  el.innerHTML = `${head}<div class="voice-talk" aria-live="polite">${bubbles()}</div>${tips}${controls}${speakToggle}`;
}

function renderHeard() {
  const b = $("#voice-heard");
  if (b) { b.textContent = heard || "Listening…"; b.classList.toggle("hint", !heard); }
}

// ---------- push-to-talk on a mic button ----------
// Tap: listen until you stop talking. Hold: listen while pressed, stop when you let go.
function pressStart(e) {
  if (e.button > 0) return;
  e.preventDefault();
  if (state === "listening") { stopListening(); return; }
  if (!useSpeech() || (state === "closed" && !storage.get("voice_notice_seen", false))) {
    if (state === "closed") openVoice();
    return;
  }
  held = { long: false, timer: setTimeout(() => { if (held) held.long = true; }, HOLD_MS) };
  if (state === "closed") openVoice();
  else listen_();
}
function pressEnd() {
  if (!held) return;
  clearTimeout(held.timer);
  if (held.long && state === "listening") stopListening();
  held = null;
}

export function setupVoice() {
  const btn = $("#voice-btn");
  btn.addEventListener("pointerdown", pressStart);
  btn.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); isVoiceOpen() ? closeVoice() : openVoice(); } });
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
  window.addEventListener("pointerup", pressEnd);
  window.addEventListener("pointercancel", pressEnd);
  $("#voice-scrim").addEventListener("click", closeVoice);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isVoiceOpen()) closeVoice(); });

  const el = $("#voice");
  el.addEventListener("contextmenu", (e) => e.preventDefault());
  el.addEventListener("pointerdown", (e) => { if (e.target.closest("[data-voice-mic]")) pressStart(e); });
  el.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#voice-text");
    send(input.value);
  });
  el.addEventListener("change", (e) => {
    if (e.target.matches("[data-voice-speak]")) storage.set("voice_speak", e.target.checked);
  });
  el.addEventListener("click", (e) => {
    const t = e.target;
    if (t.closest("[data-voice-close]")) return closeVoice();
    if (t.closest("[data-voice-ok]")) { storage.set("voice_notice_seen", true); return listen_(); }
    if (t.closest("[data-voice-type]")) {
      storage.set("voice_notice_seen", true);
      typed = true; storage.set("voice_typed", true);
      session?.abort(); session = null; stopLevel();
      state = "reply"; render(); return focusBox();
    }
    if (t.closest("[data-voice-talk]")) {
      typed = false; storage.set("voice_typed", false);
      return storage.get("voice_notice_seen", false) ? listen_() : (state = "notice", render());
    }
    const say = t.closest("[data-voice-say]");
    if (say) return send(say.dataset.voiceSay);
    const choice = t.closest("[data-voice-choice]");
    if (choice) return send(reply.choices[Number(choice.dataset.voiceChoice)].text);
    if (t.closest("[data-voice-confirm]")) return send(reply.heard, true);
  });
}
