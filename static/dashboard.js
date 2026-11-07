const $ = (id) => document.getElementById(id);
const role = document.body.dataset.role;

const MODE_INFO = {
  stroke: { title: "Stroke Recovery", highlight: ["grip", "activation", "compensation"] },
  parkinsons: { title: "Parkinson's Monitoring", highlight: ["tremor", "steadiness", "latency"] },
  phantom: { title: "Phantom Limb Mirror Therapy", highlight: ["grip", "activation", "reps"] },
  cp: { title: "Pediatric Cerebral Palsy", highlight: ["grip", "reps", "compensation", "difficulty"] },
  cognitive: { title: "Cognitive Decline Screening", highlight: ["latency", "activation"] },
};

const EVENT_LABELS = {
  shoulder_hike: ["Shoulder hike (compensation)", "warn"],
  trunk_lean: ["Trunk lean (compensation)", "warn"],
  latency: ["Reaction time", "info"],
  latency_miss: ["Reaction test missed (>3 s)", "warn"],
};

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

function setText(id, v) { const el = $(id); if (el) el.textContent = v; }

function fmtClock(ms) {
  const s = Math.floor(ms / 1000);
  return `T+${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function applyMode(mode) {
  const info = MODE_INFO[mode] || MODE_INFO.stroke;
  setText("mode-title", info.title);
  $("mode-select").value = mode;
  document.querySelectorAll("[data-metric]").forEach((el) => {
    el.classList.toggle("highlight", info.highlight.includes(el.dataset.metric));
  });
}

function gateLabel(s) {
  if (!s.sensors_ok) return ["Sensors offline", "bad"];
  if (!s.calibrated) return ["Calibrating", "idle"];
  if (s.compensation && s.compensation.length) return ["Blocked: posture", "bad"];
  if (s.gate_open) return ["Gate open", "good"];
  if (!s.curls) return ["No hand in view", "idle"];
  if (!s.intent_active) return ["Waiting for intent", "idle"];
  return ["Waiting for target", "idle"];
}

const spark = [];
let lastSparkAt = 0;
let lastEventsSig = "";
let currentMode = null;

function renderEvents(events) {
  const sig = JSON.stringify(events.slice(-1)) + events.length;
  if (sig === lastEventsSig || !$("event-log")) return;
  lastEventsSig = sig;
  const ul = $("event-log");
  ul.innerHTML = "";
  if (!events.length) { ul.innerHTML = '<li class="muted">No incidents yet</li>'; return; }
  [...events].reverse().forEach((e) => {
    const [label, sev] = EVENT_LABELS[e.type] || [e.type, "info"];
    const li = document.createElement("li");
    li.className = sev;
    li.innerHTML = `<time>${fmtClock(e.t)}</time><span class="sev">${sev === "warn" ? "WARN" : "INFO"}</span>`;
    li.append(label + (e.ms !== undefined ? `: ${e.ms} ms` : ""));
    ul.append(li);
  });
}

function render(s) {
  ["thumb", "index", "rest"].forEach((f, i) => {
    $(`bar-${f}`).style.width = `${(s.angles[i] / 160) * 100}%`;
    setText(`ang-${f}`, `${s.angles[i]}°`);
  });
  $("bar-intent").style.width = `${s.intent_strength * 100}%`;
  setText("intent-val", s.intent_strength.toFixed(2));
  const [label, cls] = gateLabel(s);
  const pill = $("gate-status");
  pill.textContent = label;
  pill.className = `pill ${cls}`;

  setText("reps", s.reps);
  setText("activation", s.activation_rate.toFixed(0));
  setText("tremor", s.tremor_hz.toFixed(1));
  setText("steadiness", s.steadiness.toFixed(0));
  setText("latency", s.latency_ms_mean ?? "—");
  setText("latency-trials", s.latency_trials);
  setText("difficulty", s.difficulty);
  setText("comp-count", s.compensation_count);
  renderEvents(s.events);
  if (s.mode !== currentMode) { currentMode = s.mode; applyMode(s.mode); }

  const now = Date.now();
  if (now - lastSparkAt > 1000) {
    lastSparkAt = now;
    spark.push(s.activation_rate);
    if (spark.length > 60) spark.shift();
    const pts = spark.map((v, i) => `${(i / 59) * 120},${30 - (v / 100) * 28 - 1}`).join(" ");
    $("spark-line").setAttribute("points", pts);
  }
}

const socket = io();
socket.on("connect", () => setText("conn", "live"));
socket.on("disconnect", () => setText("conn", "disconnected: retrying…"));
socket.on("state", render);
socket.on("event", (e) => {
  if (e.type === "shoulder_hike" || e.type === "trunk_lean") {
    const pill = $("gate-status");
    pill.classList.add("flash");
    setTimeout(() => pill.classList.remove("flash"), 600);
  }
});

$("mode-select").addEventListener("change", (e) => api("/api/mode", "POST", { mode: e.target.value }).catch(alert));

async function withStatus(statusId, btn, fn) {
  btn.disabled = true;
  setText(statusId, "working…");
  try { await fn(); setText(statusId, ""); }
  catch (err) { setText(statusId, `⚠ ${err.message}`); }
  finally { btn.disabled = false; }
}

if (role === "therapist") {
  const changeDiff = (d) => api("/api/difficulty", "POST", { level: Number($("difficulty").textContent) + d }).catch(alert);
  $("diff-up").onclick = () => changeDiff(1);
  $("diff-down").onclick = () => changeDiff(-1);
  $("btn-cue").onclick = () => api("/api/latency").catch(alert);
  $("btn-end").onclick = () => withStatus("agent-status", $("btn-end"), async () => {
    await api("/api/session/end");
    spark.length = 0;
  });

  $("btn-agent").onclick = () => withStatus("agent-status", $("btn-agent"), async () => {
    const r = await api("/api/agent");
    $("agent-out").hidden = false;
    setText("agent-summary", r.summary);
    setText("agent-plan", r.next_session_plan || "—");
    const ol = $("agent-trace");
    ol.innerHTML = "";
    r.trace.forEach((t) => {
      const li = document.createElement("li");
      const head = document.createElement("div");
      head.className = "trace-head";
      head.textContent = `${t.tool}(${JSON.stringify(t.args)})`;
      const pre = document.createElement("pre");
      pre.textContent = JSON.stringify(t.result, null, 1).slice(0, 600);
      li.append(head, pre);
      ol.append(li);
    });
    if (!r.trace.length) ol.innerHTML = '<li class="muted">The model answered without calling tools</li>';
  });

  $("btn-triage").onclick = () => withStatus("triage-status", $("btn-triage"), async () => {
    const r = await api("/api/triage", "GET");
    const tbody = $("triage-table").querySelector("tbody");
    tbody.innerHTML = "";
    r.patients.forEach((p) => {
      const tr = document.createElement("tr");
      [p.urgency.toUpperCase(), `${p.name} (${p.patient_id})`, p.condition, `${p.last_session_days_ago} d ago`, p.reason]
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
