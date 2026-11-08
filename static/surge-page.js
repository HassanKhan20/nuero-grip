import { $, api, toast, initShell } from "./common.js";
import { initSurge } from "./command.js";

initShell();
initSurge({ api, toast });

// My clinic: the clinic's 10 patients ranked by Nemotron
const status = (text) => { $("triage-status").hidden = !text; $("triage-status").textContent = text || ""; };
$("btn-triage").onclick = async () => {
  const btn = $("btn-triage");
  btn.disabled = true;
  status("Nemotron is ranking your patients…");
  try {
    const r = await api("/api/triage", "GET");
    const labels = { urgent: "Urgent", monitor: "Monitor", stable: "Stable" };
    $("triage-table").querySelector("tbody").replaceChildren(...r.patients.map((p) => {
      const tr = document.createElement("tr");
      [labels[p.urgency] || p.urgency, p.name, p.condition, `${p.last_session_days_ago} days ago`, p.reason].forEach((v, i) => {
        const td = document.createElement("td");
        td.textContent = v;
        if (i === 0) td.className = `urg ${p.urgency}`;
        tr.append(td);
      });
      return tr;
    }));
    $("triage-table").hidden = false;
    status("");
  } catch (err) {
    status(err.message);
  } finally { btn.disabled = false; }
};
