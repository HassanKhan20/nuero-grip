// AI reasoning page (NVIDIA track): what Nemotron concluded, what to do next, and each tool it used to get there.
import { $, api, el, initShell } from "./common.js";

initShell();

const mmss = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.round((s || 0) % 60)).padStart(2, "0")}`;
const when = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

// each tool call in plain words: [what it did, what came back]
const DESCRIBE = {
  get_session_metrics: (a, r) => ["Read this session",
    `${r.reps ?? 0} reps, ${Math.round(r.activation_rate ?? 0)}% activation, ${mmss(r.session_s)} long, difficulty ${r.difficulty ?? "?"}`
    + (r.tremor_hz ? `, tremor ${Number(r.tremor_hz).toFixed(1)} Hz` : "")],
  get_patient_history: (a, r) => ["Looked at past sessions",
    Array.isArray(r) ? (r.length ? `${r.length} earlier session${r.length > 1 ? "s" : ""}` : "No earlier sessions") : ""],
  get_open_incidents: (a, r) => ["Checked for alerts",
    Array.isArray(r) ? (r.length ? r.map((i) => i.title).join(", ") : "No open alerts") : ""],
  set_difficulty: (a, r, ctx) => {
    const to = r.level ?? a.level;
    const from = ctx.before;
    ctx.after = to;
    const title = from == null || from === to ? `Kept difficulty at ${to}` : `${to < from ? "Lowered" : "Raised"} difficulty from ${from} to ${to}`;
    return [title, a.reason || r.reason || ""];
  },
  trigger_feedback: (a) => [a.kind === "celebrate" ? "Cheered the patient on" : "Sent the patient an alert", a.message || ""],
  open_incident: (a, r) => [`Raised an alert: ${a.title || "incident"}`, r.id ? "Sent to the command center" : ""],
};

let runs = [];

function describe(run) {
  const metrics = run.trace.find((t) => t.tool === "get_session_metrics" && !t.result?.error)?.result || {};
  const ctx = { before: metrics.difficulty ?? run.context?.difficulty ?? null, after: null };
  return run.trace.map((t) => {
    const fn = DESCRIBE[t.tool];
    const [title, detail] = t.result?.error ? ["A tool call failed", t.result.error] : fn ? fn(t.args || {}, t.result || {}, ctx) : [t.tool, ""];
    return { ...t, title, detail };
  });
}

function show(run) {
  const steps = describe(run);
  $("rs-empty").hidden = true;
  $("rs-view").hidden = false;
  $("rs-summary").textContent = run.summary || "No summary returned.";

  const next = [];
  if (run.next_session_plan) next.push([run.next_session_plan]);
  const changed = steps.filter((s) => s.tool === "set_difficulty" && !s.result?.error && !s.title.startsWith("Kept")).pop();
  if (changed) next.push([`${changed.title} (already applied to the device)`]);
  const alerts = steps.filter((s) => s.tool === "open_incident" && s.result?.id).length
    + (steps.find((s) => s.tool === "get_open_incidents" && Array.isArray(s.result))?.result.length || 0);
  if (alerts) next.push([`Handle ${alerts} alert${alerts > 1 ? "s" : ""} in the command center`, "/command"]);
  next.push(["Therapist checks this plan before the next session"]);
  $("rs-next").replaceChildren(...next.map(([text, href]) => {
    const li = el("li");
    if (href) { const a = el("a", "", text); a.href = href; li.append(a); } else li.textContent = text;
    return li;
  }));

  $("rs-steps-h").textContent = `What Nemotron did (${steps.length} step${steps.length === 1 ? "" : "s"})`;
  $("rs-steps").replaceChildren(...steps.map((st, n) => {
    const li = el("li", `step${st.result?.error ? " failed" : ""}`);
    const body = el("div", "step-body");
    body.append(el("b", "", st.title));
    if (st.detail) body.append(el("p", "", st.detail));
    if (st.reasoning) {
      const why = el("p", "why", st.reasoning.replace(/\*\*|__|^#+\s*/gm, ""));
      why.hidden = true;
      const btn = el("button", "btn link why-btn", "Why?");
      btn.type = "button";
      btn.onclick = () => { why.hidden = !why.hidden; btn.textContent = why.hidden ? "Why?" : "Hide"; };
      body.append(btn, why);
    }
    li.append(el("span", "step-n", n + 1), body);
    return li;
  }));
  if (!steps.length) $("rs-steps").replaceChildren(el("li", "", "It answered without using any tools."));

  const pick = $("rs-history");
  pick.hidden = runs.length < 2;
  pick.replaceChildren(...runs.map((r) => {
    const o = el("option", "", `Review #${r.id}, ${when(r.at)}`);
    o.value = r.id;
    return o;
  }));
  pick.value = run.id;
}

function status(text) {
  $("rs-status").hidden = !text;
  $("rs-status").textContent = text || "";
}

async function run() {
  const btn = $("btn-run");
  btn.disabled = true;
  const t0 = Date.now();
  const tick = () => status(`Nemotron is working… ${Math.round((Date.now() - t0) / 1000)} s (about 15 s)`);
  tick();
  const timer = setInterval(tick, 1000);
  try {
    const r = await api("/api/agent");
    runs.unshift(r);
    status("");
    show(r);
  } catch (err) {
    status(err.message);
  } finally {
    clearInterval(timer);
    btn.disabled = false;
  }
}

$("btn-run").onclick = run;
$("rs-history").onchange = (e) => { const r = runs.find((x) => String(x.id) === e.target.value); if (r) show(r); };
api("/api/agent/runs", "GET").then((r) => {
  runs = r.runs;
  if (runs.length) show(runs[0]);
}).catch(() => {}).finally(() => {
  if (new URLSearchParams(location.search).get("run") === "1") {
    history.replaceState(null, "", location.pathname); // a refresh shouldn't start another review
    run();
  }
});
