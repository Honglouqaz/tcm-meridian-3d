/**
 * anatomy.js —— 程序化人体：皮肤 / 骨骼 / 肌肉
 *
 * 全部由 data/body.json 的体表剖面（profile）与肢体参数生成，不依赖任何外部 3D 资产。
 * 这样做的原因：原仓库只有穴位点、没有人体，点自然「悬空」；把体表做成**解析几何**之后，
 * 每个穴位都能被精确投影上去（见 tools/build_body.py），人体与穴位永远同一套坐标。
 *
 * 坐标约定：y 向上，z 向前（腹侧），x 向右（人体左侧为 -x）。
 * 单位：1 ≈ 0.196 m（身高 8.68 单位 ≈ 1.70 m）。
 */
import * as THREE from 'three';

// 皮肤默认**不透明**：半透明材质在 three.js 里不写深度、且总在最后绘制，
// 结果就是背面穴位全部透出来、看起来像穿模。要看内部请切「内视」。
const SKIN = new THREE.MeshPhysicalMaterial({
  color: 0xe8cdb6, roughness: 0.62, metalness: 0.0, clearcoat: 0.35,
  side: THREE.DoubleSide, transparent: false,
});
// 「内视」模式：几乎全透，只看经络穴位（解剖图册常用）
const SKIN_XRAY = new THREE.MeshPhysicalMaterial({
  color: 0x8fb4cc, transparent: true, opacity: 0.07, roughness: 0.8,
  side: THREE.DoubleSide, depthWrite: false,
});
const SKIN_EDGE = new THREE.MeshBasicMaterial({
  color: 0x6f8fa8, transparent: true, opacity: 0.20, wireframe: true,
});

/** 线框副本：打 wire 标记、默认隐藏，供「皮肤线框」开关统一控制 */
function edgeMesh(geo) {
  const m = new THREE.Mesh(geo, SKIN_EDGE);
  m.userData.wire = true;
  m.visible = false;
  return m;
}
const BONE = new THREE.MeshStandardMaterial({ color: 0xe9e3d2, roughness: 0.7, metalness: 0.05 });
const CARTILAGE = new THREE.MeshStandardMaterial({ color: 0xb9c6c9, roughness: 0.8 });
const MUSCLE = new THREE.MeshStandardMaterial({
  color: 0xa8402f, transparent: true, opacity: 0.38, roughness: 0.85, depthWrite: false,
});

/** 切换皮肤显示模式：'solid' 实体半透 | 'xray' 内视（近乎全透）| 'hidden' 隐藏 */
export function setSkinMode(root, mode) {
  const g = root?.getObjectByName('skin');
  if (!g) return;
  g.visible = mode !== 'hidden';
  g.traverse(o => {
    if (!o.isMesh || o.userData.wire) return;
    o.material = mode === 'xray' ? SKIN_XRAY : SKIN;
  });
}

/** 体表剖面插值：给定 y，返回 {rx, rz, zc} */
export function profileAt(profile, y) {
  if (!profile.length) return { rx: 0.5, rz: 0.25, zc: 0 };
  if (y <= profile[0].y) return profile[0];
  if (y >= profile[profile.length - 1].y) return profile[profile.length - 1];
  for (let i = 0; i < profile.length - 1; i++) {
    const a = profile[i], b = profile[i + 1];
    if (y >= a.y && y <= b.y) {
      const t = b.y > a.y ? (y - a.y) / (b.y - a.y) : 0;
      return {
        rx: a.rx + (b.rx - a.rx) * t,
        rz: a.rz + (b.rz - a.rz) * t,
        zc: a.zc + (b.zc - a.zc) * t,
      };
    }
  }
  return profile[profile.length - 1];
}

/** 皮肤：躯干 + 头 + 颈，按剖面逐层放样 */
export function buildSkin(body) {
  const g = new THREE.Group();
  g.name = 'skin';
  const prof = body.profile;
  const SEG = 32;

  // —— 躯干：逐层环 → 三角面 ——
  const rings = [];
  for (const row of prof) {
    if (row.y > body.meta.landmarks.neck_root + 0.05) continue;   // 颈部以上交给头
    const ring = [];
    for (let i = 0; i < SEG; i++) {
      const t = (i / SEG) * Math.PI * 2;
      ring.push(new THREE.Vector3(Math.cos(t) * row.rx, row.y, row.zc + Math.sin(t) * row.rz));
    }
    rings.push(ring);
  }
  const pos = [], idx = [];
  rings.forEach(r => r.forEach(v => pos.push(v.x, v.y, v.z)));
  for (let i = 0; i < rings.length - 1; i++) {
    for (let j = 0; j < SEG; j++) {
      const a = i * SEG + j, b = i * SEG + (j + 1) % SEG;
      const c = (i + 1) * SEG + j, d = (i + 1) * SEG + (j + 1) % SEG;
      idx.push(a, c, b, b, c, d);
    }
  }
  const torsoGeo = new THREE.BufferGeometry();
  torsoGeo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  torsoGeo.setIndex(idx);
  torsoGeo.computeVertexNormals();
  g.add(new THREE.Mesh(torsoGeo, SKIN));
  g.add(edgeMesh(torsoGeo.clone()));

  // —— 头：颅顶到下颌，用剖面最后一层往上收 ——
  const top = profileAt(prof, body.meta.landmarks.vertex);
  const chin = profileAt(prof, body.meta.landmarks.chin);
  const headY = (body.meta.landmarks.vertex + body.meta.landmarks.chin) / 2;
  const head = new THREE.Mesh(new THREE.SphereGeometry(1, 28, 22), SKIN);
  head.scale.set(Math.max(top.rx, 0.34), (body.meta.landmarks.vertex - body.meta.landmarks.chin) / 2 + 0.10,
                 Math.max(top.rz, 0.40));
  head.position.set(0, headY, (top.zc + chin.zc) / 2);
  g.add(head);
  const headEdge = edgeMesh(new THREE.SphereGeometry(1, 16, 12));
  headEdge.scale.copy(head.scale).multiplyScalar(1.002);
  headEdge.position.copy(head.position);
  g.add(headEdge);

  // —— 颈 ——
  const neckTop = profileAt(prof, body.meta.landmarks.chin);
  const neckBot = profileAt(prof, body.meta.landmarks.neck_root);
  const neck = new THREE.Mesh(
    new THREE.CylinderGeometry(neckTop.rx * 0.62, neckBot.rx * 0.78,
      body.meta.landmarks.chin - body.meta.landmarks.neck_root, 20, 1, true), SKIN);
  neck.position.set(0, (body.meta.landmarks.chin + body.meta.landmarks.neck_root) / 2,
                    (neckTop.zc + neckBot.zc) / 2);
  g.add(neck);

  // —— 手臂：沿 ±x，肩→肘→腕锥形 ——
  for (const [key, arm] of Object.entries(body.limbs.arms || {})) {
    const sgn = key === 'arm_l' ? -1 : 1;
    const len = arm.x_to - arm.x_from;
    const upper = new THREE.Mesh(new THREE.CylinderGeometry(arm.r_elbow, arm.r_shoulder, len * 0.5, 16, 1, true), SKIN);
    upper.rotation.z = Math.PI / 2;
    upper.position.set(sgn * (arm.x_from + len * 0.25), arm.y, arm.z);
    g.add(upper);
    const fore = new THREE.Mesh(new THREE.CylinderGeometry(arm.r_wrist, arm.r_elbow, len * 0.5, 16, 1, true), SKIN);
    fore.rotation.z = Math.PI / 2;
    fore.position.set(sgn * (arm.x_from + len * 0.75), arm.y, arm.z);
    g.add(fore);
    // 手掌 + 五指（T-pose 下手指沿 ±x 伸展，掌面朝下）
    const palm = new THREE.Mesh(new THREE.SphereGeometry(1, 14, 10), SKIN);
    palm.scale.set(0.13, 0.075, 0.16);
    palm.position.set(sgn * (arm.x_to + 0.02), arm.y, arm.z);
    g.add(palm);
    for (let f = 0; f < 5; f++) {
      const len = [0.20, 0.24, 0.23, 0.20, 0.16][f];
      const off = [-0.10, -0.035, 0.035, 0.10, 0.155][f];
      const finger = new THREE.Mesh(new THREE.CapsuleGeometry(0.026, len, 4, 8), SKIN);
      finger.rotation.z = Math.PI / 2;
      finger.position.set(sgn * (arm.x_to + 0.10 + len * 0.5), arm.y - 0.005, arm.z + off);
      g.add(finger);
    }
    // 肩关节：把手臂圆柱与躯干接缝包住
    const shoulder = new THREE.Mesh(new THREE.SphereGeometry(1, 18, 14), SKIN);
    shoulder.scale.set(0.26, arm.r_shoulder * 1.15, arm.r_shoulder * 1.15);
    shoulder.position.set(sgn * (arm.x_from + 0.10), arm.y, arm.z);
    g.add(shoulder);
    const elbow = new THREE.Mesh(new THREE.SphereGeometry(arm.r_elbow * 1.05, 14, 10), SKIN);
    elbow.position.set(sgn * (arm.x_from + len * 0.5), arm.y, arm.z);
    g.add(elbow);
  }

  // —— 腿：髋→膝→踝 ——
  for (const [key, leg] of Object.entries(body.limbs.legs || {})) {
    const len = leg.y_from - leg.y_to;
    const thigh = new THREE.Mesh(new THREE.CylinderGeometry(leg.r_knee, leg.r_hip, len * 0.52, 18, 1, true), SKIN);
    thigh.position.set(leg.x, leg.y_from - len * 0.26, leg.z);
    g.add(thigh);
    const shank = new THREE.Mesh(new THREE.CylinderGeometry(leg.r_ankle, leg.r_knee, len * 0.48, 18, 1, true), SKIN);
    shank.position.set(leg.x, leg.y_from - len * 0.76, leg.z);
    g.add(shank);
    // 脚掌 + 五趾（沿 +z 向前）
    const foot = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), SKIN);
    foot.scale.set(0.145, 0.095, 0.30);
    foot.position.set(leg.x, leg.y_to + 0.03, leg.z + 0.14);
    g.add(foot);
    for (let f = 0; f < 5; f++) {
      const len = [0.11, 0.10, 0.09, 0.08, 0.07][f];
      const off = [-0.085, -0.030, 0.025, 0.075, 0.120][f];
      const toe = new THREE.Mesh(new THREE.CapsuleGeometry(0.026, len, 4, 8), SKIN);
      toe.rotation.x = Math.PI / 2;
      toe.position.set(leg.x + off, leg.y_to + 0.02, leg.z + 0.42 + len * 0.4);
      g.add(toe);
    }
    // 髋/膝关节：包住接缝
    const hip = new THREE.Mesh(new THREE.SphereGeometry(leg.r_hip * 1.02, 18, 14), SKIN);
    hip.position.set(leg.x, leg.y_from + 0.02, leg.z);
    g.add(hip);
    const knee = new THREE.Mesh(new THREE.SphereGeometry(leg.r_knee * 1.02, 16, 12), SKIN);
    knee.position.set(leg.x, leg.y_from - len * 0.52, leg.z);
    g.add(knee);
  }
  return g;
}

/** 骨骼：脊柱 + 肋骨 + 颅骨 + 骨盆 + 四肢长骨 */
export function buildSkeleton(body) {
  const g = new THREE.Group();
  g.name = 'skeleton';
  const L = body.meta.landmarks;

  // 脊柱：从尾骨（长强）沿背侧上行到枕骨，内收 0.16
  const spinePts = [];
  for (let y = L.crotch + 0.12; y <= L.chin - 0.02; y += 0.12) {
    const p = profileAt(body.profile, y);
    spinePts.push(new THREE.Vector3(0, y, p.zc - p.rz + 0.16));
  }
  const spineCurve = new THREE.CatmullRomCurve3(spinePts);
  g.add(new THREE.Mesh(new THREE.TubeGeometry(spineCurve, 120, 0.055, 10, false), BONE));
  // 椎体：24 节
  for (let i = 0; i < 24; i++) {
    const p = spineCurve.getPoint(i / 23);
    const v = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.085, 0.045, 12), CARTILAGE);
    v.position.copy(p);
    g.add(v);
  }

  // 肋骨：12 对，从脊柱绕到胸骨
  for (let i = 0; i < 12; i++) {
    const y = L.shoulder - 0.06 - i * 0.115;
    const p = profileAt(body.profile, y);
    const depth = p.rz * 1.02, width = p.rx * 0.98;
    for (const sgn of [-1, 1]) {
      const pts = [];
      for (let k = 0; k <= 12; k++) {
        const t = k / 12;
        const ang = Math.PI * (0.5 + t * 0.92);            // 背面 → 侧面 → 前胸
        const shrink = 0.86 + 0.14 * Math.sin(t * Math.PI); // 肋弓形状
        pts.push(new THREE.Vector3(
          sgn * Math.cos(Math.PI - ang) * width * shrink,
          y - t * 0.10 * (i / 11),                          // 前侧略微下沉（肋弓）
          p.zc + Math.sin(ang) * depth * shrink));
      }
      const curve = new THREE.CatmullRomCurve3(pts);
      g.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 24, 0.022, 6, false), BONE));
    }
  }
  // 胸骨
  const sternum = new THREE.Mesh(new THREE.BoxGeometry(0.10, 0.62, 0.045), BONE);
  const sp = profileAt(body.profile, L.nipple);
  sternum.position.set(0, L.nipple + 0.30, sp.zc + sp.rz - 0.10);
  g.add(sternum);

  // 颅骨 + 下颌
  const headY = (L.vertex + L.chin) / 2;
  const hp = profileAt(body.profile, headY);
  const skull = new THREE.Mesh(new THREE.SphereGeometry(1, 24, 18), BONE);
  skull.scale.set(0.34, 0.40, 0.40);
  skull.position.set(0, headY + 0.04, hp.zc);
  g.add(skull);
  const jaw = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.10, 0.26), BONE);
  jaw.position.set(0, L.chin + 0.06, hp.zc + 0.10);
  g.add(jaw);

  // 肩胛骨：贴在背侧的扁平三角（缺了它肩部就是"没有骨架"）
  for (const sgn of [-1, 1]) {
    const scap = new THREE.Mesh(new THREE.BoxGeometry(0.30, 0.34, 0.05), BONE);
    const sp2 = profileAt(body.profile, L.shoulder - 0.16);
    scap.position.set(sgn * 0.30, L.shoulder - 0.18, sp2.zc - sp2.rz + 0.10);
    scap.rotation.set(0.18, sgn * 0.25, sgn * 0.12);
    g.add(scap);
  }

  // 骨盆：两片髂骨 + 耻骨/坐骨环
  const pel = profileAt(body.profile, L.pubis + 0.10);
  for (const sgn of [-1, 1]) {
    const ilium = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), BONE);
    ilium.scale.set(0.24, 0.20, 0.13);
    ilium.position.set(sgn * 0.24, L.pubis + 0.14, pel.zc - 0.04);
    ilium.rotation.z = sgn * 0.35;
    g.add(ilium);
  }
  // 骨盆环：用扁环把两侧髂骨连成一体（避免"两个球"的观感）
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.30, 0.045, 8, 28), BONE);
  ring.position.set(0, L.pubis + 0.06, pel.zc - 0.02);
  ring.rotation.x = Math.PI / 2;
  ring.scale.set(1, 0.78, 1);
  g.add(ring);
  const sacrum = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.30, 10), BONE);
  sacrum.position.set(0, L.pubis + 0.10, pel.zc - pel.rz + 0.18);
  sacrum.rotation.x = Math.PI;
  g.add(sacrum);

  // 锁骨
  for (const sgn of [-1, 1]) {
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, L.neck_root + 0.02, sp.zc + sp.rz - 0.06),
      new THREE.Vector3(sgn * 0.28, L.neck_root + 0.05, sp.zc + sp.rz - 0.12),
      new THREE.Vector3(sgn * 0.52, L.shoulder + 0.02, sp.zc - 0.02),
    ]);
    g.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 16, 0.026, 6, false), BONE));
  }

  // 四肢长骨
  for (const [key, arm] of Object.entries(body.limbs.arms || {})) {
    const sgn = key === 'arm_l' ? -1 : 1;
    const len = arm.x_to - arm.x_from;
    const hum = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.055, len * 0.48, 10), BONE);
    hum.rotation.z = Math.PI / 2;
    hum.position.set(sgn * (arm.x_from + len * 0.26), arm.y, arm.z);
    g.add(hum);
    for (const dz of [-0.05, 0.05]) {
      const rad = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.036, len * 0.46, 8), BONE);
      rad.rotation.z = Math.PI / 2;
      rad.position.set(sgn * (arm.x_from + len * 0.74), arm.y, arm.z + dz);
      g.add(rad);
    }
    // 腕骨 + 掌骨（5 根短杆，与手掌方向一致）
    for (let f = 0; f < 5; f++) {
      const off = [-0.10, -0.035, 0.035, 0.10, 0.155][f];
      const mc = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.016, 0.20, 6), BONE);
      mc.rotation.z = Math.PI / 2;
      mc.position.set(sgn * (arm.x_to + 0.06), arm.y, arm.z + off);
      g.add(mc);
    }
  }
  for (const [key, leg] of Object.entries(body.limbs.legs || {})) {
    const len = leg.y_from - leg.y_to;
    const fem = new THREE.Mesh(new THREE.CylinderGeometry(0.062, 0.075, len * 0.5, 10), BONE);
    fem.position.set(leg.x, leg.y_from - len * 0.25, leg.z);
    g.add(fem);
    const tib = new THREE.Mesh(new THREE.CylinderGeometry(0.042, 0.055, len * 0.44, 10), BONE);
    tib.position.set(leg.x, leg.y_from - len * 0.72, leg.z);
    g.add(tib);
    const knee = new THREE.Mesh(new THREE.SphereGeometry(0.085, 12, 10), CARTILAGE);
    knee.position.set(leg.x, leg.y_from - len * 0.52, leg.z);
    g.add(knee);
    // 髌骨
    const patella = new THREE.Mesh(new THREE.SphereGeometry(0.055, 10, 8), BONE);
    patella.scale.set(1, 1.2, 0.6);
    patella.position.set(leg.x, leg.y_from - len * 0.52, leg.z + 0.14);
    g.add(patella);
    // 足骨（跗骨+跖骨，简化为几根短杆）
    for (let i = 0; i < 4; i++) {
      const meta = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.022, 0.16, 6), BONE);
      meta.rotation.x = Math.PI / 2;
      meta.position.set(leg.x - 0.09 + i * 0.06, leg.y_to + 0.05, leg.z + 0.30);
      g.add(meta);
    }
  }
  return g;
}

/** 肌肉：主要肌群用椭球近似（半透明，便于和经络叠看） */
export function buildMuscles(body) {
  const g = new THREE.Group();
  g.name = 'muscles';
  const L = body.meta.landmarks;
  const blob = (x, y, z, sx, sy, sz, rz = 0) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), MUSCLE);
    m.scale.set(sx, sy, sz);
    m.position.set(x, y, z);
    m.rotation.z = rz;
    g.add(m);
  };
  const chest = profileAt(body.profile, L.nipple);
  const waist = profileAt(body.profile, L.navel);
  const pel = profileAt(body.profile, L.pubis + 0.1);

  // 斜方肌 / 三角肌 / 胸大肌 / 腹直肌 / 背阔肌
  blob(0, L.shoulder + 0.06, chest.zc - 0.10, 0.46, 0.14, 0.16);
  for (const sgn of [-1, 1]) {
    blob(sgn * 0.46, L.shoulder - 0.02, chest.zc - 0.06, 0.14, 0.15, 0.15);
    blob(sgn * 0.26, L.nipple + 0.10, chest.zc + chest.rz * 0.72, 0.24, 0.16, 0.10);
    blob(sgn * 0.34, L.navel + 0.34, chest.zc - 0.18, 0.20, 0.30, 0.10);  // 背阔肌
    blob(sgn * 0.22, L.navel - 0.02, waist.zc + waist.rz * 0.62, 0.12, 0.26, 0.07); // 腹直肌
    blob(sgn * 0.26, L.pubis + 0.02, pel.zc - pel.rz * 0.62, 0.22, 0.20, 0.14);     // 臀大肌
  }
  // 四肢肌群
  for (const [key, arm] of Object.entries(body.limbs.arms || {})) {
    const sgn = key === 'arm_l' ? -1 : 1;
    const len = arm.x_to - arm.x_from;
    blob(sgn * (arm.x_from + len * 0.26), arm.y + 0.04, arm.z + 0.04, 0.26, 0.11, 0.11);
    blob(sgn * (arm.x_from + len * 0.70), arm.y + 0.02, arm.z, 0.22, 0.08, 0.08);
  }
  for (const [key, leg] of Object.entries(body.limbs.legs || {})) {
    const len = leg.y_from - leg.y_to;
    blob(leg.x, leg.y_from - len * 0.24, leg.z + 0.06, 0.20, 0.34, 0.18);
    blob(leg.x, leg.y_from - len * 0.72, leg.z - 0.04, 0.15, 0.24, 0.15);
  }
  return g;
}
