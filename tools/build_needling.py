#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_needling.py —— 给 361 穴算「骨性标志 + 进针几何」

为什么是这个做法
----------------
教材上的「直刺 0.5~1 寸」是**临床经验值**，属于有出处的医学结论；本仓库没有该数据的
可靠可引用来源，**不编造数字**。本脚本给的是**从真实解剖网格实测出来的几何量**：

  1. 逐穴的体表法向（= 进针方向）
  2. 沿进针方向从皮肤到**最近骨面**的距离（mm）——这是"再往里就是骨"的几何上限
  3. 命中的骨性结构名称（如足三里 → 胫骨，膻中 → 胸骨，百会 → 颅骨）

这三项都能从数据复现、可被任何人用同一份网格验算，所以可以写进产品里；
它们**不是**医疗操作参数，界面上必须写清楚。

输入
----
  data/body.json        贴体后的 361 穴坐标（本项目坐标系）
  demo/models/skin.glb  皮肤三角面（本项目坐标系）
  BodyParts3D zip       骨骼部件（BP3D 坐标系，本脚本内部做同一套换算）

输出
----
  data/needling.json

用法
----
  python3 tools/build_needling.py --zip /path/isa_BP3D_4.0_obj_99.zip
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
sys.path.insert(0, HERE)
from build_real_body import classify, is_bone   # 复用同一套部件分类/骨骼判定，避免口径分叉

# 骨名中英映射（按关键词，命中即取第一条）——只为界面可读，不改变几何事实
BONE_ZH = [
    ("femur", "股骨"), ("patella", "髌骨"), ("tibia", "胫骨"), ("fibula", "腓骨"),
    ("talus", "距骨"), ("calcaneus", "跟骨"), ("navicular", "足舟骨"), ("cuboid", "骰骨"),
    ("cuneiform", "楔骨"), ("metatarsal", "跖骨"), ("phalanx of foot", "趾骨"),
    ("humerus", "肱骨"), ("radius", "桡骨"), ("ulna", "尺骨"), ("scapula", "肩胛骨"),
    ("clavicle", "锁骨"), ("sternum", "胸骨"), ("metacarpal", "掌骨"),
    ("phalanx of hand", "指骨"), ("carpal", "腕骨"),
    ("sacrum", "骶骨"), ("coccyx", "尾骨"), ("ilium", "髂骨"), ("ischium", "坐骨"),
    ("pubis", "耻骨"), ("pelvi", "骨盆"),
    ("cervical vertebra", "颈椎"), ("thoracic vertebra", "胸椎"), ("lumbar vertebra", "腰椎"),
    ("vertebra", "椎骨"), ("rib", "肋骨"),
    ("mandible", "下颌骨"), ("maxilla", "上颌骨"), ("zygomatic", "颧骨"), ("temporal", "颞骨"),
    ("parietal", "顶骨"), ("frontal", "额骨"), ("occipital", "枕骨"), ("sphenoid", "蝶骨"),
    ("ethmoid", "筛骨"), ("nasal", "鼻骨"), ("vomer", "犁骨"), ("lacrimal", "泪骨"),
    ("palatine", "腭骨"), ("hyoid", "舌骨"), ("skull", "颅骨"),
]
BONE_BLACKLIST = ("eyelid", "cartilage", "ligament", "tendon", "membrane", "capsule",
                  "septum", "disc", "meniscus", "fascia", "sheath", "bursa", "plate of")


def zh_name(en):
    low = en.lower()
    for k, zh in BONE_ZH:
        if k in low:
            return zh
    return en


def read_obj(zf, name):
    txt = zf.read(name).decode("utf-8", "ignore")
    vs, fs = [], []
    for line in txt.splitlines():
        if line.startswith("v "):
            _, x, y, z = line.split()[:4]
            vs.append((float(x), float(y), float(z)))
        elif line.startswith("f "):
            idx = [int(tok.split("/")[0]) - 1 for tok in line.split()[1:]]
            for k in range(1, len(idx) - 1):
                fs.append((idx[0], idx[k], idx[k + 1]))
    return vs, fs


def read_glb(path):
    import numpy as np
    raw = open(path, "rb").read()
    jlen, _ = struct.unpack("<I4s", raw[12:20])
    gltf = json.loads(raw[20:20 + jlen].decode("utf-8").rstrip("\x00 "))
    off = 20 + jlen
    blen, _ = struct.unpack("<I4s", raw[off:off + 8])
    binc = raw[off + 8: off + 8 + blen]
    acc, pv = gltf["accessors"], gltf["bufferViews"]
    prim = gltf["meshes"][0]["primitives"][0]
    a0, i0 = acc[prim["attributes"]["POSITION"]], acc[prim["indices"]]
    v0, b1 = pv[a0["bufferView"]], pv[i0["bufferView"]]
    v = np.frombuffer(binc[v0["byteOffset"]:v0["byteOffset"] + v0["byteLength"]],
                      dtype=np.float32).reshape(-1, 3)
    f = np.frombuffer(binc[b1["byteOffset"]:b1["byteOffset"] + b1["byteLength"]],
                      dtype=np.uint32).reshape(-1, 3)
    return v, f


def ray_tri_hits(origin, direction, T):
    """Möller–Trumbore，向量化：T 为 (M,3,3)。返回 (命中距离数组, 命中掩码)"""
    import numpy as np
    e1 = T[:, 1] - T[:, 0]
    e2 = T[:, 2] - T[:, 0]
    p = np.cross(direction, e2)                     # direction (3,)
    det = (e1 * p).sum(-1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    tvec = origin - T[:, 0]
    u = (tvec * p).sum(-1) * inv
    q = np.cross(tvec, e1)
    v = (q * direction).sum(-1) * inv
    t = (q * e2).sum(-1) * inv
    hit = ok & (u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
    return t, hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    args = ap.parse_args()
    import numpy as np
    import time

    body = json.load(open(os.path.join(ROOT, "data", "body.json"), encoding="utf-8"))
    pts = body["acupoints"]
    meta = body["meta"]
    s = 1.0 / meta["scale"]["unit_to_mm"]              # 本地单位 → mm
    front_sign = meta["orientation"]["front_sign_bp3d"]
    P = np.array([[p["pos"]["x"], p["pos"]["y"], p["pos"]["z"]] for p in pts], dtype=np.float64)

    # ── 皮肤三角面 ──────────────────────────────────────────────────
    sv, sf = read_glb(os.path.join(ROOT, "demo", "models", "skin.glb"))
    sv = sv.astype(np.float64)
    tri = sv[sf].astype(np.float64)                   # (M,3,3)
    print(f"皮肤：{len(sv)} 顶点 / {len(tri)} 面")

    # 每点最近三角面 → 面法向（向外）→ 进针方向
    cen = tri.mean(1)
    # 内部参考点：同高度体表横截面的中心（用于判断法向朝内还是朝外）
    # 不能用「点 − 最近三角面重心」——点在表面上，那个向量几乎是切向的，判定会随机翻。
    slab_cache = {}
    def section_center(y, x):
        side = 0 if abs(x) < 0.12 else (1 if x > 0 else -1)
        key = (round(y / 0.15), side)
        if key not in slab_cache:
            m = np.abs(sv[:, 1] - y) < 0.15
            if side:                                   # 肢体：只取同侧顶点，中心落在该肢体轴线上
                m &= (np.sign(sv[:, 0]) == side)
            slab_cache[key] = sv[m].mean(0) if m.sum() > 50 else sv.mean(0)
        return slab_cache[key]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    nl = np.linalg.norm(nrm, axis=1)
    nl[nl == 0] = 1e-12
    nrm = nrm / nl[:, None]

    # ── 骨骼部件（保留每块骨的名字）──────────────────────────────────
    parts = json.load(open(os.path.abspath(os.path.join(ROOT, "..", "bp3d", "parts.json")), encoding="utf-8"))
    zf = zipfile.ZipFile(args.zip)
    inner = zf.namelist()[0].split("/")[0]
    have = {n.split("/")[-1][:-4] for n in zf.namelist()}
    bones = [r for r in parts if is_bone(r["name"]) and r["fj"] in have]

    # BP3D → 本地坐标（与 build_real_body.py 完全同一套换算）
    s2 = 1.0 / meta["scale"]["unit_to_mm"]        # 单位/mm（注意方向：不是 mm/单位）
    # 反推：skin.glb 顶点是 to_local 之后的，所以这里重建变换参数
    cx = meta.get("_bp3d_cx"); cy = meta.get("_bp3d_cy"); zmin = meta.get("_bp3d_zmin")
    if cx is None:
        # body.json 里没存 BP3D 原点，这里用与生成时一致的方式复算：
        # para 由 BP3D 皮肤决定，重新读一次 BP3D 皮肤算参数（保证一致）
        bpv, _ = read_obj(zf, f"{inner}/FJ2810.obj")
        bpv = np.asarray(bpv, dtype=np.float64)
        cx = (bpv[:, 0].min() + bpv[:, 0].max()) / 2
        cy = (bpv[:, 1].min() + bpv[:, 1].max()) / 2
        zmin, zmax = bpv[:, 2].min(), bpv[:, 2].max()
        Y_SOLE = -5.67
        s2 = (3.00 - Y_SOLE) / (zmax - zmin)      # 单位/mm
    Y_SOLE = -5.67

    def to_local(a):
        out = np.empty_like(a)
        out[:, 0] = (a[:, 0] - cx) * s2
        out[:, 1] = (a[:, 2] - zmin) * s2 + Y_SOLE
        out[:, 2] = (a[:, 1] - cy) * s2 * front_sign
        return out

    allT, allName, allV, allVName = [], [], [], []
    t0 = time.time()
    for r in bones:
        try:
            v, f = read_obj(zf, f"{inner}/{r['fj']}.obj")
        except KeyError:
            continue
        if not f:
            continue
        vv = to_local(np.asarray(v, dtype=np.float64))
        allT.append(vv[np.asarray(f)])
        allName.append(r["name"])
        allV.append(vv)
        allVName.append(r["name"])
    BT = np.concatenate(allT).astype(np.float64)
    print(f"骨骼：{len(allName)} 部件 / {len(BT)} 面（解析 {time.time()-t0:.0f}s）")
    # 每面的部件索引
    pid = np.concatenate([np.full(len(t), i, dtype=np.int32) for i, t in enumerate(allT)])
    bcen = BT.mean(1)

    R = 0.30                    # 预筛半径（本地单位 ≈ 6 cm）
    out = []
    t0 = time.time()
    for i, p in enumerate(P):
        # 1) 最近皮肤面 → 法向
        near_skin = np.linalg.norm(cen - p, axis=1) < 0.25
        js = np.where(near_skin)[0]
        if len(js) == 0:
            js = np.arange(len(tri))
        d_skin = np.linalg.norm(cen[js] - p, axis=1)
        k = js[int(np.argmin(d_skin))]
        n = nrm[k]
        # 确保法向朝外：与「点 − 同高度截面中心」同向
        if np.dot(n, p - section_center(p[1], p[0])) < 0:
            n = -n
        inward = -n

        # 2) 最近的骨（按顶点距离，同侧优先）——这是「骨性标志」的客观依据
        side = 0 if abs(p[0]) < 0.12 else (1 if p[0] > 0 else -1)
        best_d, bone_en = np.inf, None
        for vv, nm in zip(allV, allVName):
            if not (np.abs(vv[:, 1] - p[1]) < R).any():
                continue
            dmin = float(np.linalg.norm(vv - p, axis=1).min())
            if side and (np.sign(np.median(vv[:, 0])) != side) and abs(np.median(vv[:, 0])) > 0.12:
                continue                                   # 别把对侧肢体的骨算进来
            if dmin < best_d:
                best_d, bone_en = dmin, nm
        nearest_mm = best_d * meta["scale"]["unit_to_mm"] if bone_en else None

        # 3) 沿进针方向的第一块骨：只有和「最近骨」是同一块才采信，
        #    否则说明射线穿到了别的部位（例如手垂在大腿旁，射线打到胫骨），一律不报。
        dist_mm = None
        near_b = np.linalg.norm(bcen - p, axis=1) < R
        jb = np.where(near_b)[0]
        if len(jb):
            t, hit = ray_tri_hits(p, inward, BT[jb])
            if hit.any():
                idx = np.where(hit)[0]
                bi = idx[int(np.argmin(t[idx]))]
                hit_name = allName[int(pid[jb[bi]])]
                if bone_en and hit_name == bone_en:
                    dist_mm = float(t[bi]) * meta["scale"]["unit_to_mm"]
        out.append({
            "id": pts[i]["id"], "name": pts[i]["name"],
            "meridian": pts[i]["meridian"],
            "normal": [round(float(x), 4) for x in n],
            "inward": [round(float(x), 4) for x in inward],
            "bone_en": bone_en, "bone_zh": zh_name(bone_en) if bone_en else None,
            "nearest_bone_mm": round(nearest_mm, 1) if nearest_mm is not None else None,
            "needle_to_bone_mm": round(dist_mm, 1) if dist_mm is not None else None,
        })
        if (i + 1) % 60 == 0:
            print(f"  {i+1}/{len(P)}  {time.time()-t0:.0f}s")

    ok = [o for o in out if o["nearest_bone_mm"] is not None]
    need_ok = [o for o in out if o["needle_to_bone_mm"] is not None]
    data = {
        "meta": {
            "generator": "tools/build_needling.py",
            "source": "BodyParts3D 4.3 皮肤+骨骼网格（CC BY-SA 2.1 JP）实测",
            "CRITICAL": ("本数据是**模型几何实测值**：沿穴位体表法向从皮肤到最近骨面的距离，"
                         "以及命中的骨性结构。它不是教材的进针深度，也不是医疗操作参数。"),
            "units": "mm（距离）/ 本地单位向量（方向）",
            "coverage": f"最近骨可判定 {len(ok)}/{len(out)}；射线触骨与最近骨一致 {len(need_ok)}/{len(out)}",
            "radius_prefilter": R,
        },
        "points": out,
    }
    json.dump(data, open(os.path.join(ROOT, "data", "needling.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))

    # ── 摘要 ──────────────────────────────────────────────────────
    if not ok:
        print("❌ 最近骨全部未命中，检查骨骼筛选与坐标换算")
        sys.exit(1)
    ds = sorted(o["nearest_bone_mm"] for o in ok)
    print(f"\n最近骨可判定 {len(ok)}/{len(out)}；点→骨距离 中位 {ds[len(ds)//2]:.1f} mm，"
          f"范围 {ds[0]:.1f}~{ds[-1]:.1f} mm；射线触骨一致 {len(need_ok)} 穴")
    from collections import Counter
    print("下方骨性结构 Top10:", Counter(o["bone_zh"] for o in ok).most_common(10))
    for nm in ("足三里", "膻中", "百会", "合谷", "三阴交", "风池"):
        for o in out:
            if o["name"] == nm:
                print(f"  {nm}: 最近骨 {o['bone_zh']} {o['nearest_bone_mm']} mm · 沿法向触骨 {o['needle_to_bone_mm']} mm")
    print(f"✅ 写出 data/needling.json（{os.path.getsize(os.path.join(ROOT,'data','needling.json'))/1024:.0f} KB）")


if __name__ == "__main__":
    main()
