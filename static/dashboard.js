import { createHand } from "./hand.js";

const $ = (id) => document.getElementById(id);
const role = document.body.dataset.role;
const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };

// ---------- conditions ----------
const CONDITIONS = {
  stroke: { title: "Stroke recovery", note: () => "Moves only while you try, with clean posture.",
    stats: ["reps", "activation", "compensation", "difficulty"] },
  parkinsons: { title: "Parkinson's", note: (s) => (s.tremor_hz > 0 ? `Tremor ${s.tremor_hz.toFixed(1)} Hz` : "No tremor detected"),
    stats: ["tremor", "steadiness", "taprate", "tapdec"], test: "tap" },
  phantom: { title: "Phantom limb", note: () => "Mirrored hand for mirror therapy.",
    stats: ["reps", "activation", "compensation", "difficulty"] },
  cp: { title: "Cerebral palsy", note: () => "Child-size hand. Joint color shows flexion.",
    stats: ["reps", "activation", "compensation", "difficulty"] },
  cognitive: { title: "Cognitive screening", note: () => "Squeeze when the screen flashes.",
    stats: ["rtMean", "rtLast", "rtTrials", "rtTrend"], test: "reaction" },
};

const tapOk = (s) => s.tapping && !s.tapping.error;
const STATS = {
  reps: ["Reps", (s) => s.reps],
  activation: ["Activation", (s) => `${s.activation_rate.toFixed(0)}%`],
  compensation: ["Compensation", (s) => s.compensation_count],
  difficulty: ["Difficulty", (s) => `${s.difficulty} / 5`],
  tremor: ["Tremor", (s) => (s.tremor_hz > 0 ? `${s.tremor_hz.toFixed(1)} Hz` : "None")],
  steadiness: ["Steadiness", (s) => `${s.steadiness.toFixed(0)} / 100`],
  taprate: ["Tap rate", (s) => (tapOk(s) ? `${s.tapping.rate_hz.toFixed(1)} /s` : "—")],
  tapdec: ["Tap decrement", (s) => (tapOk(s) ? `${s.tapping.decrement_pct.toFixed(0)}%` : "—")],
  rtMean: ["Mean reaction", (s) => (s.latency_ms_mean != null ? `${s.latency_ms_mean} ms` : "—")],
  rtLast: ["Last", (s) => (s.latencies?.length ? `${s.latencies.at(-1)} ms` : "—")],
  rtTrials: ["Trials", (s) => s.latency_trials],
  rtTrend: ["Trend", (s) => {
    const l = s.latencies || [];
    if (l.length < 4) return "—";
    const k = Math.floor(l.length / 2);
    const avg = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const d = Math.round(avg(l.slice(k)) - avg(l.slice(0, k)));
    return `${d > 0 ? "+" : ""}${d} ms`;
  }],
};

const EVENT_LABELS = {
  shoulder_hike: ["Shoulder hike", "warn"],
  trunk_lean: ["Trunk lean", "warn"],
  latency: ["Reaction", "info"],
  latency_miss: ["Reaction missed", "warn"],
  cue: ["Cue shown", "info"],
  tapping: ["Tap test done", "info"],
  calibration_squeeze: ["Calibration: squeeze", "info"],
  calibrated: ["Calibrated", "info"],
  calibration_failed: ["Calibration failed", "warn"],
  agent_alert: ["AI alert", "warn"],
};

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
  if (m.supportsWebGL()) hand = m.createHand3D($("hand3d"));
} catch (err) {
  console.warn("3D hand unavailable, using flat hand", err);
}
if (!hand) {
  $("hand3d").classList.add("flat");
  const flat = createHand($("hand3d"));
  hand = { update: (s, g) => flat.update(s.angles, g) };
}

function gateState(s) {
  if (!s.sensors_ok) return ["Sensors offline", "bad", "blocked"];
  if (!s.calibrated) return ["Calibrating", "idle", ""];
  if (s.compensation?.length) return ["Blocked: posture", "bad", "blocked"];
  if (s.control_mode === "intent") {
    if (s.gate_open) return ["Moving", "good", "open"];
    if (Math.max(...s.angles) > 0) return ["Opening", "idle", ""];
    return ["Waiting", "idle", ""];
  }
  if (s.gate_open) return ["Moving", "good", "open"];
  if (!s.curls) return ["No hand in view", "idle", ""];
  if (!s.intent_active) return ["Waiting", "idle", ""];
  return ["Holding", "idle", ""];
}

// ---------- condition + stats ----------
let currentMode = null;
function applyCondition(mode) {
  const c = CONDITIONS[mode] || CONDITIONS.stroke;
  setText("cond-title", c.title);
  document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
  const box = $("stats");
  box.replaceChildren(...c.stats.map((key) => {
    const card = document.createElement("div");
    card.className = "stat";
    card.innerHTML = `<span></span><b data-stat="${key}">—</b>`;
    card.querySelector("span").textContent = STATS[key][0];
    return card;
  }));
  if ($("test-tap")) $("test-tap").hidden = c.test !== "tap";
  if ($("test-reaction")) $("test-reaction").hidden = c.test !== "reaction";
}

// ---------- camera picture-in-picture ----------
let camStarted = false;
function renderCamera(s) {
  const show = s.source_kind !== "mock" && s.camera_ok && s.control_mode === "mirror";
  $("pip").hidden = !show || !camStarted;
  if (show && !camStarted) {
    camStarted = true;
    const img = $("cam");
    img.onload = () => { $("pip").hidden = false; };
    img.onerror = () => { camStarted = false; };
    img.src = "/video_feed";
  }
}

// ---------- intent waveform ----------
const wave = [];
const waveY = (v) => 39 - v * 38;
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

// ---------- activity ----------
let lastEventsSig = "";
function eventItem(e) {
  const [label, sev] = EVENT_LABELS[e.type] || [e.type, "info"];
  const li = document.createElement("li");
  li.className = sev;
  const time = document.createElement("time");
  time.textContent = fmtClock(e.t);
  const text = document.createElement("span");
  text.textContent = label + (e.ms !== undefined ? ` · ${e.ms} ms` : "") + (e.message ? ` · ${e.message}` : "");
  li.append(time, text);
  return li;
}
function renderEvents(events) {
  const ul = $("event-log");
  if (!ul) return;
  const shown = events.filter((e) => e.type !== "cue" && e.type !== "calibration_squeeze");
  const sig = shown.length + JSON.stringify(shown.slice(-1));
  if (sig === lastEventsSig) return;
  lastEventsSig = sig;
  const recent = [...shown].reverse();
  ul.replaceChildren(...recent.slice(0, 5).map(eventItem));
  if (!recent.length) ul.innerHTML = '<li class="muted">Nothing yet</li>';
  $("log-more").hidden = recent.length <= 5;
  $("event-log-all").replaceChildren(...recent.slice(5).map(eventItem));
}

// ---------- tap results ----------
function renderTapping(t) {
  if (!t || !$("tap-results")) return;
  $("tap-results").hidden = !!t.error;
  const flag = $("tap-flag");
  flag.hidden = false;
  if (t.error) {
    flag.className = "flag warn";
    flag.textContent = "Not enough taps. Keep the hand in view and try again.";
    return;
  }
  setText("tap-taps", t.taps);
  setText("tap-rate", `${t.rate_hz.toFixed(1)} /s`);
  setText("tap-dec", `${t.decrement_pct.toFixed(0)}%`);
  setText("tap-cv", t.rhythm_cv.toFixed(2));
  const concern = t.flag !== "within typical range";
  flag.className = `flag ${concern ? "warn" : "good"}`;
  flag.textContent = concern ? "Possible bradykinesia. Review with a clinician." : "Within typical range.";
}

// ---------- control panel ----------
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
  setText("intent-label", !s.calibrated ? "Calibrating. Stay relaxed." : s.intent_active ? "Trying" : "Relaxed");
  $("intent-label").classList.toggle("on", s.intent_active);
  wave.push(s.intent_strength);
  if (wave.length > 100) wave.shift();
  drawWave();

  const t = s.touch || {};
  setText("pad-temple", t.temple ?? "—");
  setText("pad-forearm", t.forearm ?? "—");
  setText("pad-temple-d", s.calibrated ? `${(t.temple_drop * 100).toFixed(0)}%` : "");
  setText("pad-forearm-d", s.calibrated ? `${(t.forearm_drop * 100).toFixed(0)}%` : "");
  setText("cal-status", s.range_calibrated ? "Calibrated" : "");
  setText("difficulty", s.difficulty);
}

function renderOverlays(s) {
  $("cue-overlay").hidden = !s.cue_active;
  $("tap-overlay").hidden = !s.tapping_active;
  setText("tap-left", Math.ceil(s.tapping_remaining_s));
  setText("cue-status", s.cue_pending ? "Get ready." : s.cue_active ? "Waiting for grip." : "Cue appears after 1–3 s.");
  const cal = s.calibration_phase;
  $("cal-overlay").hidden = !cal;
  if (cal) {
    const sim = s.source_kind !== "hardware";
    setText("cal-word", cal === "relax" ? "Relax" : "Squeeze");
    setText("cal-help", cal === "relax" ? "Keep still." : `Clench your jaw and squeeze hard${sim ? " (hold Space)" : ""}.`);
    setText("cal-left", Math.ceil(s.calibration_remaining_s));
    $("cal-overlay").classList.toggle("squeeze", cal === "squeeze");
  }
}

// ---------- main render ----------
function render(s) {
  if (s.mode !== currentMode) { currentMode = s.mode; applyCondition(s.mode); }
  setText("source-label", SOURCE_LABELS[s.source_kind] || s.source_kind);
  setText("cond-note", (CONDITIONS[s.mode] || CONDITIONS.stroke).note(s));

  const [label, cls, handState] = gateState(s);
  const pill = $("gate-status");
  pill.textContent = label;
  pill.className = `pill ${cls}`;
  hand.update(s, handState);

  renderCamera(s);
  renderControl(s);
  renderOverlays(s);
  document.querySelectorAll("[data-stat]").forEach((el) => { el.textContent = STATS[el.dataset.stat][1](s); });
  renderEvents(s.events);
  drawTrials(s.latencies || []);
  if (s.tapping) renderTapping(s.tapping);
}

// ---------- socket ----------
const socket = io();
socket.on("connect", () => $("conn-dot").classList.add("live"));
socket.on("disconnect", () => { $("conn-dot").classList.remove("live"); setText("source-label", "Reconnecting"); });
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
const fail = (err) => toast(err.message);
document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => api("/api/mode", "POST", { mode: b.dataset.mode }).catch(fail)));
document.querySelectorAll("[data-control]").forEach((b) => b.addEventListener("click", () => api("/api/control", "POST", { mode: b.dataset.control }).catch(fail)));
document.querySelectorAll("[data-grip]").forEach((b) => b.addEventListener("click", () => api("/api/control", "POST", { mode: "intent", grip: b.dataset.grip }).catch(fail)));
$("btn-cal").addEventListener("click", () => api("/api/calibrate").catch(fail));
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
  if (e.code === "Space" && !e.repeat && !["INPUT", "SELECT", "TEXTAREA", "BUTTON", "SUMMARY"].includes(document.activeElement.tagName)) {
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
  const review = () => busy($("btn-agent"), "agent-status", async () => {
    const r = await api("/api/agent");
    $("agent-out").hidden = false;
    setText("agent-summary", r.summary || "No summary returned.");
    setText("agent-plan", r.next_session_plan || "—");
    setText("trace-summary", `Agent steps (${r.trace.length})`);
    $("agent-trace").replaceChildren(...r.trace.map((t) => {
      const li = document.createElement("li");
      if (t.reasoning) {
        const why = document.createElement("p");
        why.className = "why";
        why.textContent = t.reasoning;
        li.append(why);
      }
      const head = document.createElement("code");
      head.textContent = `${t.tool}(${Object.keys(t.args).length ? JSON.stringify(t.args) : ""})`;
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(t.result, null, 1).slice(0, 600);
      li.append(head, pre);
      return li;
    }));
  });

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
  });
} else {
  $("btn-explain").onclick = () => busy($("btn-explain"), "explain-status", async () => {
    const r = await api("/api/patient_view");
    setText("explain-text", r.text);
  });
}
