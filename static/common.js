// Shared by every page: fetch helper, toast, the live socket, the incident badge in the system bar, PDF export.
export const $ = (id) => document.getElementById(id);
export const role = document.body.dataset.role;

export async function api(path, method = "POST", body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 3500);
}

export function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

let shell = null;
export function initShell() {
  if (shell) return shell;
  const socket = io();
  socket.on("connect", () => $("conn-dot")?.classList.add("live"));
  socket.on("disconnect", () => $("conn-dot")?.classList.remove("live"));

  // Export PDF: the browser's "Save as PDF" names the file from the title
  document.querySelectorAll("[data-print]").forEach((b) => b.addEventListener("click", () => {
    const original = document.title;
    document.title = `NeuroGrip ${b.dataset.print} ${new Date().toISOString().slice(0, 10)}`;
    window.addEventListener("afterprint", () => { document.title = original; }, { once: true });
    window.print();
  }));

  if (role === "therapist") {
    // the Command center badge is live on every page, so a new incident is never missed
    const live = new Map();
    const badge = () => {
      const b = $("inc-badge");
      if (!b) return;
      const rows = [...live.values()].filter((i) => i.status !== "resolved");
      b.textContent = rows.length;
      b.hidden = !rows.length;
      b.classList.toggle("bad", rows.some((i) => i.severity === "critical" || i.severity === "high"));
    };
    api("/api/incidents", "GET").then((r) => { r.incidents.forEach((i) => live.set(i.id, i)); badge(); }).catch(() => {});
    socket.on("incident", (inc) => {
      const isNew = !live.has(inc.id);
      live.set(inc.id, inc);
      badge();
      if (isNew) toast(`New incident · ${inc.title}`);
      else if (inc.timeline.at(-1)?.kind === "escalated") toast(`Escalated · ${inc.title}`);
    });
  }
  shell = { socket };
  return shell;
}
