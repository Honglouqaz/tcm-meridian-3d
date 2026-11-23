#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py —— 校验 data/body.json 的穴位位置是否真的贴体表、任督是否归零

跑法：python3 tools/verify.py        （退出码 0 = 全过）
这项检查是「可复现」的关键：不靠看图，靠算。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BODY = os.path.join(ROOT, "data", "body.json")

# GB/T 12346-2021 十四经穴数（合计 361）
EXPECT = {1: 11, 2: 20, 3: 45, 4: 21, 5: 9, 6: 19, 7: 67, 8: 27,
          9: 9, 10: 23, 11: 44, 12: 14, 13: 24, 14: 28}


def profile_at(prof, y):
    if y <= prof[0]["y"]:
        r = prof[0]
        return r["rx"], r["rz"], r["zc"]
    if y >= prof[-1]["y"]:
        r = prof[-1]
        return r["rx"], r["rz"], r["zc"]
    for a, b in zip(prof, prof[1:]):
        if a["y"] <= y <= b["y"]:
            t = (y - a["y"]) / (b["y"] - a["y"]) if b["y"] > a["y"] else 0
            return (a["rx"] + (b["rx"] - a["rx"]) * t,
                    a["rz"] + (b["rz"] - a["rz"]) * t,
                    a["zc"] + (b["zc"] - a["zc"]) * t)
    r = prof[-1]
    return r["rx"], r["rz"], r["zc"]


def main():
    body = json.load(open(BODY, encoding="utf-8"))
    prof, meta = body["profile"], body["meta"]
    arm, leg = meta["arm"], meta["leg"]
    pts = body["acupoints"]
    fails = []

    # 1) 穴数
    if len(pts) != 361:
        fails.append(f"穴位总数 {len(pts)} ≠ 361")
    counts = {}
    for p in pts:
        counts[p["meridian_id"]] = counts.get(p["meridian_id"], 0) + 1
    for mid, n in EXPECT.items():
        if counts.get(mid, 0) != n:
            fails.append(f"经络 {mid} 穴数 {counts.get(mid, 0)} ≠ {n}")

    # 2) 任督归零
    mid_pts = [p for p in pts if p["meridian_id"] in (13, 14)]
    bad_mid = [p["name"] for p in mid_pts if abs(p["pos"]["x"]) > 1e-9]
    if bad_mid:
        fails.append(f"任督未归中线 {len(bad_mid)} 个：{bad_mid[:5]}")

    # 3) 全部贴体表：躯干/头按椭圆、手臂按轴、腿按轴
    pad = 0.018
    far = []
    for p in pts:
        x, y, z = p["pos"]["x"], p["pos"]["y"], p["pos"]["z"]
        r = p["region"]
        if r in ("trunk", "head"):
            rx, rz, zc = profile_at(prof, y)
            v = math.hypot(x / (rx + pad), (z - zc) / (rz + pad))
            if abs(v - 1) > 0.05:
                far.append((p["name"], r, round(v, 3)))
        elif r in ("arm_l", "arm_r"):
            span = arm["x_to"] - arm["x_from"]
            t = min(max((abs(x) - arm["x_from"]) / span, 0), 1)
            rad = (arm["r_shoulder"] + (arm["r_elbow"] - arm["r_shoulder"]) * (t / 0.5)) if t <= 0.5 \
                else (arm["r_elbow"] + (arm["r_wrist"] - arm["r_elbow"]) * ((t - 0.5) / 0.5))
            d = math.hypot(y - arm["y"], z - arm["z"])
            if abs(d - (rad + pad)) > 0.05:
                far.append((p["name"], r, round(d - rad, 3)))
        else:
            span = leg["y_from"] - leg["y_to"]
            t = min(max((leg["y_from"] - y) / span, 0), 1)
            rad = (leg["r_hip"] + (leg["r_knee"] - leg["r_hip"]) * (t / 0.55)) if t <= 0.55 \
                else (leg["r_knee"] + (leg["r_ankle"] - leg["r_knee"]) * ((t - 0.55) / 0.45))
            cx = leg["x"] if x > 0 else -leg["x"]
            d = math.hypot(x - cx, z - leg["z"])
            if abs(d - (rad + pad)) > 0.05:
                far.append((p["name"], r, round(d - rad, 3)))
    if far:
        fails.append(f"离体表超差 {len(far)} 个：{far[:5]}")

    # 4) 身体包围盒合理性（身高、臂展、厚度）
    ys = [p["pos"]["y"] for p in pts]
    xs = [p["pos"]["x"] for p in pts]
    zs = [p["pos"]["z"] for p in pts]
    if not (8.4 < (max(ys) - min(ys)) < 9.0):
        fails.append(f"身高异常 {max(ys)-min(ys):.2f}")
    if not (8.0 < (max(xs) - min(xs)) < 9.2):
        fails.append(f"臂展异常 {max(xs)-min(xs):.2f}")

    print(json.dumps({
        "穴位": len(pts), "经脉": len(counts),
        "任督中线": len(mid_pts), "离体表超差": len(far),
        "身高": round(max(ys) - min(ys), 2), "臂展": round(max(xs) - min(xs), 2),
        "厚度": round(max(zs) - min(zs), 2),
    }, ensure_ascii=False, indent=2))
    if fails:
        print("\n❌ 未通过：")
        for f in fails:
            print("  ·", f)
        sys.exit(1)
    print("\n✅ 全部通过：361 穴贴体表、任督归中线、十四经穴数与 GB/T 12346-2021 一致")


if __name__ == "__main__":
    main()
