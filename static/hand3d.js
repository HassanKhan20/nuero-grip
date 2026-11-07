// 3D robotic hand (Three.js). Driven by the 5 servo angles; its look changes per condition.
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

const OLIVE = 0x9fb04a;
const OLIVE_BRIGHT = 0xd6e68f;
const RED = 0xe0694f;
const AMBER = 0xe3a24c;

// index -> pinky, laid out across the top of the palm
const FINGERS = [
  { key: "index", x: 0.34, lens: [0.46, 0.3, 0.23], r: 0.095 },
  { key: "middle", x: 0.11, lens: [0.5, 0.33, 0.25], r: 0.098 },
  { key: "ring", x: -0.12, lens: [0.47, 0.31, 0.24], r: 0.094 },
  { key: "pinky", x: -0.34, lens: [0.36, 0.24, 0.2], r: 0.085 },
];
const THUMB = { key: "thumb", lens: [0.4, 0.3, 0.24], r: 0.11 };
const MAX_BEND = [1.35, 1.65, 1.15]; // radians per joint at full curl
const KEYS = ["thumb", "index", "middle", "ring", "pinky"];

export function supportsWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function roundedPalm() {
  const w = 1.0, h = 1.15, r = 0.2;
  const s = new THREE.Shape();
  s.moveTo(-w / 2 + r, 0);
  s.lineTo(w / 2 - r, 0);
  s.quadraticCurveTo(w / 2, 0, w / 2, r);
  s.lineTo(w / 2, h - r);
  s.quadraticCurveTo(w / 2, h, w / 2 - r, h);
  s.lineTo(-w / 2 + r, h);
  s.quadraticCurveTo(-w / 2, h, -w / 2, h - r);
  s.lineTo(-w / 2, r);
  s.quadraticCurveTo(-w / 2, 0, -w / 2 + r, 0);
  const g = new THREE.ExtrudeGeometry(s, { depth: 0.2, bevelEnabled: true, bevelThickness: 0.07, bevelSize: 0.07, bevelSegments: 4, curveSegments: 10 });
  g.translate(0, 0, -0.1);
  return g;
}

export function createHand3D(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.replaceChildren(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0d100b, 8, 17);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 60);
  camera.position.set(3.4, 1.9, 8.6);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.3, 0);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.minDistance = 5;
  controls.maxDistance = 13;

  scene.add(new THREE.HemisphereLight(0xf3f1e6, 0x23261a, 1.1));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.6);
  keyLight.position.set(3, 5, 4);
  scene.add(keyLight);
  const rim = new THREE.PointLight(OLIVE, 8, 9);
  rim.position.set(-2.2, 1.6, -2);
  scene.add(rim);
  const glow = new THREE.PointLight(OLIVE, 0, 5);
  glow.position.set(0, 0.9, 1.7);
  scene.add(glow);

  const grid = new THREE.GridHelper(16, 32, 0x7a8c2a, 0x252b12);
  grid.position.y = -2.1;
  grid.material.transparent = true;
  grid.material.opacity = 0.5;
  scene.add(grid);
  // glowing floor rings under the arm
  const floorRings = [[0.9, 0xd4ee6a, 0.55], [1.35, 0xd4ee6a, 0.22], [2.1, 0x4aa8ff, 0.12]].map(([r, color, opacity]) => {
    const ring = new THREE.Mesh(new THREE.RingGeometry(r, r + 0.025, 96),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = -2.08;
    ring.userData.base = opacity;
    scene.add(ring);
    return ring;
  });

  // materials
  const skin = new THREE.MeshStandardMaterial({ color: 0xdfe1cf, roughness: 0.42, metalness: 0.08, transparent: true });
  const armMat = new THREE.MeshStandardMaterial({ color: 0xc9ccb6, roughness: 0.5, metalness: 0.05 });
  const wire = new THREE.MeshBasicMaterial({ color: OLIVE_BRIGHT, wireframe: true, transparent: true, opacity: 0.07, depthWrite: false });
  const sphereGeo = new THREE.SphereGeometry(1, 18, 14);

  const root = new THREE.Group(); // whole arm (CP scales this)
  scene.add(root);
  const hand = new THREE.Group(); // wrist pivot (tremor, phantom mirror)
  root.add(hand);

  const forearm = new THREE.Mesh(new THREE.CapsuleGeometry(0.34, 1.5, 8, 24), armMat);
  forearm.position.y = -1.15;
  forearm.scale.set(1.05, 1, 0.72);
  root.add(forearm);

  const palm = new THREE.Mesh(roundedPalm(), skin);
  palm.add(new THREE.Mesh(palm.geometry, wire));
  hand.add(palm);

  const knuckleMats = [];
  function buildFinger(spec, base) {
    const joints = [];
    const mat = new THREE.MeshStandardMaterial({ color: OLIVE, roughness: 0.3, emissive: OLIVE, emissiveIntensity: 0.25 });
    knuckleMats.push(mat);
    let parent = base;
    spec.lens.forEach((len, i) => {
      let j = base;
      if (i > 0) {
        j = new THREE.Group();
        j.position.y = spec.lens[i - 1];
        parent.add(j);
      }
      const r = spec.r * (1 - i * 0.08);
      const seg = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 16), skin);
      seg.position.y = len / 2;
      seg.add(new THREE.Mesh(seg.geometry, wire));
      j.add(seg);
      const knuckle = new THREE.Mesh(sphereGeo, mat);
      knuckle.scale.setScalar(r * 1.12);
      j.add(knuckle);
      joints.push(j);
      parent = j;
    });
    const tip = new THREE.Object3D();
    tip.position.y = spec.lens[spec.lens.length - 1] + spec.r * 0.6;
    parent.add(tip);
    hand.add(base);
    return { joints, tip, base };
  }

  const fingers = {};
  FINGERS.forEach((spec) => {
    const base = new THREE.Group();
    base.position.set(spec.x, 1.12, 0);
    base.rotation.z = -spec.x * 0.18;
    fingers[spec.key] = buildFinger(spec, base);
  });
  const thumbBase = new THREE.Group();
  thumbBase.position.set(0.5, 0.3, 0.08);
  thumbBase.rotation.set(0, -0.35, -0.95);
  fingers.thumb = buildFinger(THUMB, thumbBase);

  // signal pulses + tendon lines (wrist -> fingertip)
  const pulseMat = new THREE.MeshBasicMaterial({ color: OLIVE_BRIGHT, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
  const lineMat = new THREE.LineBasicMaterial({ color: OLIVE_BRIGHT, transparent: true, opacity: 0, depthWrite: false });
  const wristLocal = new THREE.Vector3(0, 0.12, 0.2);
  const paths = {};
  KEYS.forEach((k, i) => {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 5 }, () => new THREE.Vector3())), lineMat);
    line.frustumCulled = false;
    scene.add(line);
    const pulses = [0, 0.5].map((phase) => {
      const p = new THREE.Mesh(sphereGeo, pulseMat);
      p.scale.setScalar(0.05);
      p.userData.phase = phase + i * 0.13;
      scene.add(p);
      return p;
    });
    paths[k] = { line, pulses, pts: Array.from({ length: 5 }, () => new THREE.Vector3()) };
  });

  // Parkinson's: tremor rings at the wrist
  const rings = [0, 1, 2].map(() => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.012, 8, 80),
      new THREE.MeshBasicMaterial({ color: AMBER, transparent: true, opacity: 0, depthWrite: false }));
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.05;
    root.add(ring);
    return ring;
  });

  // Cognitive: halo behind the hand
  const halo = new THREE.Mesh(new THREE.TorusGeometry(1.55, 0.025, 10, 140),
    new THREE.MeshBasicMaterial({ color: OLIVE_BRIGHT, transparent: true, opacity: 0, depthWrite: false }));
  halo.position.set(0, 0.95, -0.35);
  root.add(halo);

  // Phantom: drifting particles
  const pCount = 320;
  const pPos = new Float32Array(pCount * 3);
  for (let i = 0; i < pCount; i++) {
    pPos[i * 3] = (Math.random() - 0.5) * 2.6;
    pPos[i * 3 + 1] = Math.random() * 3 - 0.4;
    pPos[i * 3 + 2] = (Math.random() - 0.5) * 1.4;
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.BufferAttribute(pPos, 3));
  const particles = new THREE.Points(pGeo, new THREE.PointsMaterial({
    color: OLIVE_BRIGHT, size: 0.035, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false,
  }));
  root.add(particles);

  // state
  const cur = Object.fromEntries(KEYS.map((k) => [k, 0]));
  let target = { ...cur };
  let state = { mode: "stroke", tremor_hz: 0, intent_active: false, intent_strength: 0, cue_active: false, cue_pending: false };
  let gate = "";
  let appliedMode = null;
  const emissiveTarget = new THREE.Color(0x000000);
  const tmp = new THREE.Vector3();

  function applyCondition(mode) {
    const phantom = mode === "phantom";
    skin.opacity = phantom ? 0.14 : 1;
    skin.depthWrite = !phantom;
    skin.side = phantom ? THREE.DoubleSide : THREE.FrontSide;
    skin.needsUpdate = true;
    wire.opacity = phantom ? 0.5 : 0.07;
    hand.scale.set(phantom ? -1 : 1, 1, 1); // mirror image of the healthy hand
    root.scale.setScalar(mode === "cp" ? 0.8 : 1); // child-size hand
    particles.visible = phantom;
    appliedMode = mode;
  }

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  const clock = new THREE.Clock();
  function frame() {
    const dt = Math.min(0.05, clock.getDelta());
    const t = clock.elapsedTime;
    const mode = state.mode;
    if (mode !== appliedMode) applyCondition(mode);

    // joints ease toward the commanded servo angles
    KEYS.forEach((k) => { cur[k] += (target[k] - cur[k]) * Math.min(1, dt * 12); });
    FINGERS.forEach(({ key }) => fingers[key].joints.forEach((j, i) => { j.rotation.x = cur[key] * MAX_BEND[i]; }));
    const th = fingers.thumb, c = cur.thumb;
    th.base.rotation.z = -0.95 + c * 0.75;
    th.base.rotation.x = c * 0.5;
    th.joints[1].rotation.x = c * 0.7;
    th.joints[2].rotation.x = c * 0.8;

    // idle sway + floor glow that brightens while the patient is trying
    root.rotation.y = Math.sin(t * 0.35) * 0.12;
    floorRings.forEach((ring, i) => {
      const boost = state.intent_active ? 1.8 : 1;
      ring.material.opacity = ring.userData.base * boost * (0.85 + 0.15 * Math.sin(t * 2 + i));
    });

    // Parkinson's: tremor at the measured frequency (none shown when none is measured)
    const f = mode === "parkinsons" ? state.tremor_hz : 0;
    if (f > 0) {
      const w = 2 * Math.PI * f * t;
      hand.rotation.z = 0.045 * Math.sin(w);
      hand.rotation.x = 0.025 * Math.sin(w + 1.1);
      th.base.rotation.x += 0.12 * Math.sin(w); // pill-rolling thumb
      rings.forEach((ring, i) => {
        const u = ((t * f * 0.5) + i / 3) % 1;
        ring.scale.setScalar(1 + u * 1.4);
        ring.material.opacity = 0.55 * (1 - u);
      });
    } else {
      hand.rotation.z = 0;
      hand.rotation.x = 0;
      rings.forEach((ring) => { ring.material.opacity = 0; });
    }

    // CP: joint colour shows how hard each finger is flexing
    const cpMode = mode === "cp";
    [...FINGERS.map((s) => s.key), "thumb"].forEach((k, i) => {
      const m = knuckleMats[i];
      m.color.setHex(OLIVE);
      if (cpMode) m.color.lerp(new THREE.Color(AMBER), cur[k]);
      m.emissive.copy(m.color);
    });

    // Cognitive: halo breathes while waiting, flashes on the cue
    if (mode === "cognitive") {
      const flash = state.cue_active ? 0.75 + 0.25 * Math.sin(t * 18) : state.cue_pending ? 0.25 + 0.15 * Math.sin(t * 4) : 0.12;
      halo.material.opacity = flash;
      halo.scale.setScalar(state.cue_active ? 1.04 + 0.03 * Math.sin(t * 18) : 1);
    } else {
      halo.material.opacity = 0;
    }

    // phantom particles drift upward
    if (particles.visible) {
      const a = pGeo.attributes.position;
      for (let i = 0; i < pCount; i++) {
        let y = a.getY(i) + dt * 0.18;
        if (y > 2.6) y = -0.4;
        a.setY(i, y);
      }
      a.needsUpdate = true;
    }

    // signal pulses: wrist -> fingertip while the patient is trying
    hand.updateMatrixWorld(true);
    const showSignal = (mode === "stroke" || mode === "cp" || mode === "phantom" || mode === "cognitive") && state.intent_active;
    const speed = 0.5 + state.intent_strength;
    lineMat.opacity += ((showSignal ? 0.55 : 0) - lineMat.opacity) * Math.min(1, dt * 6);
    KEYS.forEach((k) => {
      const fg = fingers[k], p = paths[k];
      hand.localToWorld(p.pts[0].copy(wristLocal));
      fg.base.getWorldPosition(p.pts[1]);
      fg.joints[1].getWorldPosition(p.pts[2]);
      fg.joints[2].getWorldPosition(p.pts[3]);
      fg.tip.getWorldPosition(p.pts[4]);
      p.line.geometry.setFromPoints(p.pts);
      p.pulses.forEach((pulse) => {
        pulse.visible = showSignal;
        if (!showSignal) return;
        const u = (t * speed * 0.6 + pulse.userData.phase) % 1;
        const seg = Math.min(3, Math.floor(u * 4));
        tmp.lerpVectors(p.pts[seg], p.pts[seg + 1], u * 4 - seg);
        pulse.position.copy(tmp);
      });
    });

    // gate glow: green while moving, red when blocked
    emissiveTarget.setHex(gate === "open" ? OLIVE : gate === "blocked" ? RED : 0x000000);
    skin.emissive.lerp(emissiveTarget, Math.min(1, dt * 6));
    skin.emissiveIntensity = 0.16;
    glow.color.copy(gate === "blocked" ? new THREE.Color(RED) : new THREE.Color(OLIVE));
    glow.intensity += ((gate ? 6 : 0) - glow.intensity) * Math.min(1, dt * 5);

    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  return {
    update(s, gateState) {
      state = s;
      gate = gateState;
      target = Object.fromEntries(KEYS.map((k, i) => [k, (s.angles[i] || 0) / 160]));
    },
  };
}
