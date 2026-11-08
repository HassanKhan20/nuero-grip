// Command center (incidents + audit log) and surge triage. Full pages, therapist only.
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
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
};
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
const SEV = { low: "Low", medium: "Medium", high: "High", critical: "Critical" };
const STATUS = { open: "New", acknowledged: "In progress", resolved: "Resolved" };
const ACTIONS = {
  login: "Signed in", logout: "Signed out", login_failed: "Failed sign-in", login_blocked: "Blocked (lockout)",
  denied: "Access denied", agent_review: "AI session review", triage_brief: "AI surge plan",
  incident_declared: "New incident", incident_ack: "Took incident", incident_assign: "Assigned",
  incident_note: "Update", intent_zero: "Re-zeroed intent", incident_resolve: "Resolved", incident_reopen: "Reopened", incident_scope: "Scope changed",
};

export function initCommandCenter({ api, toast, socket }) {
  const byId = new Map();
  let tab = "active";
  let selected = null;

  const active = (i) => i.status !== "resolved";
  const visible = () => [...byId.values()].filter((i) => (tab === "active" ? active(i) : !active(i))).sort((a, b) => b.updated - a.updated);

  function renderCounts() {
    const all = [...byId.values()];
    const a = all.filter(active).length;
    $("cc-count-active").textContent = a ? `(${a})` : "";
    $("cc-count-resolved").textContent = all.length - a ? `(${all.length - a})` : "";
  }

  function renderList() {
    const rows = visible();
    if (rows.length && !rows.some((i) => i.id === selected)) selected = rows[0].id;
    const ul = $("cc-list");
    if (!rows.length) {
      ul.replaceChildren(el("li", "empty", tab === "active" ? "All clear. No open incidents." : "Nothing resolved yet."));
      return;
    }
    ul.replaceChildren(...rows.map((i) => {
      const li = el("li", `sev-${i.severity}${i.id === selected ? " on" : ""}`);
      li.tabIndex = 0;
      li.append(el("b", "", i.title), el("span", "cc-meta", `${SEV[i.severity]} · ${STATUS[i.status]} · ${ago(i.updated)}`));
      li.onclick = () => { selected = i.id; renderList(); renderDetail(); };
      li.onkeydown = (e) => { if (e.key === "Enter") li.onclick(); };
      return li;
    }));
  }

  async function act(action, body) {
    try { upsert(await api(`/api/incidents/${selected}/${action}`, "POST", body)); } catch (err) { toast(err.message); }
  }

  function renderDetail() {
    const box = $("cc-detail");
    const i = byId.get(selected);
    if (!i || !visible().includes(i)) { box.replaceChildren(el("p", "", "Pick an incident on the left.")); return; }

    const head = el("div", "cc-dhead");
    head.append(el("h3", "", i.title), el("span", `pill sev-${i.severity}`, SEV[i.severity]), el("span", `pill st-${i.status}`, STATUS[i.status]));
    const facts = el("p", "cc-facts", `Owner: ${i.owner || "nobody yet"} · Detected ${ago(i.created)}`);
    const parts = [head, facts];
    if (i.detail) parts.push(el("p", "", i.detail));

    const actions = el("div", "btn-row");
    const btn = (label, cls, fn) => { const b = el("button", `btn ${cls}`, label); b.type = "button"; b.onclick = fn; actions.append(b); };
    if (i.status === "open") btn("Take it", "primary", () => act("ack"));
    if (i.status !== "resolved") btn("Resolve", i.status === "open" ? "ghost" : "primary", () => act("resolve", { text: "Resolved" }));
    else btn("Reopen", "ghost", () => act("reopen"));
    parts.push(actions, el("h4", "", "Updates"));

    const tl = el("ol", "cc-timeline");
    i.timeline.forEach((e) => {
      const li = el("li", `tl-${e.kind}`);
      li.append(el("span", "tl-time", `${clock(e.t)} · ${e.actor}`), el("p", "", e.text));
      tl.append(li);
    });
    const form = el("form", "cc-compose");
    form.innerHTML = `<input id="cc-note" placeholder="Write an update for the team" maxlength="500" autocomplete="off"><button type="submit" class="btn ghost">Send</button>`;
    form.onsubmit = (e) => {
      e.preventDefault();
      const text = $("cc-note").value.trim();
      if (!text) return;
      $("cc-note").value = "";
      act("note", { text });
    };
    parts.push(tl, form);
    box.replaceChildren(...parts);
    tl.scrollTop = tl.scrollHeight;
  }

  function upsert(inc) {  // new-incident toasts and the nav badge come from the shell (common.js)
    byId.set(inc.id, inc);
    if (!selected) selected = inc.id;
    renderCounts(); renderList();
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
      renderCounts(); renderList(); renderDetail();
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
    if (audit) { loadAudit(); return; }
    tab = b.dataset.cc;
    renderList(); renderDetail();
  }));
  $("cc-declare-btn").onclick = () => { $("cc-declare").hidden = false; $("cc-declare-btn").hidden = true; $("cc-declare").elements.title.focus(); };
  const closeDeclare = () => { $("cc-declare").hidden = true; $("cc-declare-btn").hidden = false; $("cc-declare").reset(); };
  $("cc-declare-cancel").onclick = closeDeclare;
  $("cc-declare").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const inc = await api("/api/incidents", "POST", Object.fromEntries(new FormData(e.target)));
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

export function initSurge({ api }) {
  let urg = "urgent";
  let data = null;
  const status = (text) => { $("surge-status").hidden = !text; $("surge-status").textContent = text || ""; };

  function stat(value, label, tone) {
    const d = el("div", `stat ${tone || ""}`);
    d.append(el("b", "", value), el("span", "", label));
    return d;
  }

  function render() {
    const s = data.summary;
    $("surge-kpis").replaceChildren(
      stat(fmtNum(s.total), "patients cut off from care"),
      stat(fmtNum(s.urgent), "need help urgently", "bad"),
      stat(fmtNum(s.unassigned_urgent), "urgent with no therapist yet", s.unassigned_urgent ? "bad" : "good"),
    );
    if (data.brief) {
      $("surge-brief").textContent = data.brief;
      $("surge-brief").hidden = false;
      $("btn-brief").textContent = "Rewrite plan";
    }

    const labels = { urgent: "Urgent", monitor: "Monitor", stable: "Stable" };
    $("surge-table").querySelector("tbody").replaceChildren(...data.patients.map((p) => {
      const tr = el("tr");
      const care = p.assigned_to || (p.care === "waitlist" ? "Waitlist" : "Home program");
      [labels[p.urgency], p.name, p.region, p.ai_reason || p.reason, care].forEach((v, i) => {
        const td = el("td", "", v);
        if (i === 0) td.className = `urg ${p.urgency}`;
        if (i === 4) td.className = `care ${p.care.replace(" ", "-")}`;
        tr.append(td);
      });
      return tr;
    }));
    const shown = data.patients.length;
    const total = urg ? s[urg] : s.total;
    $("surge-more").textContent = shown < total ? `Top ${shown} of ${fmtNum(total)}, highest risk first.` : "";
  }

  async function load() {
    try {
      data = await api(`/api/triage/population?limit=150&urgency=${urg}`, "GET");
      render();
    } catch (err) { status(err.message); }
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
    status("Nemotron is writing the plan… about 15 s");
    try {
      await api("/api/triage/brief");
      status("");
      await load();
    } catch (err) {
      status(err.message);
    } finally { btn.disabled = false; }
  };
  load();
}
