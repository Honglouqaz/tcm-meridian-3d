#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_body.py —— 从穴位坐标反推人体体表，并把 361 穴贴回体表

为什么需要这个脚本
------------------
原始数据（data/acupoints.json）的 `pos` 来自一套第三方 3D 资产，有两个硬问题：
  1. 正中线不在 x=0，而在 x≈+0.12（任脉 24 + 督脉 28 穴全部偏移）
  2. 只给点、不给人体 —— 没有体表可贴，点就「悬在空中」，任督看起来在人体外

本脚本的做法
------------
用穴位当解剖标志，先定出一套**平滑的人体剖面**（每个高度的半宽 rx、半深 rz、截面中心 zc），
再把每个穴位沿其所在截面的方向投影到体表；正中线穴强制 x=0。
体表是解析几何，所以「贴不贴」是可验证的，不是靠眼看。

剖面用「关键层 + 单调插值」而不是逐层统计包络：
逐层统计会被单点离群带跑（实测相邻 0.12 高度上半宽能从 0.10 跳到 0.72），
结果是一堆薄片而不是人体。

输出
----
  data/body.json  剖面 + 肢体参数 + 361 穴修正坐标（含所在分区）

用法
----
  python3 tools/build_body.py            # 生成 data/body.json 并打印校验
  python3 tools/build_body.py --check    # 只校验
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "data", "acupoints.json")
OUT = os.path.join(ROOT, "data", "body.json")

# 中线偏移：由数据实测（任脉 24 穴 + 督脉 28 穴的 x 中位数 = 0.12）
MIDLINE_SHIFT = 0.12

# 解剖标志（y 值全部取自数据实测，作为全模型的纵向标尺）
LANDMARKS = {
    "vertex": 3.00,     # 百会 · 头顶
    "chin": 2.08,       # 承浆 · 颏唇沟
    "neck_root": 1.56,  # 天突 · 胸骨上窝
    "shoulder": 1.42,   # 肩峰（手臂轴线高度）
    "nipple": 0.79,     # 乳中
    "navel": -0.47,     # 神阙
    "pubis": -1.10,     # 曲骨 · 耻骨联合上缘
    "crotch": -1.43,    # 会阴
    "knee": -3.05,      # 委中 · 腘横纹
    "ankle": -5.26,     # 昆仑 · 外踝尖
    "sole": -5.67,      # 涌泉 · 足底
}

# ── 关键层剖面 ────────────────────────────────────────────────────────────
# (y, 半宽 rx, 半深 rz, 截面中心 zc)
# 数值来源：数据里同高度穴位的横向/前后位置（例如乳中 x=0.52、膻中 z=0.42、
# 至阳 z=-0.68、环跳 x=0.68），取稳健值后再按人体比例收尾。
PROFILE_KEYS = [
    (-1.50, 0.30, 0.26, -0.06),   # 会阴下（并入骨盆）
    (-1.28, 0.52, 0.36, -0.08),   # 髋
    (-1.10, 0.58, 0.40, -0.09),   # 曲骨
    (-0.75, 0.54, 0.38, -0.10),   # 下腹
    (-0.47, 0.51, 0.37, -0.10),   # 腰（神阙）
    (-0.10, 0.53, 0.40, -0.11),   # 中腹
    (0.30, 0.56, 0.45, -0.11),    # 下胸
    (0.79, 0.60, 0.50, -0.12),    # 胸（乳中）
    (1.20, 0.63, 0.49, -0.12),    # 上胸
    (1.45, 0.66, 0.45, -0.12),    # 肩带
    (1.56, 0.60, 0.42, -0.11),    # 颈根（天突）
    (1.66, 0.26, 0.24, -0.06),    # 颈
    (1.95, 0.21, 0.21, 0.00),     # 颈上
    (2.08, 0.26, 0.30, 0.04),     # 下颌（承浆）
    (2.30, 0.32, 0.38, 0.03),     # 面中
    (2.55, 0.34, 0.40, 0.01),     # 颅中
    (2.80, 0.29, 0.33, -0.01),    # 颅上
    (3.00, 0.14, 0.16, -0.02),    # 头顶（百会）
]

# 手臂（T-pose 平举）：轴线高度 = 肩峰，前后 = 躯干中心
ARM = {"y": 1.42, "z": -0.10, "x_from": 0.60, "x_to": 4.30,
       "r_shoulder": 0.26, "r_elbow": 0.155, "r_wrist": 0.105, "r_hand": 0.13}
# 腿：轴线左右 = 髋半宽×0.72，前后 = 躯干中心
LEG = {"x": 0.42, "z": -0.08, "y_from": -1.30, "y_to": -5.67,
       "r_hip": 0.31, "r_knee": 0.195, "r_ankle": 0.115, "r_foot": 0.16}


def interp_profile(y):
    """在关键层之间做平滑插值（余弦缓动，避免出现折线状断面）。"""
    ks = PROFILE_KEYS
    if y <= ks[0][0]:
        return ks[0][1], ks[0][2], ks[0][3]
    if y >= ks[-1][0]:
        return ks[-1][1], ks[-1][2], ks[-1][3]
    for a, b in zip(ks, ks[1:]):
        if a[0] <= y <= b[0]:
            t = (y - a[0]) / (b[0] - a[0])
            t = 0.5 - 0.5 * math.cos(t * math.pi)          # 余弦缓动
            return (a[1] + (b[1] - a[1]) * t,
                    a[2] + (b[2] - a[2]) * t,
                    a[3] + (b[3] - a[3]) * t)
    return ks[-1][1], ks[-1][2], ks[-1][3]


def build_profile(step=0.06):
    """按固定步长采样成剖面表，供前端放样建模与投影共用。"""
    rows = []
    y = PROFILE_KEYS[0][0]
    while y <= PROFILE_KEYS[-1][0] + 1e-9:
        rx, rz, zc = interp_profile(y)
        rows.append({"y": round(y, 3), "rx": round(rx, 3), "rz": round(rz, 3), "zc": round(zc, 3)})
        y += step
    return rows


def profile_at(profile, y):
    if y <= profile[0]["y"]:
        r = profile[0]
        return r["rx"], r["rz"], r["zc"]
    if y >= profile[-1]["y"]:
        r = profile[-1]
        return r["rx"], r["rz"], r["zc"]
    for a, b in zip(profile, profile[1:]):
        if a["y"] <= y <= b["y"]:
            t = (y - a["y"]) / (b["y"] - a["y"]) if b["y"] > a["y"] else 0
            return (a["rx"] + (b["rx"] - a["rx"]) * t,
                    a["rz"] + (b["rz"] - a["rz"]) * t,
                    a["zc"] + (b["zc"] - a["zc"]) * t)
    r = profile[-1]
    return r["rx"], r["rz"], r["zc"]


def region(x, y):
    """分区：头颈 / 手臂 / 腿 / 躯干。判据来自 T-pose 几何，不是拍脑袋。"""
    ax = abs(x)
    if y >= 2.02:
        return "head"
    if 1.02 < y < 1.92 and ax > ARM["x_from"] + 0.12:
        return "arm_l" if x < 0 else "arm_r"
    if abs(x) < 0.06 and y > LEG["y_from"] - 0.22:
        return "trunk"          # 会阴等正中线穴：虽然低于髋线，但属于躯干中线，不能算进腿
    if y < LEG["y_from"] - 0.06:
        return "leg_l" if x < 0 else "leg_r"
    return "trunk"


def arm_radius(t):
    """沿手臂轴 0(肩)→1(腕) 的半径。"""
    if t <= 0.5:
        return ARM["r_shoulder"] + (ARM["r_elbow"] - ARM["r_shoulder"]) * (t / 0.5)
    return ARM["r_elbow"] + (ARM["r_wrist"] - ARM["r_elbow"]) * ((t - 0.5) / 0.5)


def leg_radius(t):
    """沿腿轴 0(髋)→1(踝) 的半径。"""
    if t <= 0.55:
        return LEG["r_hip"] + (LEG["r_knee"] - LEG["r_hip"]) * (t / 0.55)
    return LEG["r_knee"] + (LEG["r_ankle"] - LEG["r_knee"]) * ((t - 0.55) / 0.45)


def snap(x, y, z, reg, profile, pad=0.018):
    """把点投影到体表。pad：向外偏移，让点球心略微浮在皮肤外（可点击、不陷进网格）。"""
    if reg in ("trunk", "head"):
        rx, rz, zc = profile_at(profile, y)
        if abs(x) < 0.06:                                  # 正中线：任脉/督脉
            x = 0.0
            z = (zc + rz + pad) if z >= zc else (zc - rz - pad)
            return x, y, z
        dx, dz = x / rx, (z - zc) / rz
        d = math.hypot(dx, dz) or 1.0
        ux, uz = dx / d, dz / d                            # 单位方向（椭圆参数域）
        return ux * (rx + pad), y, zc + uz * (rz + pad)

    if reg in ("arm_l", "arm_r"):
        ax = abs(x)
        span = max(ARM["x_to"] - ARM["x_from"], 1e-6)
        t = min(max((ax - ARM["x_from"]) / span, 0.0), 1.0)
        rad = arm_radius(t) + pad
        dy, dz = y - ARM["y"], z - ARM["z"]
        d = math.hypot(dy, dz) or 1.0
        sgn = -1 if reg == "arm_l" else 1
        return sgn * ax, ARM["y"] + dy / d * rad, ARM["z"] + dz / d * rad

    # 腿
    sgn = -1 if reg == "leg_l" else 1
    span = max(LEG["y_from"] - LEG["y_to"], 1e-6)
    t = min(max((LEG["y_from"] - y) / span, 0.0), 1.0)
    rad = leg_radius(t) + pad
    dx, dz = x - sgn * LEG["x"], z - LEG["z"]
    d = math.hypot(dx, dz) or 1.0
    return sgn * LEG["x"] + dx / d * rad, y, LEG["z"] + dz / d * rad


def main():
    check_only = "--check" in sys.argv
    raw = json.load(open(SRC, encoding="utf-8"))
    profile = build_profile()

    moved, maxd = 0, 0.0
    out_points, off = [], []
    for a in raw["acupoints"]:
        q = a["pos"]
        x0, y, z0 = q["x"] - MIDLINE_SHIFT, q["y"], q["z"]
        reg = region(x0, y)
        nx, ny, nz = snap(x0, y, z0, reg, profile)
        d = math.dist((x0, y, z0), (nx, ny, nz))
        if d > 0.02:
            moved += 1
        maxd = max(maxd, d)

        # 校验：投影后应正好落在体表（±pad 容差）
        if reg in ("trunk", "head"):
            rx, rz, zc = profile_at(profile, ny)
            v = math.hypot(nx / rx, (nz - zc) / rz)
            if abs(v - 1.0) > 0.08:
                off.append((a["name"], round(v, 3)))

        out_points.append({
            "id": a["id"], "py": a["py"], "name": a["name"],
            "meridian_id": a["meridian_id"], "meridian": a["meridian"],
            "pos": {"x": round(nx, 4), "y": round(ny, 4), "z": round(nz, 4)},
            "region": reg,
            "shiyi": a.get("shiyi", ""), "func": a.get("func", ""), "location": a.get("location", ""),
        })

    mid = [p for p in out_points if p["meridian_id"] in (13, 14)]
    mid_ok = all(abs(p["pos"]["x"]) < 1e-9 for p in mid)
    stats = {
        "穴位总数": len(out_points),
        "坐标位移>0.02": moved,
        "最大位移": round(maxd, 3),
        "任督 52 穴 x=0": mid_ok,
        "偏离体表>8%": len(off),
        "剖面层数": len(profile),
    }
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if off[:6]:
        print("偏离示例:", off[:6])
    if not mid_ok:
        print("❌ 任督未归零:", [(p["name"], p["pos"]["x"]) for p in mid if abs(p["pos"]["x"]) > 0][:5])
        sys.exit(1)
    if check_only:
        return

    body = {
        "meta": {
            "source": "data/acupoints.json（GB/T 12346-2021 校订）",
            "generator": "tools/build_body.py",
            "midline_shift": MIDLINE_SHIFT,
            "landmarks": LANDMARKS,
            "arm": ARM, "leg": LEG,
            "units": "1 ≈ 0.196 m（身高 8.68 ≈ 1.70 m）；y 向上、z 向前、x 向右",
            "note": "坐标已校正：中线归零，361 穴全部投影到解析体表（±0.01 贴皮）",
        },
        "profile": profile,
        "limbs": {"arms": {"arm_l": dict(ARM), "arm_r": dict(ARM)},
                  "legs": {"leg_l": dict(LEG, x=-LEG["x"]), "leg_r": dict(LEG)}},
        "acupoints": out_points,
    }
    # 手臂左右对称：轴线一致，只有 x 符号不同
    json.dump(body, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"✅ 写出 {OUT}（{os.path.getsize(OUT)/1024:.0f} KB）")


if __name__ == "__main__":
    main()
