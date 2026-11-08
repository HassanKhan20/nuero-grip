import { createHand } from "./hand.js";
import { createTour } from "./onboarding.js";

const $ = (id) => document.getElementById(id);
const role = document.body.dataset.role;
const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };
const icon = (name) => `<svg><use href="#i-${name}"/></svg>`;

// ---------- conditions ----------
const CONDITIONS = {
  stroke: { title: "Stroke recovery", mark: "STROKE", note: () => "Moves only while you try",
    stats: ["reps", "activation", "session", "difficulty"] },
  parkinsons: { title: "Parkinson's", mark: "TREMOR", note: (s) => (s.tremor_hz > 0 ? `Tremor ${s.tremor_hz.toFixed(1)} Hz` : "No tremor detected"),
    stats: ["tremor", "steadiness", "taprate", "tapdec"], test: "tap" },
  phantom: { title: "Phantom limb", mark: "MIRROR", note: () => "Mirrored hand for mirror therapy",
    stats: ["reps", "activation", "session", "difficulty"] },
  cp: { title: "Cerebral palsy", mark: "CP", note: () => "Child-size hand · joint color shows flexion",
    stats: ["reps", "activation", "session", "difficulty"] },
  cognitive: { title: "Cognitive screening", mark: "REACT", note: () => "Squeeze when the screen flashes",
    stats: ["rtMean", "rtLast", "rtTrials", "rtTrend"], test: "reaction" },
};

const tapOk = (s) => s.tapping && !s.tapping.error;
const STATS = {
  reps: ["Reps", "repeat", (s) => s.reps],
  activation: ["Activation", "bolt", (s) => `${s.activation_rate.toFixed(0)}%`],
  session: ["Session time", "timer", (s) => fmtClock((s.session_s || 0) * 1000)],
  difficulty: ["Difficulty", "level", (s) => `${s.difficulty} / 5`],
  tremor: ["Tremor", "wave", (s) => (s.tremor_hz > 0 ? `${s.tremor_hz.toFixed(1)} Hz` : "None")],
  steadiness: ["Steadiness", "target", (s) => `${s.steadiness.toFixed(0)} / 100`],
  taprate: ["Tap rate", "tap", (s) => (tapOk(s) ? `${s.tapping.rate_hz.toFixed(1)} /s` : "—")],
  tapdec: ["Tap decrement", "trend", (s) => (tapOk(s) ? `${s.tapping.decrement_pct.toFixed(0)}%` : "—")],
  rtMean: ["Mean reaction", "timer", (s) => (s.latency_ms_mean != null ? `${s.latency_ms_mean} ms` : "—")],
  rtLast: ["Last trial", "bolt", (s) => (s.latencies?.length ? `${s.latencies.at(-1)} ms` : "—")],
  rtTrials: ["Trials", "hash", (s) => s.latency_trials],
  rtTrend: ["Trend", "trend", (s) => {
    const l = s.latencies || [];
    if (l.length < 4) return "—";
    const k = Math.floor(l.length / 2);
    const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const d = Math.round(avg(l.slice(k)) - avg(l.slice(0, k)));
    return `${d > 0 ? "+" : ""}${d} ms`;
  }],
};

// type -> [label, severity, icon]
const EVENTS = {
  latency: ["Reaction", "info", "timer"],
  latency_miss: ["Reaction missed", "warn", "timer"],
  tapping: ["Tap test done", "info", "tap"],
  calibrated: ["Calibrated", "info", "target"],
  calibration_failed: ["Calibration failed", "bad", "target"],
  agent_alert: ["AI alert", "bad", "bolt"],
};
const SEV_LABEL = { bad: "High", warn: "Medium", info: "Info" };
const SOURCE_LABELS = { mock: "Simulated", camera: "Camera", hardware: "Headband" };

// ---------- helpers ----------
async function api(path, method = "POST", body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}
const fail = (err) => toast(err.message);

const fmtClock = (ms) => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

let audio = null;
document.addEventListener("pointerdown", () => { audio ??= new AudioContext(); }, { once: true });
function beep(hz = 1200, ms = 180) {
  if (!audio) return;
  const o = audio.createOscillator(), g = audio.createGain();
  o.frequency.value = hz;
  g.gain.value = 0.12;
  o.connect(g).connect(audio.destination);
  o.start();
  o.stop(audio.currentTime + ms / 1000);
}

// ---------- hand: 3D when WebGL works, flat SVG otherwise ----------
let hand = null;
try {
  const m = await import("./hand3d.js");
  if (m.supportsWebGL()) {
    hand = m.createHand3D($("hand3d"));
    hand.onAnchors((a) => drawLeaders(a));
  }
} catch (err) {
  console.warn("3D hand unavailable, using flat hand", err);
}
if (!hand) {
  $("hand3d").classList.add("flat");
  const flat = createHand($("hand3d"));
  hand = { update: (s, g) => flat.update(s.angles, g), setView() {}, rotate() {} };
  $("leaders").hidden = true;
  document.querySelector(".view-bar").hidden = true;
}
document.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
  hand.setView(b.dataset.view);
  document.querySelectorAll("[data-view]").forEach((x) => x.classList.toggle("on", x === b));
}));
document.querySelectorAll("[data-rot]").forEach((b) => b.addEventListener("click", () => {
  hand.rotate(Number(b.dataset.rot));
  document.querySelectorAll("[data-view]").forEach((x) => x.classList.remove("on"));
}));

function gateState(s) {
  if (!s.sensors_ok) return ["Sensors offline", "bad", "blocked"];
  if (!s.calibrated) return ["Calibrating", "", ""];
  if (s.gate_open) return ["Moving", "good", "open"];
  if (s.control_mode === "intent") return [Math.max(...s.angles) > 0 ? "Opening" : "Waiting", "", ""];
  if (!s.curls) return ["No hand in view", "", ""];
  return [s.intent_active ? "Holding" : "Waiting", "", ""];
}

// ---------- sheets (dialogs) ----------
const dockButtons = document.querySelectorAll(".icon-btn[data-sheet]");
function openSheet(id) {
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
  dockButtons.forEach((b) => b.classList.toggle("on", b.dataset.sheet === id));
  if (id) $(id)?.showModal();
}
document.querySelectorAll("[data-sheet]").forEach((b) => b.addEventListener("click", () => openSheet(b.dataset.sheet)));
document.querySelectorAll("dialog").forEach((d) => {
  d.querySelector(".close")?.addEventListener("click", () => d.close());
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
  d.addEventListener("close", () => dockButtons.forEach((b) => b.classList.toggle("on", b.dataset.sheet === "")));
});

// ---------- condition + status rows ----------
let currentMode = null;
function applyCondition(mode) {
  const c = CONDITIONS[mode] || CONDITIONS.stroke;
  setText("cond-title", c.title);
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  $("stats").replaceChildren(...c.stats.map((key) => {
    const item = document.createElement("div");
    item.className = "spec-item";
    item.innerHTML = `<span></span><b data-stat="${key}">—</b>`;
    item.querySelector("span").textContent = STATS[key][0];
    return item;
  }));
  setText("watermark", c.mark);
  const hasTest = role === "therapist" && !!c.test;
  if ($("test-tap")) $("test-tap").hidden = c.test !== "tap";
  if ($("test-reaction")) $("test-reaction").hidden = c.test !== "reaction";
  $("cam-card").hidden = hasTest; // one context card: the condition's test, otherwise the camera
}

// ---------- finger callouts + leader lines ----------
const FINGER_KEYS = ["thumb", "index", "middle", "ring", "pinky"];
const callouts = Object.fromEntries([...document.querySelectorAll(".callout")].map((el) => [el.dataset.anchor, el]));
function renderCallouts(s) {
  const peaks = s.finger_peak_deg || [0, 0, 0, 0, 0];
  FINGER_KEYS.forEach((k, i) => {
    const el = callouts[k];
    if (!el) return;
    const now = s.angles[i] || 0, peak = peaks[i] || 0;
    el.querySelector('[data-co="now"]').textContent = `${now}°`;
    el.querySelector('[data-co="pct"]').textContent = `${Math.round((now / 160) * 100)}% closed`;
    el.querySelector('[data-co="bar"]').style.width = `${(now / 160) * 100}%`;
    el.querySelector('[data-co="peak"]').style.left = `calc(${(peak / 160) * 100}% - 1px)`;
    el.querySelector('[data-co="peaklabel"]').textContent = `Peak ${peak}° · ${Math.round((peak / 160) * 100)}% range this session`;
  });
  const w = callouts.wrist;
  if (w) {
    w.querySelector('[data-co="intent"]').textContent = s.intent_strength.toFixed(2);
    w.querySelector('[data-co="tremor"]').textContent = s.tremor_hz > 0 ? `${s.tremor_hz.toFixed(1)} Hz` : "None";
  }
}

const leaders = $("leaders");
const stageEl = $("stage");
function drawLeaders(anchors) {
  const sr = stageEl.getBoundingClientRect();
  if (!sr.width) return;
  let html = "";
  for (const [key, el] of Object.entries(callouts)) {
    const a = anchors[key];
    if (!a) continue;
    const r = el.getBoundingClientRect();
    const left = el.closest(".callouts").classList.contains("left");
    const x0 = (left ? r.right : r.left) - sr.left, y0 = r.top + r.height / 2 - sr.top;
    const elbow = x0 + (left ? 18 : -18);
    html += `<path d="M${x0},${y0} H${elbow} L${a.x},${a.y}"/><circle cx="${a.x}" cy="${a.y}" r="3.5"/>`;
  }
  leaders.innerHTML = html;
}

// ---------- camera mini panel ----------
let camStarted = false;
function renderCamera(s) {
  const img = $("cam");
  let msg = "";
  let tag = "Off";
  if (s.source_kind === "mock") msg = "Simulated hand · no camera";
  else if (!s.camera_ok) msg = "Camera unavailable";
  else if (s.control_mode !== "mirror") { msg = "Not used in intent-only control"; tag = "Idle"; }
  else {
    tag = "Live";
    if (!camStarted) {
      camStarted = true;
      img.onload = () => { img.hidden = false; };
      img.onerror = () => { camStarted = false; img.hidden = true; };
      img.src = "/video_feed";
    }
  }
  img.hidden = !(tag === "Live" && img.complete && img.naturalWidth);
  setText("cam-msg", msg);
  $("cam-msg").hidden = !msg;
  setText("cam-tag", tag);
}

// ---------- intent waveform ----------
const wave = [];
const waveY = (v) => 42 - v * 40;
function drawWave() {
  $("wave-line").setAttribute("points", wave.map((v, i) => `${(i / 99) * 200},${waveY(v)}`).join(" "));
}
$("wave").addEventListener("pointermove", (e) => {
  if (!wave.length) return;
  const r = $("wave").getBoundingClientRect();
  const i = Math.max(0, Math.min(wave.length - 1, Math.round(((e.clientX - r.left) / r.width) * 99)));
  const v = wave[i];
  if (v === undefined) return;
  const dot = $("wave-dot");
  dot.setAttribute("cx", (i / 99) * 200);
  dot.setAttribute("cy", waveY(v));
  dot.hidden = false;
  const tip = $("wave-tip");
  tip.textContent = `${v.toFixed(2)} · ${((wave.length - 1 - i) / 10).toFixed(1)} s ago`;
  tip.style.left = `${e.clientX - r.left}px`;
  tip.hidden = false;
});
$("wave").addEventListener("pointerleave", () => { $("wave-tip").hidden = true; $("wave-dot").hidden = true; });

// ---------- reaction chart ----------
let lastTrialsSig = "";
function drawTrials(latencies) {
  const svg = $("trials");
  if (!svg) return;
  $("trials-wrap").hidden = !latencies.length;
  const sig = latencies.join(",");
  if (sig === lastTrialsSig) return;
  lastTrialsSig = sig;
  const ns = "http://www.w3.org/2000/svg";
  svg.replaceChildren();
  const base = document.createElementNS(ns, "line");
  Object.entries({ x1: 0, y1: 59, x2: 200, y2: 59, class: "baseline" }).forEach(([k, v]) => base.setAttribute(k, v));
  svg.append(base);
  const max = Math.max(1000, ...latencies);
  const w = 20;
  latencies.forEach((ms, i) => {
    const h = Math.max(2, (ms / max) * 56);
    const r = document.createElementNS(ns, "rect");
    Object.entries({ x: i * w + 3, y: 59 - h, width: w - 6, height: h, rx: 3, class: "bar-mark" }).forEach(([k, v]) => r.setAttribute(k, v));
    r.addEventListener("pointerenter", () => {
      const tip = $("trials-tip");
      tip.textContent = `Trial ${i + 1}: ${ms} ms`;
      tip.style.left = `${((i + 0.5) * w / 200) * 100}%`;
      tip.hidden = false;
    });
    r.addEventListener("pointerleave", () => { $("trials-tip").hidden = true; });
    svg.append(r);
  });
}

// ---------- needs attention ----------
let lastEventsSig = "";
function eventItem(e) {
  const [label, sev, ic] = EVENTS[e.type] || [e.type, "info", "list"];
  const li = document.createElement("li");
  li.className = sev;
  li.innerHTML = `<span class="what"><span></span><small></small></span><span class="sev"></span>`;
  li.querySelector(".what span").textContent = e.message || label + (e.ms !== undefined ? ` · ${e.ms} ms` : "");
  li.querySelector(".what small").textContent = `${fmtClock(e.t || 0)}${e.message ? ` · ${label}` : ""}`;
  li.querySelector(".sev").textContent = SEV_LABEL[sev];
  return li;
}
function renderEvents(events) {
  const shown = events.filter((e) => EVENTS[e.type]);
  const sig = shown.length + JSON.stringify(shown.slice(-1));
  if (sig === lastEventsSig) return;
  lastEventsSig = sig;
  const recent = [...shown].reverse();
  const empty = () => { const li = document.createElement("li"); li.className = "empty"; li.textContent = "Nothing yet"; return li; };
  $("event-log-all").replaceChildren(...(recent.length ? recent.map(eventItem) : [empty()]));
  const flagged = recent.filter((e) => EVENTS[e.type][1] !== "info").length;
  setText("attn-badge", flagged);
  $("attn-badge").hidden = !flagged;
}

// ---------- tap results ----------
function renderTapping(t) {
  if (!t || !$("tap-results")) return;
  $("tap-results").hidden = !!t.error;
  const flag = $("tap-flag");
  flag.hidden = false;
  if (t.error) {
    flag.className = "flag warn";
    flag.textContent = "Not enough taps. Keep the hand in view.";
    return;
  }
  setText("tap-taps", t.taps);
  setText("tap-rate", `${t.rate_hz.toFixed(1)} /s`);
  setText("tap-dec", `${t.decrement_pct.toFixed(0)}%`);
  setText("tap-cv", t.rhythm_cv.toFixed(2));
  const concern = t.flag !== "within typical range";
  flag.className = `flag ${concern ? "warn" : "good"}`;
  flag.textContent = concern ? "Possible bradykinesia · review with a clinician" : "Within typical range";
}

// ---------- controls state ----------
function renderControl(s) {
  const intentMode = s.control_mode === "intent";
  document.querySelectorAll("[data-control]").forEach((b) => b.classList.toggle("on", b.dataset.control === s.control_mode));
  document.querySelectorAll("[data-grip]").forEach((b) => b.classList.toggle("on", b.dataset.grip === s.grip));
  $("grip-row").hidden = !intentMode;
  const hw = s.source_kind === "hardware";
  $("sim-intent").hidden = hw;
  $("hw-intent").hidden = !hw;
  $("auto-intent").checked = s.intent_auto;
  $("btn-hold").classList.toggle("active", s.intent_held);

  setText("intent-val", s.intent_strength.toFixed(2));
  setText("intent-label", !s.calibrated ? "Calibrating" : s.intent_active ? "Trying" : "Relaxed");
  $("intent-label").classList.toggle("on", s.intent_active);
  wave.push(s.intent_strength);
  if (wave.length > 100) wave.shift();
  drawWave();

  const t = s.touch || {};
  setText("pad-temple", t.temple ?? "—");
  setText("pad-forearm", t.forearm ?? "—");
  setText("pad-temple-d", s.calibrated ? `${(t.temple_drop * 100).toFixed(0)}% change` : "");
  setText("pad-forearm-d", s.calibrated ? `${(t.forearm_drop * 100).toFixed(0)}% change` : "");
  setText("cal-status", s.range_calibrated ? "Calibrated" : "Default threshold");
  setText("difficulty", s.difficulty);
}

function renderOverlays(s) {
  $("cue-overlay").hidden = !s.cue_active;
  $("tap-overlay").hidden = !s.tapping_active;
  setText("tap-left", Math.ceil(s.tapping_remaining_s));
  setText("cue-status", s.cue_pending ? "Get ready" : s.cue_active ? "Waiting for grip" : "Cue appears after 1–3 s");
  const cal = s.calibration_phase;
  $("cal-overlay").hidden = !cal;
  if (cal) {
    const sim = s.source_kind !== "hardware";
    setText("cal-word", cal === "relax" ? "Relax" : "Squeeze");
    setText("cal-help", cal === "relax" ? "Keep still" : `Clench your jaw and squeeze hard${sim ? " (hold Space)" : ""}`);
    setText("cal-left", Math.ceil(s.calibration_remaining_s));
    $("cal-overlay").classList.toggle("squeeze", cal === "squeeze");
  }
}

// ---------- main render ----------
let tourChecked = false;
let lastState = null;
function render(s) {
  lastState = s;
  window.dispatchEvent(new CustomEvent("ng-state", { detail: s }));
  if (!tourChecked) { tourChecked = true; tour.startIfNew(); }
  if (s.mode !== currentMode) { currentMode = s.mode; applyCondition(s.mode); }
  const src = SOURCE_LABELS[s.source_kind] || s.source_kind;
  setText("source-label", src);
  setText("cond-note", `${src} · ${(CONDITIONS[s.mode] || CONDITIONS.stroke).note(s)}`);

  const [label, cls, handState] = gateState(s);
  const pill = $("gate-status");
  pill.textContent = label;
  pill.className = `pill ${cls}`;
  hand.update(s, handState);

  renderCallouts(s);
  renderCamera(s);
  renderControl(s);
  renderOverlays(s);
  document.querySelectorAll("[data-stat]").forEach((el) => { el.textContent = STATS[el.dataset.stat][2](s); });
  renderEvents(s.events);
  drawTrials(s.latencies || []);
  if (s.tapping) renderTapping(s.tapping);
}

// ---------- onboarding ----------
const tour = createTour({ role, api, toast });
$("btn-tour").addEventListener("click", () => tour.start());

// ---------- socket ----------
const socket = io();
socket.on("connect", () => $("conn-dot").classList.add("live"));
socket.on("disconnect", () => { $("conn-dot").classList.remove("live"); setText("cond-note", "Reconnecting…"); });
socket.on("state", render);
socket.on("event", (e) => {
  if (e.type === "cue") { $("cue-overlay").hidden = false; beep(1400, 200); }
  if (e.type === "latency") toast(`Reaction ${e.ms} ms`);
  if (e.type === "latency_miss") toast("No grip within 3 s");
  if (e.type === "tapping") { renderTapping(e); toast(e.error ? "Not enough taps" : `${e.taps} taps`); }
  if (e.type === "calibration_squeeze") beep(900, 150);
  if (e.type === "calibrated") toast(`Calibrated · temple ${e.temple_range_pct}%, forearm ${e.forearm_range_pct}%`);
  if (e.type === "calibration_failed") toast(e.reason);
  if (e.type === "agent_alert" && e.message) toast(e.message);
});

// ---------- controls ----------
document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => api("/api/mode", "POST", { mode: b.dataset.mode }).catch(fail)));
document.querySelectorAll("[data-control]").forEach((b) => b.addEventListener("click", () => api("/api/control", "POST", { mode: b.dataset.control }).catch(fail)));
document.querySelectorAll("[data-grip]").forEach((b) => b.addEventListener("click", () => api("/api/control", "POST", { mode: "intent", grip: b.dataset.grip }).catch(fail)));
$("btn-cal").addEventListener("click", () => { openSheet(""); api("/api/calibrate").catch(fail); });
$("auto-intent").addEventListener("change", (e) => api("/api/intent/auto", "POST", { auto: e.target.checked }).catch(fail));

let held = false;
function setHeld(v) {
  if (v === held) return;
  held = v;
  api("/api/intent", "POST", { held: v }).catch(fail);
}
const holdBtn = $("btn-hold");
holdBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); setHeld(true); });
["pointerup", "pointerleave", "pointercancel"].forEach((ev) => holdBtn.addEventListener(ev, () => setHeld(false)));
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && !document.querySelector("dialog[open]")
      && !["INPUT", "SELECT", "TEXTAREA", "BUTTON", "SUMMARY"].includes(document.activeElement.tagName)) {
    e.preventDefault();
    setHeld(true);
  }
});
document.addEventListener("keyup", (e) => { if (e.code === "Space") setHeld(false); });
window.addEventListener("blur", () => setHeld(false));

async function busy(btn, statusId, fn) {
  btn.disabled = true;
  setText(statusId, "Working…");
  try { await fn(); setText(statusId, ""); }
  catch (err) { setText(statusId, err.message); }
  finally { btn.disabled = false; }
}

if (role === "therapist") {
  const changeDiff = (d) => api("/api/difficulty", "POST", { level: Number($("difficulty").textContent) + d }).catch(fail);
  $("diff-up").onclick = () => changeDiff(1);
  $("diff-down").onclick = () => changeDiff(-1);
  $("btn-cue").onclick = () => api("/api/latency").catch(fail);
  $("btn-tap").onclick = () => api("/api/tapping", "POST", { seconds: 10 }).catch(fail);

  // ----- session report: readable agent steps + export to PDF -----
  const ACTIONS = {
    get_session_metrics: (a, r) => ["Read this session",
      `${r.reps ?? 0} reps · ${Math.round(r.activation_rate ?? 0)}% activation · ${fmtClock((r.session_s || 0) * 1000)} long`],
    get_patient_history: (a, r) => ["Compared with past sessions",
      Array.isArray(r) ? (r.length ? `${r.length} previous session${r.length > 1 ? "s" : ""} on record` : "No previous sessions on record") : ""],
    set_difficulty: (a, r, ctx) => {
      const to = r.level ?? a.level;
      const from = ctx.before;
      const title = from == null || from === to ? `Kept difficulty at ${to}`
        : `${to < from ? "Lowered" : "Raised"} difficulty from ${from} to ${to}`;
      return [title, a.reason || r.reason || ""];
    },
    trigger_feedback: (a) => [a.kind === "celebrate" ? "Sent a celebration cue" : "Sent an alert to the dashboard", a.message || ""],
  };
  let lastReport = null;

  function buildReport(r, snap, startedAt) {
    const ctx = { before: snap?.difficulty ?? null };
    const metricsStep = r.trace.find((t) => t.tool === "get_session_metrics" && !t.result?.error);
    if (metricsStep?.result?.difficulty != null) ctx.before = metricsStep.result.difficulty;
    const steps = r.trace.map((t) => {
      const fn = ACTIONS[t.tool];
      const [title, detail] = t.result?.error ? [`${t.tool} failed`, t.result.error]
        : fn ? fn(t.args || {}, t.result || {}, ctx) : [t.tool, ""];
      return { title, detail, reasoning: t.reasoning || "" };
    });
    const setStep = [...r.trace].reverse().find((t) => t.tool === "set_difficulty" && !t.result?.error);
    const after = setStep ? (setStep.result.level ?? setStep.args.level) : ctx.before;
    // show the numbers the agent actually analyzed, not the screen at click time
    const analyzed = metricsStep ? { ...(snap || {}), ...metricsStep.result } : (snap || {});
    return { r, snap: analyzed, steps, before: ctx.before, after, at: startedAt };
  }

  function renderReport(rep) {
    const s = rep.snap;
    const cond = CONDITIONS[s.mode] || CONDITIONS.stroke;
    const when = rep.at.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    setText("rep-meta", `Patient ${s.patient_id || "demo"} · ${cond.title} · ${when} · ${fmtClock((s.session_s || 0) * 1000)} session`);
    const cards = cond.stats.filter((k) => k !== "difficulty").map((k) => [STATS[k][0], STATS[k][2](s)]);
    cards.push(["Difficulty", rep.before != null && rep.after !== rep.before ? `${rep.before} → ${rep.after}` : `${rep.after ?? "—"}`]);
    $("rep-metrics").replaceChildren(...cards.map(([label, value]) => {
      const d = document.createElement("div");
      d.innerHTML = "<span></span><b></b>";
      d.querySelector("span").textContent = label;
      d.querySelector("b").textContent = value;
      return d;
    }));
    setText("rep-summary", rep.r.summary || "No summary returned.");
    setText("rep-plan", rep.r.next_session_plan || "—");
    $("rep-steps").replaceChildren(...rep.steps.map((st) => {
      const li = document.createElement("li");
      const title = document.createElement("b");
      title.textContent = st.title;
      li.append(title);
      if (st.detail) {
        const p = document.createElement("p");
        p.textContent = st.detail;
        li.append(p);
      }
      if (st.reasoning) {
        const det = document.createElement("details");
        det.className = "no-print";
        det.innerHTML = "<summary>Agent reasoning</summary><p></p>";
        det.querySelector("p").textContent = st.reasoning;
        li.append(det);
      }
      return li;
    }));
    if (!rep.steps.length) $("rep-steps").innerHTML = "<li><b>Answered without using tools</b></li>";
  }

  const review = async () => {
    const btn = $("btn-agent");
    btn.disabled = true;
    setText("agent-status", "Nemotron is reviewing the session… about 15 s");
    const snap = lastState;
    const startedAt = new Date();
    try {
      const r = await api("/api/agent");
      lastReport = buildReport(r, snap, startedAt);
      renderReport(lastReport);
      setText("agent-status", `Reviewed ${startedAt.toLocaleTimeString([], { timeStyle: "short" })}`);
      $("agent-preview").textContent = r.summary || "";
      $("agent-preview").hidden = !r.summary;
      $("btn-report").hidden = false;
      openSheet("sheet-report");
    } catch (err) {
      setText("agent-status", err.message);
    } finally {
      btn.disabled = false;
    }
  };
  $("btn-report").onclick = () => { if (lastReport) openSheet("sheet-report"); };

  // Export PDF: print just the open sheet; the browser's "Save as PDF" names the file from the title
  document.querySelectorAll("[data-print]").forEach((b) => b.addEventListener("click", () => {
    const original = document.title;
    document.title = `NeuroGrip ${b.dataset.print} ${new Date().toISOString().slice(0, 10)}`;
    window.addEventListener("afterprint", () => { document.title = original; }, { once: true });
    window.print();
  }));

  $("btn-agent").onclick = review;
  $("btn-end").onclick = async () => {
    try {
      await api("/api/session/end");
    } catch (err) {
      toast(err.message);
      return;
    }
    toast("Session saved");
    review(); // the agent reviews every finished session
  };

  $("btn-triage").onclick = () => busy($("btn-triage"), "triage-status", async () => {
    const r = await api("/api/triage", "GET");
    const tbody = $("triage-table").querySelector("tbody");
    const labels = { urgent: "Urgent", monitor: "Monitor", stable: "Stable" };
    const trends = { improving: "Improving", declining: "Declining", stable: "Stable" };
    tbody.replaceChildren(...r.patients.map((p) => {
      const tr = document.createElement("tr");
      [labels[p.urgency] || p.urgency, p.name, p.condition, trends[p.trend] || "—", `${p.last_session_days_ago} d`, p.reason].forEach((v, i) => {
        const td = document.createElement("td");
        td.textContent = v;
        if (i === 0) td.className = `urg ${p.urgency}`;
        if (i === 3) td.className = `trend ${p.trend || ""}`;
        tr.append(td);
      });
      return tr;
    }));
    $("triage-table").hidden = false;
    setText("caseload-meta", `Ranked ${new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} by NVIDIA Nemotron`);
    $("btn-caseload-pdf").hidden = false;
  });
} else {
  $("btn-explain").onclick = () => busy($("btn-explain"), "explain-status", async () => {
    const r = await api("/api/patient_view");
    setText("explain-text", r.text);
  });
}
