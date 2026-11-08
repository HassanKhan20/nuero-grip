import { $, api, toast, initShell } from "./common.js";
import { initSurge } from "./command.js";

initShell();
initSurge({ api, toast });

// My caseload: the clinic's 10 patients ranked by Nemotron
$("btn-triage").onclick = async () => {
  const btn = $("btn-triage");
  btn.disabled = true;
  $("triage-status").textContent = "Nemotron is ranking your caseload…";
  try {
    const r = await api("/api/triage", "GET");
    const labels = { urgent: "Urgent", monitor: "Monitor", stable: "Stable" };
    const trends = { improving: "Improving", declining: "Declining", stable: "Stable" };
    $("triage-table").querySelector("tbody").replaceChildren(...r.patients.map((p) => {
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
    $("triage-status").textContent = "";
    $("caseload-meta").textContent = `Caseload ranked ${new Date().toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} by NVIDIA Nemotron`;
  } catch (err) {
    $("triage-status").textContent = err.message;
  } finally { btn.disabled = false; }
};
