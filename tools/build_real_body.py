#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_real_body.py —— 用真实解剖网格（BodyParts3D）重建人体，并把 361 穴贴到真实皮肤表面

数据源
------
BodyParts3D 4.3（日本 DBCLS，CC BY-SA 2.1 JP）
  · FJ2810 = FMA7163 Skin —— 整具人体体表，102,467 顶点 / 203,382 面
  · 骨骼、肌肉：按 FMA 名称从 3,210 个解剖部件中筛出
许可：代码 MIT，网格数据 CC BY-SA 2.1 JP（署名见 DATA_LICENSE.md）

为什么要换掉程序化人体
----------------------
上一版用「剖面放样 + 球关节 + 圆柱四肢」拼出来，比例对但没有真实解剖形态，
观感就是木头人。真实网格直接把这个问题消掉。

坐标约定
--------
BodyParts3D：Z 向上，单位 mm，体高 1719.5 mm
本项目：      y 向上，z 向前，x 向右，1 单位 ≈ 0.198 m（身高 8.67 ≈ 1.70 m）

穴位贴体
--------
上游穴位坐标是 **T-pose（双臂平举）**，而 BodyParts3D 是**解剖学站姿（双臂下垂）**。
所以顺序必须是：先把手臂穴位绕肩关节转下来 → 换算到网格坐标系 → 用「最近三角面点」
投影到真实皮肤表面。直接拿 T-pose 坐标做最近点投影，手臂穴位会被吸到躯干上。

用法
----
  python3 tools/build_real_body.py --zip /path/isa_BP3D_4.0_obj_99.zip
"""
import argparse
import json
import math
import os
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SKIN_FJ = "FJ2810"          # FMA7163 Skin：整具体表
# 明显不是"骨头"的同名干扰项（睑板、软骨、韧带等）
BONE_BLACKLIST = ("eyelid", "cartilage", "ligament", "tendon", "membrane", "capsule",
                  "septum", "disc", "meniscus", "fascia", "sheath", "bursa", "plate of")
# 肌肉只要主要肌群，细小的手内肌、面肌全放进来会拖慢前端且看不清
MUSCLE_KEEP = (
    "deltoid", "pectoralis major", "rectus abdominis", "external oblique", "latissimus",
    "trapezius", "biceps brachii", "triceps brachii", "brachialis", "brachioradialis",
    "gluteus maximus", "gluteus medius", "rectus femoris", "vastus lateralis", "vastus medialis",
    "vastus intermedius", "biceps femoris", "semitendinosus", "semimembranosus",
    "gastrocnemius", "soleus", "tibialis anterior", "sternocleidomastoid", "masseter",
    "temporalis", "iliopsoas", "psoas major", "iliacus", "sartorius", "adductor longus",
    "adductor magnus", "teres major", "infraspinatus", "supraspinatus", "rhomboid",
    "serratus anterior", "erector spinae", "splenius", "semispinalis", "obliquus",
    "extensor digitorum", "flexor digitorum", "extensor carpi", "flexor carpi",
    "pectineus", "gracilis", "tensor fasciae", "piriformis", "diaphragm", "occipitalis",
    "frontalis", "orbicularis oris", "zygomaticus", "platysma", "buccinator", "myohyoid",
    "digastric", "omohyoid", "sternohyoid", "thyrohyoid", "scalenus", "longus colli",
    "longus capitis", "levator scapulae", "rhomboideus", "subscapularis", "coracobrachialis",
)

# 本项目坐标：足底 y=-5.67，头顶 y=+3.00
Y_SOLE, Y_VERTEX = -5.67, 3.00
# 上游 T-pose 手臂轴线（用于把手放下来）
ARM_PIVOT = (0.60, 1.42, -0.10)
MIDLINE_SHIFT = 0.12        # 上游数据中线偏移


import re

# 只认这几类骨名（用词边界匹配：避免 iliotibial→tibia、fibular vein→fibula、maxillary gingiva→maxilla）
BONE_TOKENS = (
    "femur", "patella", "tibia", "fibula", "talus", "calcaneus", "navicular", "cuboid",
    "cuneiform", "metatarsal", "humerus", "radius", "ulna", "scapula", "clavicle", "sternum",
    "metacarpal", "carpal", "tarsal", "sacrum", "coccyx", "ilium", "ischium", "pubis",
    "rib", "ribs", "vertebra", "vertebrae", "mandible", "maxilla", "zygomatic", "temporal",
    "parietal", "frontal", "occipital", "sphenoid", "ethmoid", "nasal", "vomer", "lacrimal",
    "palatine", "hyoid", "malleus", "incus", "stapes", "phalanx", "phalanges", "bone", "skull",
)
SOFT_TISSUE = ("artery", "vein", "nerve", "muscle", "ligament", "tendon", "fascia", "tract",
               "gingiva", "skin", "cartilage", "membrane", "capsule", "septum", "disc", "bursa",
               "sheath", "gland", "lymph", "ganglion", "set of", "part of", "ganglia",
               "aponeurosis", "retinaculum", "periosteum", "marrow", "joint", "suture")


def is_bone(name):
    """这个解剖部件到底是不是骨"""
    low = name.lower()
    if any(w in low for w in SOFT_TISSUE):
        return False
    return any(re.search(rf"\b{t}\b", low) for t in BONE_TOKENS)


BONE_KW = ("vertebra", "rib", "sternum", "clavicle", "scapula", "humerus", "radius", "ulna",
           "carpal", "metacarpal", "phalanx", "phalan", "femur", "patella", "tibia", "fibula",
           "tarsal", "metatarsal", "calcaneus", "talus", "navicular", "cuboid", "cuneiform",
           "ilium", "ischium", "pubis", "sacrum", "coccyx", "mandible", "maxilla", "zygomatic",
           "temporal", "parietal", "frontal", "occipital", "sphenoid", "ethmoid", "nasal",
           "vomer", "lacrimal", "palatine", "hyoid", "malleus", "incus", "stapes", "atlas",
           "axis", "bone")
MUS_KW = ("muscle", "biceps", "triceps", "deltoid", "pectoralis", "rectus", "oblique",
          "transversus", "trapezius", "latissimus", "rhomboid", "serratus", "erector", "gluteus",
          "sartorius", "quadriceps", "vastus", "femoris", "gastrocnemius", "soleus", "tibialis",
          "peroneus", "masseter", "temporalis", "sternocleidomastoid", "brachialis",
          "brachioradialis", "extensor", "flexor", "adductor", "abductor", "levator", "sphincter",
          "diaphragm", "intercostal", "orbicularis", "zygomaticus", "platysma", "buccinator",
          "digastric", "mylohyoid", "geniohyoid", "stylohyoid", "omohyoid", "thyrohyoid",
          "sternothyroid", "sternohyoid", "iliopsoas", "psoas", "iliacus", "piriformis",
          "coccygeus", "longus", "brevis", "teres", "infraspinatus", "supraspinatus",
          "subscapularis", "coracobrachialis", "anconeus", "popliteus", "plantaris", "gracilis",
          "pectineus", "obturator", "tensor")


def classify(name):
    n = name.lower()
    if "skin" in n and "eyelid" not in n:
        return "skin"
    if is_bone(name):
        return "bone"
    if any(k in n for k in MUS_KW):
        return "muscle"
    return "other"


def load_parts():
    """读 BodyParts3D 的部件清单（FJ / FMA / 英文名），并在本地做分类。"""
    p = os.path.abspath(os.path.join(ROOT, "..", "bp3d", "parts.json"))
    recs = json.load(open(p, encoding="utf-8"))
    for r in recs:
        r["cls"] = r.get("cls") or classify(r["name"])
    return recs


def read_obj(zf, name):
    """返回 (verts Nx3 list, faces Mx3 list, 1-based→0-based)"""
    txt = zf.read(name).decode("utf-8", "ignore")
    vs, fs = [], []
    for line in txt.splitlines():
        if line.startswith("v "):
            _, x, y, z = line.split()[:4]
            vs.append((float(x), float(y), float(z)))
        elif line.startswith("f "):
            idx = [int(tok.split("/")[0]) - 1 for tok in line.split()[1:]]
            for k in range(1, len(idx) - 1):        # 多边形三角化
                fs.append((idx[0], idx[k], idx[k + 1]))
    return vs, fs


def write_glb(path, verts, faces, name):
    """极简 glTF 2.0 二进制导出：POSITION(float32) + indices(uint32)。
    法线交给 three.js 的 computeVertexNormals() 算，省一半体积。"""
    import numpy as np
    v = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    f = np.asarray(faces, dtype=np.uint32).reshape(-1, 3)
    vb, ib = v.tobytes(), f.tobytes()
    def pad(b, a=4, fill=b"\x00"):
        return b + fill * ((a - len(b) % a) % a)
    vb, ib = pad(vb), pad(ib)
    gltf = {
        "asset": {"version": "2.0", "generator": "tcm-meridian-3d/build_real_body.py",
                  "copyright": "BodyParts3D, (c) DBCLS, CC BY-SA 2.1 JP"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [
            {"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(vb) + len(ib)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(vb), "target": 34962},
            {"buffer": 0, "byteOffset": len(vb), "byteLength": len(ib), "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": int(len(v)),
             "type": "VEC3", "min": v.min(0).tolist(), "max": v.max(0).tolist()},
            {"bufferView": 1, "componentType": 5125, "count": int(f.size), "type": "SCALAR"},
        ],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js = pad(js, fill=b" ")        # JSON 块必须用空格补齐（规范要求）
    bin_ = vb + ib
    total = 12 + 8 + len(js) + 8 + len(bin_)
    with open(path, "wb") as fh:
        fh.write(b"glTF" + struct.pack("<II", 2, total))
        fh.write(struct.pack("<I", len(js)) + b"JSON" + js)
        fh.write(struct.pack("<I", len(bin_)) + b"BIN\x00" + bin_)
    return len(v), len(f), os.path.getsize(path)


def closest_on_triangle(p, a, b, c):
    """单个点到三角形最近点（Ericson, Real-Time Collision Detection）。numpy 向量化版本在调用处。"""
    import numpy as np
    ab, ac, ap = b - a, c - a, p - a
    d1 = (ab * ap).sum(-1)
    d2 = (ac * ap).sum(-1)
    bp = p - b
    d3 = (ab * bp).sum(-1)
    d4 = (ac * bp).sum(-1)
    cp = p - c
    d5 = (ab * cp).sum(-1)
    d6 = (ac * cp).sum(-1)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    denom = va + vb + vc
    denom = np.where(np.abs(denom) < 1e-20, 1e-20, denom)
    v = vb / denom
    w = vc / denom
    out = a + ab * v[..., None] + ac * w[..., None]
    # 顶点区
    m = (d1 <= 0) & (d2 <= 0)
    out = np.where(m[..., None], a, out)
    m = (d3 >= 0) & (d4 <= d3)
    out = np.where(m[..., None], b, out)
    m = (d6 >= 0) & (d5 <= d6)
    out = np.where(m[..., None], c, out)
    # 边区
    m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t = np.where(m, d1 / np.where(d1 - d3 == 0, 1e-20, d1 - d3), 0)
    out = np.where(m[..., None], a + ab * t[..., None], out)
    m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    t = np.where(m, d2 / np.where(d2 - d6 == 0, 1e-20, d2 - d6), 0)
    out = np.where(m[..., None], a + ac * t[..., None], out)
    m = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    t = np.where(m, (d4 - d3) / np.where((d4 - d3) + (d5 - d6) == 0, 1e-20, (d4 - d3) + (d5 - d6)), 0)
    out = np.where(m[..., None], b + (c - b) * t[..., None], out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--chunk", type=int, default=20000, help="每次处理的三角面数")
    args = ap.parse_args()
    import numpy as np

    zf = zipfile.ZipFile(args.zip)
    inner = zf.namelist()[0].split("/")[0]
    path_of = lambda fj: f"{inner}/{fj}.obj"
    have = {n.split("/")[-1][:-4] for n in zf.namelist()}

    recs = load_parts()
    skin_rec = [r for r in recs if r["cls"] == "skin" and "umbilicus" not in r["name"]]
    bones = [r for r in recs if is_bone(r["name"])]
    muscles = [r for r in recs if r["cls"] == "muscle"
               and any(k in r["name"].lower() for k in MUSCLE_KEEP)
               and "eyelid" not in r["name"].lower()]
    # 同一结构常有 _M / 无后缀两份（M = 镜像），只保留本体
    bones = [r for r in bones if r["fj"] in have]
    muscles = [r for r in muscles if r["fj"] in have]

    # ── 1. 读皮肤，定朝向 ────────────────────────────────────────────
    sv, sf = read_obj(zf, path_of(SKIN_FJ))
    sv = np.asarray(sv, dtype=np.float64)
    zmin, zmax = sv[:, 2].min(), sv[:, 2].max()
    print(f"皮肤: {len(sv)} 顶点 / {len(sf)} 面；Z {zmin:.1f}~{zmax:.1f}（高 {zmax-zmin:.1f} mm）")

    # 脚趾方向 = 前方（取最低 5% 高度里 Y 的最极端侧）
    foot = sv[sv[:, 2] < zmin + 0.05 * (zmax - zmin)]
    y_lo, y_hi = np.percentile(foot[:, 1], 1), np.percentile(foot[:, 1], 99)
    front_sign = 1.0 if abs(y_hi) > abs(y_lo) else -1.0
    # 验证：鼻尖应当在同一侧
    head = sv[sv[:, 2] > zmin + 0.88 * (zmax - zmin)]
    nose_sign = 1.0 if abs(np.percentile(head[:, 1], 99)) > abs(np.percentile(head[:, 1], 1)) else -1.0
    print(f"朝向判定：脚趾→{'+Y' if front_sign>0 else '-Y'}，鼻尖→{'+Y' if nose_sign>0 else '-Y'}"
          f"{'  ✅一致' if front_sign == nose_sign else '  ⚠️不一致，以脚趾为准'}")

    # ── 2. 统一变换：BodyParts3D → 本项目坐标 ────────────────────────
    s = (Y_VERTEX - Y_SOLE) / (zmax - zmin)          # mm → 本项目单位
    cx = (sv[:, 0].min() + sv[:, 0].max()) / 2       # 中线
    cy = (sv[:, 1].min() + sv[:, 1].max()) / 2
    print(f"比例 1 单位 = {1/s*1:.1f} mm = {1/s/1000:.3f} m；中线 X={cx:.1f}，前后中心 Y={cy:.1f}")

    def to_local(arr):
        """BodyParts3D(mm, Z-up) → 本项目(y-up, z-front)"""
        out = np.empty_like(arr)
        out[:, 0] = (arr[:, 0] - cx) * s
        out[:, 1] = (arr[:, 2] - zmin) * s + Y_SOLE
        out[:, 2] = (arr[:, 1] - cy) * s * front_sign
        return out

    def to_bp3d(pts):
        """本项目 → BodyParts3D(mm)，用于最近点投影"""
        out = np.empty_like(pts)
        out[:, 0] = pts[:, 0] / s + cx
        out[:, 1] = pts[:, 2] / s * front_sign + cy
        out[:, 2] = (pts[:, 1] - Y_SOLE) / s + zmin
        return out

    # ── 3. 解析骨骼（只解析一次：贴体分区与 GLB 导出共用）─────────────
    import time
    from scipy.spatial import cKDTree
    t0 = time.time()
    bone_geo = []          # [(name, verts_bp3d, faces)]
    for r in bones:
        try:
            v, f = read_obj(zf, path_of(r["fj"]))
        except KeyError:
            continue
        if not f:
            continue
        bone_geo.append((r["name"], np.asarray(v, dtype=np.float64), f))
    print(f"骨骼解析：{len(bone_geo)} 部件 / {sum(len(f) for _,_,f in bone_geo)} 面（{time.time()-t0:.0f}s）")

    # ── 4. 体表分区：每个皮肤顶点属于哪个部位（由最近的骨决定）─────────
    def bone_group(nm):
        low = nm.lower()
        side = "r" if "right" in low else ("l" if "left" in low else None)
        if any(k in low for k in ("humerus", "radius", "ulna", "carpal", "metacarpal",
                                  "phalanx of hand", "phalanges of hand", "metacarpal bone")):
            return ("arm", side)
        if any(k in low for k in ("femur", "tibia", "fibula", "patella", "tarsal", "metatarsal",
                                  "phalanx of foot", "phalanges of foot", "calcaneus", "talus",
                                  "navicular", "cuboid", "cuneiform")):
            return ("leg", side)
        if any(k in low for k in ("frontal", "parietal", "temporal", "occipital", "sphenoid",
                                  "ethmoid", "nasal", "vomer", "zygomatic", "maxilla", "mandible",
                                  "lacrimal", "palatine", "hyoid", "skull", "incus", "malleus", "stapes")):
            return ("head", None)
        return ("torso", None)

    skinL = to_local(sv)                                  # 皮肤顶点（本项目坐标）
    triL = skinL[np.asarray(sf)]
    # 顶点法线（面积加权），用于把穴位往外推一点
    vn = np.zeros_like(skinL)
    fn = np.cross(triL[:, 1] - triL[:, 0], triL[:, 2] - triL[:, 0])
    for k in range(3):
        np.add.at(vn, np.asarray(sf)[:, k], fn)
    ln = np.linalg.norm(vn, axis=1); ln[ln == 0] = 1e-12
    vn = vn / ln[:, None]

    groups_pts = {}
    for nm, v, f in bone_geo:
        kind, side = bone_group(nm)
        vl = to_local(v)
        if side is None:                                   # 中轴骨按顶点 x 的中位定侧
            mx = float(np.median(vl[:, 0]))
            side = None if abs(mx) < 0.12 else ("r" if mx > 0 else "l")
        key = kind if side is None else f"{kind}_{side}"
        groups_pts.setdefault(key, []).append(vl)

    print("骨性分区:", {k: sum(len(a) for a in v) for k, v in sorted(groups_pts.items())})
    trees = {k: cKDTree(np.concatenate(v)) for k, v in groups_pts.items() if v}

    # 给每个皮肤顶点打部位标签
    keys = list(trees)
    dmat = np.stack([trees[k].query(skinL, k=1)[0] for k in keys], axis=1)
    labels = np.array(keys)[np.argmin(dmat, axis=1)]
    from collections import Counter
    skincnt = Counter(labels.tolist())
    print("体表分区顶点数:", dict(skincnt))
    skin_tree = {k: cKDTree(skinL[labels == k]) for k in keys if (labels == k).sum() > 50}
    skin_idx = {k: np.where(labels == k)[0] for k in keys}

    # ── 5. 穴位：T-pose → 垂手，再贴到**同一部位**的体表 ───────────────
    raw = json.load(open(os.path.join(ROOT, "data", "acupoints.json"), encoding="utf-8"))
    pts, meta, expect = [], [], []
    px, py, pz = ARM_PIVOT
    for a in raw["acupoints"]:
        q = a["pos"]
        x, y, z = q["x"] - MIDLINE_SHIFT, q["y"], q["z"]
        raw_x, raw_y = x, y
        if abs(x) > 0.62 and 0.9 < y < 1.95:              # 手臂区：绕肩关节转 -90°
            dx, dy = abs(x) - px, y - py
            x = math.copysign(px + dy, x)
            y = py - dx
        pts.append((x, y, z))
        meta.append(a)
        side = "r" if raw_x > 0 else "l"
        if abs(raw_x) > 1.05:
            expect.append(f"arm_{side}")
        elif raw_y < -2.55:
            expect.append(f"leg_{side}")
        elif raw_y > 1.95:
            expect.append("head")
        else:
            expect.append("torso")
    P = np.asarray(pts, dtype=np.float64)

    mism = Counter()
    snapped = np.zeros_like(P)
    dist = np.zeros(len(P))
    mid_mask = np.array([a["meridian_id"] in (13, 14) for a in meta])
    for i, p in enumerate(P):
        want = expect[i]
        if want not in skin_tree:                          # 该部位没有顶点 → 退回全体
            mism[want] += 1
            want = max(skin_tree, key=lambda k: skin_tree[k].n)
        gg = want
        if mid_mask[i]:                                    # 任督：只在中线附近找
            idx = skin_idx.get(gg, np.arange(len(skinL)))
            sel = idx[np.abs(skinL[idx, 0]) < 0.09]
            if len(sel) < 10:
                sel = idx
            d = np.linalg.norm(skinL[sel] - p, axis=1)
            j = int(sel[int(np.argmin(d))])
        elif gg.startswith("arm") or gg.startswith("leg"):
            # 肢体：穴位沿肢体方向的位置由 y 编码（最可靠），所以**保住 y 带**，只在环向纠正
            idx = skin_idx.get(gg, np.arange(len(skinL)))
            cand = idx[np.abs(skinL[idx, 1] - p[1]) < 0.18]
            if abs(p[0]) > 0.12:                       # 同侧、且别落到两腿/两臂之间的中线
                same = np.sign(skinL[cand, 0]) == np.sign(p[0])
                if same.sum() >= 5:
                    cand = cand[same]
            if len(cand) < 5:
                cand = idx
            d = np.linalg.norm(skinL[cand] - p, axis=1)
            j = int(cand[int(np.argmin(d))])
        else:
            _d, _j = skin_tree[gg].query(p, k=1)
            j = int(skin_idx[gg][int(_j)])
        snapped[i] = skinL[j] + vn[j] * 0.018
        if mid_mask[i]:
            snapped[i, 0] = 0.0
        dist[i] = float(np.linalg.norm(P[i] - skinL[j]))

    print(f"贴体完成（按部位约束）：平均偏差 {dist.mean()*s*1000:.1f} mm，"
          f"最大 {dist.max()*s*1000:.1f} mm" + (f"；部位缺失退回全体：{dict(mism)}" if mism else ""))
    S = snapped

    # ── 5. 导出 GLB ────────────────────────────────────────────────
    mdl = os.path.join(ROOT, "demo", "models")
    os.makedirs(mdl, exist_ok=True)
    allv, allf = [], []
    for v, f in ((sv, sf),):
        allv.append(to_local(np.asarray(v, dtype=np.float64)).tolist())
        allf.append(f)
    nv, nf, sz = write_glb(os.path.join(mdl, "skin.glb"), allv[0], allf[0], "skin")
    print(f"skin.glb: {nv} 顶点 / {nf} 面 / {sz/1e6:.2f} MB")

    # 骨骼：复用已解析的 bone_geo
    gv, gf, base = [], [], 0
    for nm, v, f in bone_geo:
        gv.extend(to_local(v).tolist())
        gf.extend([(a + base, b + base, c + base) for a, b, c in f])
        base += len(v)
    nv, nf, sz = write_glb(os.path.join(mdl, "skeleton.glb"), gv, gf, "skeleton")
    print(f"skeleton.glb: {len(bone_geo)} 个部件 / {nv} 顶点 / {nf} 面 / {sz/1e6:.2f} MB")

    # 肌肉：按需解析
    gv, gf, base, used = [], [], 0, 0
    for r in muscles:
        try:
            v, f = read_obj(zf, path_of(r["fj"]))
        except KeyError:
            continue
        if not v or not f:
            continue
        gv.extend(to_local(np.asarray(v, dtype=np.float64)).tolist())
        gf.extend([(a + base, b + base, c + base) for a, b, c in f])
        base += len(v); used += 1
    nv, nf, sz = write_glb(os.path.join(mdl, "muscles.glb"), gv, gf, "muscles")
    print(f"muscles.glb: {used} 个部件 / {nv} 顶点 / {nf} 面 / {sz/1e6:.2f} MB")

    # ── 6. 写 body.json v2 ─────────────────────────────────────────
    out_pts = []
    for a, p in zip(meta, S):
        out_pts.append({
            "id": a["id"], "py": a["py"], "name": a["name"],
            "meridian_id": a["meridian_id"], "meridian": a["meridian"],
            "pos": {"x": round(float(p[0]), 4), "y": round(float(p[1]), 4), "z": round(float(p[2]), 4)},
            "shiyi": a.get("shiyi", ""), "func": a.get("func", ""), "location": a.get("location", ""),
        })
    body = {
        "meta": {
            "version": 2,
            "source": "BodyParts3D 4.3 (DBCLS, CC BY-SA 2.1 JP) + data/acupoints.json (CC BY 4.0)",
            "generator": "tools/build_real_body.py",
            "midline_shift": MIDLINE_SHIFT,
            "arm_pivot": list(ARM_PIVOT),
            "scale": {"unit_to_mm": round(1 / s, 2), "unit_to_m": round(1 / s / 1000, 4)},
            "_bp3d_cx": round(float(cx), 3), "_bp3d_cy": round(float(cy), 3),
            "_bp3d_zmin": round(float(zmin), 3),
            "orientation": {"up": "+y", "front": "+z", "right": "+x",
                            "front_sign_bp3d": front_sign},
            "height": round(Y_VERTEX - Y_SOLE, 2),
            "models": {"skin": "demo/models/skin.glb",
                       "skeleton": "demo/models/skeleton.glb",
                       "muscles": "demo/models/muscles.glb"},
            "snap": {"mean_mm": round(float(dist.mean()) * 1 / s, 1),
                     "max_mm": round(float(dist.max()) * 1 / s, 1)},
            "region_labels": {k: int(v) for k, v in skincnt.items()},
            "note": ("穴位坐标已从 T-pose 转换到解剖学站姿，并按**体表部位分区**贴到真实皮肤"
                     "（手臂穴只贴手臂、腿穴只贴腿），避免手垂在大腿旁时被吸到大腿上"),
        },
        "acupoints": out_pts,
    }
    json.dump(body, open(os.path.join(ROOT, "data", "body.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"✅ data/body.json v2 写出（{os.path.getsize(os.path.join(ROOT,'data','body.json'))/1024:.0f} KB）")


if __name__ == "__main__":
    main()
