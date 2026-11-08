// Command center (incidents, detectors, audit log) and regional surge triage. Full pages, therapist only.
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};
const fmtNum = (n) => Number(n).toLocaleString();
const ago = (t) => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
};
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const CONDITION = { stroke: "Stroke", parkinsons: "Parkinson's", phantom: "Phantom limb", cp: "Cerebral palsy", cognitive: "Cognitive" };
const SEV = { low: "Low", medium: "Medium", high: "High", critical: "Critical" };
const STATUS = { open: "Open", acknowledged: "Acknowledged", resolved: "Resolved" };
const CAT = { clinical: "Clinical", device: "Device", security: "Security", caseload: "Caseload" };
const ACTIONS = {
  login: "Signed in", logout: "Signed out", login_failed: "Failed sign-in", login_blocked: "Blocked (lockout)",
  denied: "Access denied", agent_review: "AI session review", triage_brief: "AI coordination brief",
  incident_declared: "Declared incident", incident_ack: "Acknowledged", incident_assign: "Assigned",
  incident_note: "Note", intent_zero: "Re-zeroed intent", incident_resolve: "Resolved", incident_reopen: "Reopened", incident_scope: "Scope changed",
};

// every detection rule that can open an incident (kinds match neurogrip/detect.py and app.py)
const DETECTORS = [
  ["sensor_loss", "Sensor stream lost", "Device"], ["camera_loss", "Camera offline", "Device"],
  ["tremor", "Tremor 3.5–7.5 Hz", "Clinical"], ["slow_reaction", "Slow reaction", "Clinical"],
  ["missed_cues", "Missed cues", "Clinical"], ["bradykinesia", "Finger-tap slowdown", "Clinical"],
  ["failed_logins", "Repeated failed sign-ins", "Security"], ["access_denied", "Unauthorized access", "Security"],
  ["capacity_gap", "Capacity gap", "Caseload"], ["agent:", "AI escalation", "Nemotron"],
];

function kpis(container, items) {
  container.replaceChildren(...items.map(([label, value, tone]) => {
    const d = el("div", `kpi ${tone || ""}`);
    d.append(el("span", "", label), el("b", "", value));
    return d;
  }));
}

export function initCommandCenter({ api, toast, socket }) {
  const byId = new Map();
  let filter = "active";
  let selected = null;

  const active = (i) => i.status !== "resolved";

  function renderDetectors() {
    const ul = $("cc-detectors");
    if (!ul) return;
    const all = [...byId.values()];
    ul.replaceChildren(...DETECTORS.map(([kind, label, group]) => {
      const hits = all.filter((i) => active(i) && (kind.endsWith(":") ? i.kind.startsWith(kind) : i.kind === kind));
      const worst = ["critical", "high", "medium", "low"].find((s) => hits.some((i) => i.severity === s));
      const li = el("li", hits.length ? `firing sev-${worst}` : "");
      li.append(el("span", "det-dot"), el("b", "", label), el("small", "", hits.length ? `${group} · ${hits.length} active` : `${group} · watching`));
      if (hits.length) { li.tabIndex = 0; li.onclick = () => { selected = hits[0].id; renderList(); renderDetail(); }; }
      return li;
    }));
  }

  function renderKpis() {
    const all = [...byId.values()];
    const n = (f) => all.filter(f).length;
    kpis($("cc-kpis"), [
      ["Open", n((i) => i.status === "open"), n((i) => i.status === "open") ? "warn" : ""],
      ["Acknowledged", n((i) => i.status === "acknowledged")],
      ["Critical / high active", n((i) => active(i) && (i.severity === "critical" || i.severity === "high")),
        n((i) => active(i) && (i.severity === "critical" || i.severity === "high")) ? "bad" : ""],
      ["Resolved", n((i) => i.status === "resolved"), "good"],
    ]);
  }

  function renderList() {
    const rows = [...byId.values()]
      .filter((i) => filter === "all" || (filter === "active" ? active(i) : i.status === "resolved"))
      .sort((a, b) => b.updated - a.updated);
    const ul = $("cc-list");
    if (!rows.length) {
      ul.replaceChildren(el("li", "empty", filter === "active" ? "No active incidents. Detections run every second." : "Nothing here yet"));
      return;
    }
    ul.replaceChildren(...rows.map((i) => {
      const li = el("li", `sev-${i.severity} ${i.status}${i.id === selected ? " on" : ""}`);
      li.tabIndex = 0;
      const top = el("div", "cc-row");
      top.append(el("span", "cc-sev", SEV[i.severity]), el("span", "cc-title", i.title));
      const meta = el("small", "", `${i.id} · ${CAT[i.category] || i.category} · ${STATUS[i.status]} · ${ago(i.updated)}${i.count > 1 ? ` · seen ${i.count}×` : ""}`);
      li.append(top, meta);
      li.onclick = () => { selected = i.id; renderList(); renderDetail(); };
      li.onkeydown = (e) => { if (e.key === "Enter") li.onclick(); };
      return li;
    }));
  }

  async function act(action, body) {
    try {
      const inc = await api(`/api/incidents/${selected}/${action}`, "POST", body);
      upsert(inc);
    } catch (err) { toast(err.message); }
  }

  function renderDetail() {
    const box = $("cc-detail");
    const i = byId.get(selected);
    if (!i) { box.replaceChildren(el("p", "sub", "Select an incident to see its timeline.")); return; }
    const head = el("header", "cc-dhead");
    const h = el("h3", "", i.title);
    const pills = el("div", "btn-row");
    pills.append(el("span", `pill sev-${i.severity}`, SEV[i.severity]), el("span", `pill st-${i.status}`, STATUS[i.status]),
      el("span", "pill", CAT[i.category] || i.category));
    head.append(h, pills);

    const facts = el("dl", "cc-facts");
    const add = (k, v) => { facts.append(el("dt", "", k), el("dd", "", v)); };
    add("Incident", i.id);
    add("Owner", i.owner || "Unassigned");
    add("Scope", Object.entries(i.scope || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—");
    add("Detected", `${clock(i.created)} (${ago(i.created)})`);
    add("Detail", i.detail);

    const actions = el("div", "btn-row no-print");
    const btn = (label, cls, fn) => { const b = el("button", `btn ${cls}`, label); b.type = "button"; b.onclick = fn; actions.append(b); };
    if (i.status === "open") btn("Acknowledge", "primary", () => act("ack"));
    if (i.status !== "resolved" && i.owner !== "therapist") btn("Assign to me", "ghost", () => act("assign", { owner: "therapist" }));
    if (i.status !== "resolved") btn("Resolve", "ghost", () => {
      const note = $("cc-note").value.trim();
      act("resolve", { text: note || "Resolved" });
      $("cc-note").value = "";
    });
    else btn("Reopen", "ghost", () => act("reopen"));

    const tl = el("ol", "cc-timeline");
    i.timeline.forEach((e) => {
      const li = el("li", `tl-${e.kind}`);
      li.append(el("span", "tl-time", clock(e.t)), el("b", "", e.actor), el("p", "", e.text));
      tl.append(li);
    });

    const form = el("form", "cc-compose no-print");
    form.innerHTML = `<input id="cc-note" placeholder="Message the response team (everyone sees it live)" maxlength="500" autocomplete="off"><button type="submit" class="btn primary">Send</button>`;
    form.onsubmit = (e) => {
      e.preventDefault();
      const text = $("cc-note").value.trim();
      if (!text) return;
      $("cc-note").value = "";
      act("note", { text });
    };
    box.replaceChildren(head, facts, actions, el("h4", "", "Timeline"), tl, form);
    tl.scrollTop = tl.scrollHeight;
  }

  function upsert(inc) {  // new-incident toasts and the nav badge come from the shell (common.js)
    byId.set(inc.id, inc);
    if (!selected) selected = inc.id;
    renderKpis(); renderDetectors(); renderList();
    if (inc.id === selected) {
      const typing = document.activeElement?.id === "cc-note" ? $("cc-note").value : null;
      renderDetail();
      if (typing !== null) { $("cc-note").value = typing; $("cc-note").focus(); }
    }
  }

  async function loadIncidents() {
    try {
      const r = await api("/api/incidents", "GET");
      r.incidents.forEach((i) => byId.set(i.id, i));
      if (!selected) selected = r.incidents.find(active)?.id || r.incidents[0]?.id || null;
      renderKpis(); renderDetectors(); renderList(); renderDetail();
    } catch (err) { toast(err.message); }
  }

  async function loadAudit() {
    try {
      const r = await api("/api/audit", "GET");
      $("cc-audit-table").querySelector("tbody").replaceChildren(...r.audit.map(auditRow));
    } catch (err) { toast(err.message); }
  }
  function auditRow(a) {
    const tr = el("tr", ["denied", "login_failed", "login_blocked"].includes(a.action) ? "flagged" : "");
    [clock(a.t), a.actor, ACTIONS[a.action] || a.action, a.detail, a.ip].forEach((v) => tr.append(el("td", "", v)));
    return tr;
  }

  document.querySelectorAll("#cc-tabs [data-cc]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#cc-tabs [data-cc]").forEach((x) => x.classList.toggle("on", x === b));
    const audit = b.dataset.cc === "audit";
    $("cc-incidents").hidden = audit;
    $("cc-audit").hidden = !audit;
    $("cc-filter").style.visibility = audit ? "hidden" : "";
    if (audit) loadAudit();
  }));
  document.querySelectorAll("#cc-filter [data-status]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#cc-filter [data-status]").forEach((x) => x.classList.toggle("on", x === b));
    filter = b.dataset.status;
    renderList();
  }));
  $("cc-declare-btn").onclick = () => { $("cc-declare").hidden = false; $("cc-declare-btn").hidden = true; $("cc-declare").elements.title.focus(); };
  const closeDeclare = () => { $("cc-declare").hidden = true; $("cc-declare-btn").hidden = false; $("cc-declare").reset(); };
  $("cc-declare-cancel").onclick = closeDeclare;
  $("cc-declare").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const inc = await api("/api/incidents", "POST", Object.fromEntries(f));
      selected = inc.id;
      upsert(inc);
      closeDeclare();
      renderList(); renderDetail();
    } catch (err) { toast(err.message); }
  };

  socket.on("incident", upsert);
  socket.on("audit", (a) => {
    if (!$("cc-audit").hidden) $("cc-audit-table").querySelector("tbody").prepend(auditRow(a));
  });
  setInterval(renderList, 15000); // keep "x min ago" fresh
  loadIncidents();
}

export function initSurge({ api, toast }) {
  let urg = "urgent";
  let data = null;

  function bars(container, rows) {
    const max = Math.max(1, ...rows.map((r) => r.max ?? r.value));
    container.replaceChildren(...rows.map((r) => {
      const row = el("div", "bar-row");
      const track = el("div", "bar-track");
      const fill = el("div", `bar-fill ${r.tone || ""}`);
      fill.style.width = `${(100 * r.value) / max}%`;
      track.append(fill);
      row.title = r.title || "";
      row.append(el("span", "bar-label", r.label), track, el("span", "bar-val", r.text));
      return row;
    }));
  }

  function render() {
    const s = data.summary;
    kpis($("surge-kpis"), [
      ["Patients scored", fmtNum(s.total)],
      ["Urgent", fmtNum(s.urgent), "bad"],
      ["Therapist slots", `${fmtNum(s.assigned)} / ${fmtNum(s.capacity)}`],
      ["Urgent with a therapist", `${s.urgent_coverage_pct}%`, s.urgent_coverage_pct < 100 ? "warn" : "good"],
      ["Urgent on waitlist", fmtNum(s.unassigned_urgent), s.unassigned_urgent ? "bad" : "good"],
    ]);
    const regions = Object.entries(s.by_region).sort((a, b) => b[1].urgent - a[1].urgent);
    bars($("surge-regions"), regions.map(([name, v]) => ({
      label: name, value: v.urgent, text: `${v.urgent} urgent · ${v.waitlist} waiting`, tone: "bad",
      title: `${v.total} patients in ${name}`,
    })));
    bars($("surge-load"), data.therapists.map((t) => ({
      label: t.name, value: t.assigned, max: t.capacity, text: `${t.assigned} / ${t.capacity}`,
      tone: t.assigned >= t.capacity ? "warn" : "",
    })));
    if (data.brief) { $("surge-brief").textContent = data.brief; $("surge-brief-box").hidden = false; $("btn-brief").textContent = "Rewrite the plan"; }

    const labels = { urgent: "Urgent", monitor: "Monitor", stable: "Stable" };
    const tbody = $("surge-table").querySelector("tbody");
    tbody.replaceChildren(...data.patients.map((p) => {
      const tr = el("tr");
      const care = p.assigned_to || (p.care === "waitlist" ? "Waitlist" : "Home program");
      const cells = [labels[p.urgency], p.risk, p.name, p.region, CONDITION[p.condition] || p.condition, p.ai_reason || p.reason, care];
      cells.forEach((v, i) => {
        const td = el("td", "", v);
        if (i === 2) { td.className = "who"; td.append(el("small", "", p.patient_id)); }
        if (i === 0) td.className = `urg ${p.urgency}`;
        if (i === 1) td.className = "num";
        if (i === 5 && p.ai_reason) td.classList.add("ai");
        if (i === 6) td.className = `care ${p.care.replace(" ", "-")}`;
        tr.append(td);
      });
      return tr;
    }));
    const shown = data.patients.length;
    const tierTotal = urg ? s[urg] : s.total;
    $("surge-more").textContent = shown < tierTotal ? `Showing the top ${shown} of ${fmtNum(tierTotal)} by risk. Everyone is scored; export or filter to see the rest.` : `${fmtNum(shown)} patients.`;
    $("caseload-meta").textContent = `Regional surge triage · ${fmtNum(s.total)} patients · ${new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
  }

  async function load() {
    try {
      $("surge-status").textContent = "Scoring…";
      data = await api(`/api/triage/population?limit=150&urgency=${urg}`, "GET");
      $("surge-status").textContent = "";
      render();
    } catch (err) { $("surge-status").textContent = err.message; }
  }

  document.querySelectorAll("#surge-filter [data-urg]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#surge-filter [data-urg]").forEach((x) => x.classList.toggle("on", x === b));
    urg = b.dataset.urg;
    load();
  }));
  document.querySelectorAll("#tri-tabs [data-tri]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#tri-tabs [data-tri]").forEach((x) => x.classList.toggle("on", x === b));
    $("tri-surge").hidden = b.dataset.tri !== "surge";
    $("tri-clinic").hidden = b.dataset.tri !== "clinic";
  }));
  $("btn-brief").onclick = async () => {
    const btn = $("btn-brief");
    btn.disabled = true;
    $("surge-status").textContent = "Nemotron is reading the surge… about 15 s";
    try {
      await api("/api/triage/brief");
      $("surge-status").textContent = "";
      await load();
    } catch (err) {
      $("surge-status").textContent = err.message;
    } finally { btn.disabled = false; }
  };
  load();
}
