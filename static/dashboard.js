import { createHand } from "./hand.js";

const $ = (id) => document.getElementById(id);
const role = document.body.dataset.role;
const FINGERS = ["thumb", "index", "middle", "ring", "pinky"];

const MODE_INFO = {
  stroke: { title: "Stroke Recovery", highlight: ["grip", "activation", "compensation", "intent"] },
  parkinsons: { title: "Parkinson's Monitoring", highlight: ["tremor", "steadiness", "parkinsons"] },
  phantom: { title: "Phantom Limb Mirror Therapy", highlight: ["grip", "activation", "reps"] },
  cp: { title: "Pediatric Cerebral Palsy", highlight: ["grip", "reps", "compensation", "difficulty"] },
  cognitive: { title: "Cognitive Decline Screening", highlight: ["latency", "cognitive"] },
};

const EVENT_LABELS = {
  shoulder_hike: ["Shoulder hike (compensation)", "warn"],
  trunk_lean: ["Trunk lean (compensation)", "warn"],
  latency: ["Reaction time", "info"],
  latency_miss: ["Reaction test missed (>3 s)", "warn"],
  cue: ["Reaction cue shown", "info"],
  tapping: ["Finger-tap test complete", "info"],
  calibration_squeeze: ["Calibration: squeeze phase", "info"],
  calibrated: ["Intent calibrated to wearer", "info"],
  calibration_failed: ["Calibration failed", "warn"],
};

const SOURCE_LABELS = { mock: "MOCK DATA", camera: "CAMERA MODE", hardware: "HARDWARE" };

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

const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };
const fmtClock = (ms) => {
  const s = Math.floor(ms / 1000);
  return `T+${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4000);
}

// ---------- audio cue (unlocked on first user gesture) ----------
let audio = null;
document.addEventListener("pointerdown", () => { audio ??= new AudioContext(); }, { once: true });
function beep(hz = 1200, ms = 180) {
  if (!audio) return;
  const o = audio.createOscillator(), g = audio.createGain();
  o.frequency.value = hz;
  g.gain.value = 0.15;
  o.connect(g).connect(audio.destination);
  o.start();
  o.stop(audio.currentTime + ms / 1000);
}

// ---------- hero: camera + robotic hand ----------
const hand = createHand($("hand"));
let camStarted = false;
function ensureCamera(s) {
  const usesCamera = s.source_kind !== "mock" && s.camera_ok;
  if (usesCamera && !camStarted) {
    camStarted = true;
    const img = $("cam");
    img.onload = () => { img.hidden = false; $("cam-placeholder").hidden = true; };
    img.onerror = () => { camStarted = false; };
    img.src = "/video_feed";
  }
  if (s.source_kind === "mock") setText("cam-msg", "Mock mode: synthetic hand data, no camera");
  else if (!s.camera_ok) setText("cam-msg", "Camera could not be opened. Check NG_CAMERA or close other apps using it");
}

function gateState(s) {
  if (!s.sensors_ok) return ["Sensors offline", "bad", "blocked"];
  if (!s.calibrated) return ["Calibrating", "idle", ""];
  if (s.compensation && s.compensation.length) return ["Blocked: fix posture", "bad", "blocked"];
  if (s.control_mode === "intent") {
    if (s.gate_open) return ["Moving by intent", "good", "open"];
    if (Math.max(...s.angles) > 0) return ["Relaxed: opening", "idle", ""];
    return ["Try to grip", "idle", ""];
  }
  if (s.gate_open) return ["Moving with you", "good", "open"];
  if (!s.curls) return ["Show your healthy hand", "idle", ""];
  if (!s.intent_active) return ["Waiting for intent", "idle", ""];
  return ["Holding", "idle", ""];
}

// ---------- mode ----------
let currentMode = null;
function applyMode(mode) {
  const info = MODE_INFO[mode] || MODE_INFO.stroke;
  setText("mode-title", info.title);
  $("mode-select").value = mode;
  document.querySelectorAll("[data-metric]").forEach((el) => {
    el.classList.toggle("highlight", info.highlight.includes(el.dataset.metric));
  });
  $("hand").classList.toggle("mirrored", mode === "phantom");
}

// ---------- charts ----------
const spark = [];
let lastSparkAt = 0;
function drawSpark() {
  const n = spark.length;
  const x = (i) => (n < 2 ? 120 : (i / (n - 1)) * 120);
  const y = (v) => 30 - (v / 100) * 28;
  $("spark-line").setAttribute("points", spark.map((v, i) => `${x(i)},${y(v)}`).join(" "));
}
function sparkHover(e) {
  if (!spark.length) return;
  const r = $("spark").getBoundingClientRect();
  const i = Math.max(0, Math.min(spark.length - 1, Math.round(((e.clientX - r.left) / r.width) * (spark.length - 1))));
  const v = spark[i];
  const dot = $("spark-dot");
  dot.setAttribute("cx", spark.length < 2 ? 120 : (i / (spark.length - 1)) * 120);
  dot.setAttribute("cy", 30 - (v / 100) * 28);
  dot.hidden = false;
  const tip = $("spark-tip");
  tip.textContent = `${v.toFixed(0)}% · ${spark.length - 1 - i}s ago`;
  tip.style.left = `${e.clientX - r.left}px`;
  tip.hidden = false;
}
$("spark").addEventListener("pointermove", sparkHover);
$("spark").addEventListener("pointerleave", () => { $("spark-tip").hidden = true; $("spark-dot").hidden = true; });

const wave = [];
const waveY = (v) => 39 - v * 38;
function drawWave() {
  const n = wave.length;
  $("wave-line").setAttribute("points", wave.map((v, i) => `${(i / Math.max(1, 99)) * 200},${waveY(v)}`).join(" "));
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
  tip.textContent = `Intent ${v.toFixed(2)} · ${((wave.length - 1 - i) / 10).toFixed(1)}s ago`;
  tip.style.left = `${e.clientX - r.left}px`;
  tip.hidden = false;
});
$("wave").addEventListener("pointerleave", () => { $("wave-tip").hidden = true; $("wave-dot").hidden = true; });

function renderControl(s) {
  const intentMode = s.control_mode === "intent";
  document.querySelectorAll("[data-control]").forEach((b) => b.classList.toggle("on", b.dataset.control === s.control_mode));
  document.querySelectorAll("[data-grip]").forEach((b) => b.classList.toggle("on", b.dataset.grip === s.grip));
  $("grip-row").hidden = !intentMode;
  $("cam-frame").classList.toggle("dimmed", intentMode);
  $("cam-off-note").hidden = !intentMode;
}

let lastTrialsSig = "";
function drawTrials(latencies) {
  const svg = $("trials");
  if (!svg) return;
  const sig = latencies.join(",");
  if (sig === lastTrialsSig) return;
  lastTrialsSig = sig;
  svg.replaceChildren();
  const ns = "http://www.w3.org/2000/svg";
  const base = document.createElementNS(ns, "line");
  Object.entries({ x1: 0, y1: 59, x2: 200, y2: 59, class: "baseline" }).forEach(([k, v]) => base.setAttribute(k, v));
  svg.append(base);
  const max = Math.max(1000, ...latencies);
  const w = 200 / 10;
  latencies.forEach((ms, i) => {
    const h = Math.max(2, (ms / max) * 56);
    const r = document.createElementNS(ns, "rect");
    Object.entries({ x: i * w + 2, y: 59 - h, width: w - 4, height: h, rx: 2, class: "trial-bar" })
      .forEach(([k, v]) => r.setAttribute(k, v));
    r.addEventListener("pointerenter", (e) => {
      const tip = $("trials-tip");
      tip.textContent = `Trial ${i + 1}: ${ms} ms`;
      tip.style.left = `${((i + 0.5) * w / 200) * 100}%`;
      tip.hidden = false;
    });
    r.addEventListener("pointerleave", () => { $("trials-tip").hidden = true; });
    svg.append(r);
  });
}

// ---------- incident log ----------
let lastEventsSig = "";
function renderEvents(events) {
  const ul = $("event-log");
  if (!ul) return;
  const sig = events.length + JSON.stringify(events.slice(-1));
  if (sig === lastEventsSig) return;
  lastEventsSig = sig;
  ul.replaceChildren();
  if (!events.length) { ul.innerHTML = '<li class="muted">No incidents yet</li>'; return; }
  [...events].reverse().forEach((e) => {
    const [label, sev] = EVENT_LABELS[e.type] || [e.type, "info"];
    const li = document.createElement("li");
    li.className = sev;
    const time = document.createElement("time");
    time.textContent = fmtClock(e.t);
    const tag = document.createElement("span");
    tag.className = "sev";
    tag.textContent = sev === "warn" ? "⚠ WARN" : "INFO";
    li.append(time, tag, label + (e.ms !== undefined ? `: ${e.ms} ms` : ""));
    ul.append(li);
  });
}

// ---------- tapping results ----------
function renderTapping(t) {
  if (!t || !$("tap-results")) return;
  $("tap-results").hidden = false;
  const flag = $("tap-flag");
  flag.hidden = false;
  if (t.error) {
    ["tap-taps", "tap-rate", "tap-dec", "tap-cv"].forEach((id) => setText(id, "—"));
    setText("tap-taps", t.taps ?? 0);
    flag.className = "flag warn";
    flag.textContent = "⚠ Not enough taps detected. Keep the hand in view and try again";
    return;
  }
  setText("tap-taps", t.taps);
  setText("tap-rate", t.rate_hz.toFixed(2));
  setText("tap-dec", t.decrement_pct.toFixed(0));
  setText("tap-cv", t.rhythm_cv.toFixed(2));
  const concern = t.flag !== "within typical range";
  flag.className = `flag ${concern ? "warn" : "good"}`;
  flag.textContent = concern ? `⚠ ${t.flag}: share with the clinician` : `✓ ${t.flag}`;
}

// ---------- main render ----------
function render(s) {
  ensureCamera(s);
  setText("source-badge", SOURCE_LABELS[s.source_kind] || s.source_kind);
  $("source-badge").className = `badge ${s.source_kind}`;
  const hw = s.source_kind === "hardware";
  $("sim-intent").hidden = hw;
  $("hw-intent").hidden = !hw;
  $("auto-intent").checked = s.intent_auto;

  FINGERS.forEach((f, i) => {
    $(`bar-${f}`).style.width = `${(s.angles[i] / 160) * 100}%`;
    setText(`ang-${f}`, `${s.angles[i]}°`);
  });
  const [label, cls, handState] = gateState(s);
  const pill = $("gate-status");
  pill.textContent = label;
  pill.className = `pill ${cls}`;
  hand.update(s.angles, handState);
  renderControl(s);
  wave.push(s.intent_strength);
  if (wave.length > 100) wave.shift();
  drawWave();

  $("bar-intent").style.width = `${s.intent_strength * 100}%`;
  setText("intent-val", s.intent_strength.toFixed(2));
  setText("intent-label", !s.calibrated ? "Calibrating, stay relaxed…" : s.intent_active ? "Intent detected" : "Relaxed");
  $("intent-label").classList.toggle("on", s.intent_active);
  $("btn-hold").classList.toggle("active", s.intent_held);
  const t = s.touch || {};
  setText("pad-temple", t.temple ?? "—");
  setText("pad-forearm", t.forearm ?? "—");
  setText("pad-temple-d", s.calibrated ? `${(t.temple_drop * 100).toFixed(0)}% change` : "");
  setText("pad-forearm-d", s.calibrated ? `${(t.forearm_drop * 100).toFixed(0)}% change` : "");
  setText("cal-status", s.range_calibrated ? "✓ scaled to this wearer" : "using default threshold");
  const cal = s.calibration_phase;
  $("cal-overlay").hidden = !cal;
  if (cal) {
    setText("cal-word", cal === "relax" ? "RELAX" : "SQUEEZE");
    setText("cal-help", cal === "relax" ? "Sit still and let your hand go loose"
      : "Clench your jaw and squeeze your hand as hard as you can" + (s.source_kind === "hardware" ? "" : " (hold Space)"));
    setText("cal-left", Math.ceil(s.calibration_remaining_s));
    $("cal-overlay").classList.toggle("squeeze", cal === "squeeze");
  }

  setText("reps", s.reps);
  setText("activation", s.activation_rate.toFixed(0));
  setText("tremor", s.tremor_hz.toFixed(1));
  setText("tremor-src", s.source_kind === "camera" ? "from camera" : "from wristband");
  setText("tremor-amp", s.tremor_amp.toFixed(4));
  setText("steadiness", s.steadiness.toFixed(0));
  setText("latency", s.latency_ms_mean ?? "—");
  setText("latency-trials", s.latency_trials);
  setText("difficulty", s.difficulty);
  setText("comp-count", s.compensation_count);
  renderEvents(s.events);
  drawTrials(s.latencies || []);
  if (s.tapping) renderTapping(s.tapping);
  if (s.mode !== currentMode) { currentMode = s.mode; applyMode(s.mode); }

  $("cue-overlay").hidden = !s.cue_active;
  $("tap-overlay").hidden = !s.tapping_active;
  setText("tap-left", Math.ceil(s.tapping_remaining_s));
  setText("cue-status", s.cue_pending ? "get ready…" : s.cue_active ? "waiting for grip…" : "");

  const now = Date.now();
  if (now - lastSparkAt > 1000) {
    lastSparkAt = now;
    spark.push(s.activation_rate);
    if (spark.length > 60) spark.shift();
    drawSpark();
  }
}

// ---------- socket ----------
const socket = io();
socket.on("connect", () => setText("conn", "● live"));
socket.on("disconnect", () => setText("conn", "disconnected, retrying…"));
socket.on("state", render);
socket.on("event", (e) => {
  if (e.type === "cue") { $("cue-overlay").hidden = false; beep(1400, 200); }
  if (e.type === "latency") toast(`Reaction time: ${e.ms} ms`);
  if (e.type === "calibration_squeeze") beep(900, 150);
  if (e.type === "calibrated") toast(`Calibrated: temple range ${e.temple_range_pct}%, forearm ${e.forearm_range_pct}%`);
  if (e.type === "calibration_failed") toast(`Calibration failed: ${e.reason}`);
  if (e.type === "latency_miss") toast("No grip within 3 s");
  if (e.type === "tapping") { renderTapping(e); toast(e.error ? "Finger-tap test: not enough taps" : `Finger-tap test: ${e.taps} taps, ${e.flag}`); }
  if (e.type === "shoulder_hike" || e.type === "trunk_lean") {
    const pill = $("gate-status");
    pill.classList.add("flash");
    setTimeout(() => pill.classList.remove("flash"), 600);
  }
});

// ---------- controls ----------
$("mode-select").addEventListener("change", (e) => api("/api/mode", "POST", { mode: e.target.value }).catch((err) => toast(err.message)));

document.querySelectorAll("[data-control]").forEach((b) => b.addEventListener("click", () =>
  api("/api/control", "POST", { mode: b.dataset.control }).catch((err) => toast(err.message))));
document.querySelectorAll("[data-grip]").forEach((b) => b.addEventListener("click", () =>
  api("/api/control", "POST", { mode: "intent", grip: b.dataset.grip }).catch((err) => toast(err.message))));

$("btn-cal").addEventListener("click", () => api("/api/calibrate").catch((err) => toast(err.message)));

let held = false;
function setHeld(v) {
  if (v === held) return;
  held = v;
  api("/api/intent", "POST", { held: v }).catch((err) => toast(err.message));
}
const holdBtn = $("btn-hold");
holdBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); setHeld(true); });
["pointerup", "pointerleave", "pointercancel"].forEach((ev) => holdBtn.addEventListener(ev, () => setHeld(false)));
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat && !["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(document.activeElement.tagName)) {
    e.preventDefault();
    setHeld(true);
  }
});
document.addEventListener("keyup", (e) => { if (e.code === "Space") setHeld(false); });
window.addEventListener("blur", () => setHeld(false));
$("auto-intent").addEventListener("change", (e) => api("/api/intent/auto", "POST", { auto: e.target.checked }).catch((err) => toast(err.message)));

async function withStatus(statusId, btn, fn) {
  btn.disabled = true;
  setText(statusId, "working…");
  try { await fn(); setText(statusId, ""); }
  catch (err) { setText(statusId, `⚠ ${err.message}`); }
  finally { btn.disabled = false; }
}

if (role === "therapist") {
  const changeDiff = (d) => api("/api/difficulty", "POST", { level: Number($("difficulty").textContent) + d }).catch((err) => toast(err.message));
  $("diff-up").onclick = () => changeDiff(1);
  $("diff-down").onclick = () => changeDiff(-1);
  $("btn-cue").onclick = () => api("/api/latency").catch((err) => toast(err.message));
  $("btn-tap").onclick = () => api("/api/tapping", "POST", { seconds: 10 }).catch((err) => toast(err.message));
  $("btn-end").onclick = () => withStatus("agent-status", $("btn-end"), async () => {
    await api("/api/session/end");
    spark.length = 0;
    toast("Session saved");
  });

  $("btn-agent").onclick = () => withStatus("agent-status", $("btn-agent"), async () => {
    const r = await api("/api/agent");
    $("agent-out").hidden = false;
    setText("agent-summary", r.summary || "The model returned no summary.");
    setText("agent-plan", r.next_session_plan || "—");
    const ol = $("agent-trace");
    ol.replaceChildren();
    r.trace.forEach((t) => {
      const li = document.createElement("li");
      const head = document.createElement("div");
      head.className = "trace-head";
      head.textContent = `${t.tool}(${JSON.stringify(t.args)})`;
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(t.result, null, 1).slice(0, 700);
      li.append(head, pre);
      ol.append(li);
    });
    if (!r.trace.length) ol.innerHTML = '<li class="muted">The model answered without calling tools</li>';
  });

  $("btn-triage").onclick = () => withStatus("triage-status", $("btn-triage"), async () => {
    const r = await api("/api/triage", "GET");
    const tbody = $("triage-table").querySelector("tbody");
    tbody.replaceChildren();
    const icon = { urgent: "▲", watch: "●", stable: "✓" };
    r.patients.forEach((p) => {
      const tr = document.createElement("tr");
      [`${icon[p.urgency]} ${p.urgency.toUpperCase()}`, `${p.name} (${p.patient_id})`, p.condition, `${p.last_session_days_ago} d ago`, p.reason]
        .forEach((v, i) => {
          const td = document.createElement("td");
          td.textContent = v;
          if (i === 0) td.className = `urg ${p.urgency}`;
          tr.append(td);
        });
      tbody.append(tr);
    });
    $("triage-table").hidden = false;
  });
} else {
  $("btn-explain").onclick = () => withStatus("explain-status", $("btn-explain"), async () => {
    const r = await api("/api/patient_view");
    setText("explain-text", r.text);
  });
}
