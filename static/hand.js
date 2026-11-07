// Virtual robotic hand (side view). Five actuated fingers, one per servo:
// thumb, index, middle, ring, pinky (same order as the serial protocol).
const SVG_NS = "http://www.w3.org/2000/svg";

const PHALANGES = [34, 25, 18];          // segment lengths
const JOINT_MAX = [70, 95, 65];          // degrees at full curl, per joint
const FINGERS = [                         // drawn back to front
  { key: "pinky", y: 113, shade: 3, scale: 0.78 },
  { key: "ring", y: 105, shade: 2, scale: 0.95 },
  { key: "middle", y: 96, shade: 1, scale: 1.05 },
  { key: "index", y: 87, shade: 0, scale: 1.0 },
];

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.append(n);
  return n;
}

function buildFinger(root, x, y, shade, lengths, baseAngle = 0) {
  const joints = [];
  let parent = el("g", { class: `finger shade-${shade}` }, root);
  parent.style.transform = `translate(${x}px, ${y}px) rotate(${baseAngle}deg)`;
  joints.push({ g: parent, x, y, base: baseAngle });
  lengths.forEach((len, i) => {
    el("rect", { x: 0, y: -7, width: len + 4, height: 14, rx: 7, class: "segment" }, parent);
    el("circle", { cx: 0, cy: 0, r: 4.5, class: "joint" }, parent);
    if (i < lengths.length - 1) {
      const next = el("g", {}, parent);
      next.style.transform = `translate(${len}px, 0px)`;
      joints.push({ g: next, x: len, y: 0, base: 0 });
      parent = next;
    } else {
      el("circle", { cx: len, cy: 0, r: 3, class: "fingertip" }, parent);
    }
  });
  return joints;
}

export function createHand(container) {
  const svg = el("svg", { viewBox: "0 0 260 200", class: "robot-hand", role: "img",
    "aria-label": "Virtual robotic hand mirroring the commanded servo angles" });
  el("rect", { x: 0, y: 92, width: 70, height: 40, rx: 10, class: "forearm" }, svg);
  el("rect", { x: 14, y: 96, width: 6, height: 32, rx: 3, class: "strap" }, svg);
  el("rect", { x: 34, y: 96, width: 6, height: 32, rx: 3, class: "strap" }, svg);
  const groups = { thumb: [], index: [], middle: [], ring: [], pinky: [] };
  FINGERS.forEach((f) => groups[f.key].push(buildFinger(svg, 140, f.y, f.shade, PHALANGES.map((l) => l * f.scale))));
  el("rect", { x: 62, y: 78, width: 84, height: 58, rx: 16, class: "palm" }, svg);
  el("circle", { cx: 104, cy: 107, r: 9, class: "hub" }, svg);
  groups.thumb.push(buildFinger(svg, 118, 132, 0, [26, 20], 28));
  container.replaceChildren(svg);

  return {
    update(angles, state) {
      const keys = ["thumb", "index", "middle", "ring", "pinky"];
      const curl = Object.fromEntries(keys.map((k, i) => [k, (angles[i] || 0) / 160]));
      for (const [key, fingers] of Object.entries(groups)) {
        const c = curl[key];
        fingers.forEach((joints) => {
          joints.forEach((j, i) => {
            const bend = key === "thumb" ? -c * (i === 0 ? 55 : 60) : c * JOINT_MAX[i];
            j.g.style.transform = `translate(${j.x}px, ${j.y}px) rotate(${j.base + bend}deg)`;
          });
        });
      }
      svg.classList.toggle("open", state === "open");
      svg.classList.toggle("blocked", state === "blocked");
    },
  };
}
