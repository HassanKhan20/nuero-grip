// AI reasoning page (NVIDIA track): Nemotron's tool chain on the live session, step by step, then the next steps.
import { $, api, el, initShell } from "./common.js";

initShell();

const CONDITION = { stroke: "Stroke", parkinsons: "Parkinson's", phantom: "Phantom limb", cp: "Cerebral palsy", cognitive: "Cognitive" };
const TOOLS = [
  ["get_session_metrics", "Read the live session", "Reps, activation, tremor, reaction times, difficulty"],
  ["get_patient_history", "Read past sessions", "Earlier sessions for this patient, from MongoDB"],
  ["get_open_incidents", "Check the detectors", "Active incidents from the command center"],
  ["set_difficulty", "Change difficulty", "Moves the intent threshold on the device (1–5)"],
  ["trigger_feedback", "Cue the patient", "Celebration or alert on the device and dashboard"],
  ["open_incident", "Escalate", "Opens an incident on the command center"],
];
const mmss = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.round((s || 0) % 60)).padStart(2, "0")}`;
const when = (t) => new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

// what each tool call means, in plain words: [title, what came back]
const DESCRIBE = {
  get_session_metrics: (a, r) => ["Read this session",
    `${r.reps ?? 0} reps · ${Math.round(r.activation_rate ?? 0)}% activation · ${mmss(r.session_s)} long · difficulty ${r.difficulty ?? "—"}`
    + (r.tremor_hz ? ` · tremor ${Number(r.tremor_hz).toFixed(1)} Hz` : "")],
  get_patient_history: (a, r) => ["Compared with past sessions",
    Array.isArray(r) ? (r.length ? `${r.length} previous session${r.length > 1 ? "s" : ""} on record` : "No previous sessions on record") : ""],
  get_open_incidents: (a, r) => ["Checked the live detections",
    Array.isArray(r) ? (r.length ? r.map((i) => `${i.id} ${i.title} (${i.severity})`).join(" · ") : "No active incidents") : ""],
  set_difficulty: (a, r, ctx) => {
    const to = r.level ?? a.level;
    const from = ctx.before;
    ctx.after = to;
    const title = from == null || from === to ? `Kept difficulty at ${to}` : `${to < from ? "Lowered" : "Raised"} difficulty from ${from} to ${to}`;
    return [title, a.reason || r.reason || ""];
  },
  trigger_feedback: (a) => [a.kind === "celebrate" ? "Sent a celebration cue" : "Sent an alert", a.message || ""],
  open_incident: (a, r) => [`Escalated: ${a.title || "incident"}`, r.id ? `${r.id} opened as ${r.severity} on the command center` : ""],
};

let runs = [];
let shownId = null;

function argText(args) {
  const parts = Object.entries(args || {}).filter(([k]) => k !== "reason" && k !== "detail" && k !== "message")
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return parts.join(", ");
}

function show(run) {
  shownId = run.id;
  const metrics = run.trace.find((t) => t.tool === "get_session_metrics" && !t.result?.error)?.result || {};
  const ctx = { before: metrics.difficulty ?? run.context?.difficulty ?? null, after: null };
  const steps = run.trace.map((t) => {
    const fn = DESCRIBE[t.tool];
    const [title, detail] = t.result?.error ? [`${t.tool} failed`, t.result.error] : fn ? fn(t.args || {}, t.result || {}, ctx) : [t.tool, ""];
    return { ...t, title, detail };
  });
  const after = ctx.after ?? ctx.before;

  $("rs-empty").hidden = true;
  $("rs-view").hidden = false;
  const c = run.context || {};
  $("rs-meta").textContent = `Review #${run.id} · patient ${c.patient_id || "demo"} · ${CONDITION[c.mode] || c.mode || ""} · ${when(run.at)} · ${run.seconds ?? "?"} s · ${steps.length} tool call${steps.length === 1 ? "" : "s"}`;
  $("rs-status").textContent = `Showing review #${run.id}`;

  const kpi = (label, value) => { const d = el("div", "kpi"); d.append(el("span", "", label), el("b", "", value)); return d; };
  $("rs-kpis").replaceChildren(
    kpi("Reps", metrics.reps ?? "—"),
    kpi("Activation", metrics.activation_rate != null ? `${Math.round(metrics.activation_rate)}%` : "—"),
    kpi("Session", mmss(metrics.session_s ?? c.session_s)),
    kpi("Difficulty", ctx.before != null && after !== ctx.before ? `${ctx.before} → ${after}` : `${after ?? "—"}`),
    kpi("Tool calls", steps.length),
  );

  $("rs-steps").replaceChildren(...steps.map((st, n) => {
    const li = el("li", `step${st.result?.error ? " failed" : ""}`);
    li.append(el("span", "step-n", n + 1));
    const body = el("div", "step-body");
    const head = el("div", "step-head");
    head.append(el("b", "", st.title), el("code", "", `${st.tool}(${argText(st.args)})`));
    body.append(head);
    if (st.reasoning) {
      const why = el("p", "why clamp", st.reasoning.replace(/\*\*|__|^#+\s*/gm, ""));
      why.title = "Click to expand";
      why.onclick = () => why.classList.toggle("clamp");
      const lab = el("span", "why-label", "Why");
      body.append(lab, why);
    }
    if (st.detail) body.append(el("p", "result", st.detail));
    li.append(body);
    return li;
  }));
  if (!steps.length) $("rs-steps").replaceChildren(el("li", "step", "Answered without calling any tools."));

  $("rs-summary").textContent = run.summary || "No summary returned.";

  // next steps: the plan, then every action the agent took that someone should follow up
  const next = [];
  if (run.next_session_plan) next.push(["Next session", run.next_session_plan]);
  steps.filter((s) => s.tool === "set_difficulty" && !s.result?.error).forEach((s) => next.push(["Device", s.title]));
  steps.filter((s) => s.tool === "open_incident" && s.result?.id).forEach((s) => next.push(["Respond", `${s.result.id}: ${s.args.title}`, "/command"]));
  const seen = steps.find((s) => s.tool === "get_open_incidents" && Array.isArray(s.result) && s.result.length);
  if (seen) next.push(["Respond", `${seen.result.length} active incident${seen.result.length > 1 ? "s" : ""} to work in the command center`, "/command"]);
  next.push(["Sign off", "Therapist reviews this plan before the next session"]);
  $("rs-next").replaceChildren(...next.map(([tag, text, href]) => {
    const li = el("li");
    li.append(el("span", "next-tag", tag));
    if (href) { const a = el("a", "", text); a.href = href; li.append(a); } else li.append(el("span", "", text));
    return li;
  }));

  const used = new Map();
  run.trace.forEach((t) => used.set(t.tool, (used.get(t.tool) || 0) + 1));
  renderTools(used);
  renderHistory();
}

function renderTools(used = new Map()) {
  $("rs-tools").replaceChildren(...TOOLS.map(([name, label, desc]) => {
    const li = el("li", used.get(name) ? "used" : "");
    const top = el("div", "tool-top");
    top.append(el("b", "", label), el("small", "", used.get(name) ? `used ×${used.get(name)}` : ""));
    li.append(top, el("code", "", name), el("p", "sub", desc));
    return li;
  }));
}

function renderHistory() {
  if (!runs.length) return;
  $("rs-history").replaceChildren(...runs.map((r) => {
    const li = el("li", r.id === shownId ? "on" : "");
    li.tabIndex = 0;
    li.append(el("b", "", `Review #${r.id}`), el("small", "", `${when(r.at)} · ${r.trace.length} steps`));
    li.onclick = () => show(r);
    li.onkeydown = (e) => { if (e.key === "Enter") show(r); };
    return li;
  }));
}

async function run() {
  const btn = $("btn-run");
  btn.disabled = true;
  const t0 = Date.now();
  const tick = () => { $("rs-status").textContent = `Nemotron is working through its tools… ${Math.round((Date.now() - t0) / 1000)} s (usually about 15 s)`; };
  tick();
  const timer = setInterval(tick, 1000);
  try {
    const r = await api("/api/agent");
    runs.unshift(r);
    show(r);
  } catch (err) {
    $("rs-status").textContent = err.message;
  } finally {
    clearInterval(timer);
    btn.disabled = false;
  }
}

$("btn-run").onclick = run;
renderTools();
api("/api/agent/runs", "GET").then((r) => {
  runs = r.runs;
  if (runs.length) show(runs[0]);
}).catch(() => {}).finally(() => {
  const params = new URLSearchParams(location.search);
  if (params.get("run") === "1") {
    history.replaceState(null, "", location.pathname); // a refresh shouldn't start another review
    run();
  }
});
