// First-visit guided tour: spotlight a part of the screen, explain it in one or two lines,
// and have the user actually move the hand once. Replay from the "?" button in the dock.
const KEY = "ng-onboarded-v1";

const remembered = () => { try { return localStorage.getItem(KEY) === "1"; } catch { return false; } };
const remember = () => { try { localStorage.setItem(KEY, "1"); } catch { /* private mode: fine */ } };

function steps(role) {
  const therapist = role === "therapist";
  return [
    { title: "Welcome to NeuroGrip",
      body: "The robotic hand moves only while the patient is trying. This tour takes about a minute." },
    { target: ".tabs", title: "Pick a condition",
      body: "Stroke, Parkinson's, phantom limb, cerebral palsy or cognitive screening. The 3D hand and the numbers change with it." },
    { target: ".col.left .panel:first-child", title: "Try it",
      body: "Intent is the patient's effort. On the device it comes from the headband pads. Here, hold Space.",
      task: "Hold Space until the hand closes",
      practice: true,
      done: (s) => Math.max(...s.angles) >= 60 },
    { target: ".dock-row", title: "Two ways to drive the hand",
      body: "Mirror copies the healthy hand on camera. Intent only moves from effort alone. Drag the 3D hand to rotate it." },
    { target: ".col.left .panel:nth-child(2)", title: therapist ? "Motor function status" : "Today",
      body: "The numbers that matter for this condition. Activation is the share of tries strong enough to move the hand." },
    { target: ".col.right .panel:first-child", title: "Needs attention",
      body: "Posture compensation and missed tests appear here, most serious first." },
    { target: ".col.right .panel:nth-child(2)", title: therapist ? "Session review" : "Your progress",
      body: therapist
        ? "End the session and Nemotron reviews it: what changed, a plan, and the next difficulty."
        : "Gemini explains today's session in plain words." },
    { target: ".dock", title: "Tools",
      body: therapist ? "Caseload, sensors and calibration, and the full activity log. Replay this tour with ?."
                      : "Sensors and calibration, and the full activity log. Replay this tour with ?." },
    { title: "You're set", body: "Calibrate to the wearer before the first session so effort is scaled to their pads.", final: true },
  ];
}

export function createTour({ role, api, toast }) {
  let list = [], i = 0, active = false, lastState = null, restoreControl = null, advancing = false;
  const spot = document.createElement("div");
  spot.className = "tour-spot";
  const card = document.createElement("div");
  card.className = "tour-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-live", "polite");

  function visibleTarget(sel) {
    if (!sel) return null;
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return r.width && r.height ? el : null;
  }

  function place() {
    const step = list[i];
    const el = visibleTarget(step.target);
    const vw = innerWidth, vh = innerHeight, gap = 14;
    const cw = card.offsetWidth || 340, ch = card.offsetHeight || 200;
    if (!el) {
      spot.classList.add("center");
      Object.assign(spot.style, { top: `${vh / 2}px`, left: `${vw / 2}px`, width: "0px", height: "0px" });
      Object.assign(card.style, { top: `${(vh - ch) / 2}px`, left: `${(vw - cw) / 2}px` });
      return;
    }
    spot.classList.remove("center");
    const r = el.getBoundingClientRect();
    const pad = 6;
    Object.assign(spot.style, { top: `${r.top - pad}px`, left: `${r.left - pad}px`, width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px` });
    let top, left;
    if (r.right + gap + cw < vw) { left = r.right + gap; top = r.top; }
    else if (r.left - gap - cw > 0) { left = r.left - gap - cw; top = r.top; }
    else if (r.bottom + gap + ch < vh) { top = r.bottom + gap; left = r.left + r.width / 2 - cw / 2; }
    else { top = r.top - gap - ch; left = r.left + r.width / 2 - cw / 2; }
    top = Math.max(16, Math.min(vh - ch - 16, top));
    left = Math.max(16, Math.min(vw - cw - 16, left));
    Object.assign(card.style, { top: `${top}px`, left: `${left}px` });
  }

  function render() {
    const step = list[i];
    const last = i === list.length - 1;
    const taskDone = step.task && lastState && step.done(lastState);
    card.innerHTML = `
      <h3></h3><p class="tour-body"></p>
      ${step.task ? `<p class="tour-task ${taskDone ? "done" : ""}"></p>` : ""}
      <div class="tour-foot">
        <div class="tour-dots">${list.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("")}</div>
        <div class="btn-row">
          ${last ? "" : '<button type="button" class="btn link" data-t="skip">Skip</button>'}
          ${i > 0 && !last ? '<button type="button" class="btn ghost" data-t="back">Back</button>' : ""}
          ${step.final ? '<button type="button" class="btn ghost" data-t="done">Done</button><button type="button" class="btn primary" data-t="cal">Calibrate now</button>'
                       : `<button type="button" class="btn primary" data-t="next">${step.task && !taskDone ? "Skip step" : "Next"}</button>`}
        </div>
      </div>`;
    card.querySelector("h3").textContent = step.title;
    card.querySelector(".tour-body").textContent = step.body;
    const task = card.querySelector(".tour-task");
    if (task) task.textContent = taskDone ? "Done. The hand moved because you tried." : step.task;
    place();
    requestAnimationFrame(place);
    if (step.task) document.activeElement?.blur(); // keep Space for the hold-to-try handler
    else card.querySelector('[data-t="next"], [data-t="cal"]')?.focus();
  }

  async function enter(k) {
    const prev = list[i];
    if (prev?.practice && restoreControl) {
      api("/api/control", "POST", { mode: restoreControl }).catch(() => {});
      restoreControl = null;
    }
    i = k;
    advancing = false;
    const step = list[i];
    if (step.practice && lastState) {
      // practice without the camera: intent alone closes the hand
      restoreControl = lastState.control_mode;
      await api("/api/control", "POST", { mode: "intent", grip: "fist" }).catch(() => {});
    }
    render();
  }

  function finish() {
    if (!active) return;
    if (list[i]?.practice && restoreControl) api("/api/control", "POST", { mode: restoreControl }).catch(() => {});
    restoreControl = null;
    active = false;
    spot.remove();
    card.remove();
    remember();
  }

  card.addEventListener("click", (e) => {
    const t = e.target.closest("[data-t]")?.dataset.t;
    if (t === "next") i < list.length - 1 ? enter(i + 1) : finish();
    if (t === "back") enter(Math.max(0, i - 1));
    if (t === "skip" || t === "done") finish();
    if (t === "cal") { finish(); api("/api/calibrate").catch((err) => toast(err.message)); }
  });
  document.addEventListener("keydown", (e) => {
    if (!active) return;
    if (e.key === "Escape") finish();
    if (e.key === "ArrowRight" && !list[i].task) enter(Math.min(list.length - 1, i + 1));
    if (e.key === "ArrowLeft") enter(Math.max(0, i - 1));
  });
  addEventListener("resize", () => active && place());

  window.addEventListener("ng-state", (e) => {
    lastState = e.detail;
    if (!active) return;
    const step = list[i];
    if (step.task && step.done(lastState) && !advancing) {
      advancing = true;
      render();
      setTimeout(() => active && list[i] === step && enter(i + 1), 1400);
    }
  });

  return {
    start() {
      if (active || document.querySelector("dialog[open]")) return;
      list = steps(role);
      active = true;
      document.body.append(spot, card);
      enter(0);
    },
    startIfNew() { if (!remembered()) setTimeout(() => this.start(), 700); },
  };
}
