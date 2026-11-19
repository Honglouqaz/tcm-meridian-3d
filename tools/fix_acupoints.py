#!/usr/bin/env python3
"""修正穴位坐标：数据集混尺度（约 1/3 的点 y 值 3 倍偏大 → 悬空）→ ÷3 校正 + 贴皮吸附。
源头两级都改：① 数据集中的 acupoints.json ② 小程序 package3d/data/meridian.js"""
import json, base64, struct, math, shutil, sys, os

SKIN_JS = "/opt/data/miniprogram/sishige/src/package3d/libs/plugins/anatomy/skin3d.js"
MER_JS = "/opt/data/miniprogram/sishige/src/package3d/data/meridian.js"
ACU_JSON = "/opt/data/tcm_data/meridian3d/acupoints.json"


def load_js_mod(path):
    s = open(path, encoding="utf-8").read().strip()
    lines = [l for l in s.splitlines() if not l.strip().startswith("//")]
    s = "\n".join(lines).strip()
    for pre in ("module.exports =", "module.exports=", "export default"):
        if s.startswith(pre):
            s = s[len(pre):].strip()
            break
    if s.endswith(";"):
        s = s[:-1]
    s = s.strip()
    if s.startswith("'"):                      # 单引号 JS 字面量 → 去引号
        return s.strip("'")
    return json.loads(s)


def decode_bin(b64):
    b = base64.b64decode(b64)
    vc, tc = struct.unpack_from("<II", b, 4)
    bb = struct.unpack_from("<6f", b, 16)
    q = struct.unpack_from("<%dH" % (vc * 3), b, 40)
    verts = []
    for i in range(vc):
        verts.append([bb[j] + q[i * 3 + j] / 65535.0 * bb[3 + j] for j in range(3)])
    return verts


def build_grid(verts, cell=0.22):
    g = {}
    for i, v in enumerate(verts):
        k = (int(v[0] // cell), int(v[1] // cell), int(v[2] // cell))
        g.setdefault(k, []).append(i)
    return g, cell


def nearest(verts, grid, cell, p):
    cx, cy, cz = int(p[0] // cell), int(p[1] // cell), int(p[2] // cell)
    best, bi = 1e18, -1
    r = 0
    while r <= 24:
        found = False
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    if max(abs(dx), abs(dy), abs(dz)) != r:
                        continue
                    for i in grid.get((cx + dx, cy + dy, cz + dz), ()):
                        v = verts[i]
                        d = (v[0] - p[0]) ** 2 + (v[1] - p[1]) ** 2 + (v[2] - p[2]) ** 2
                        if d < best:
                            best, bi = d, i
                        found = True
        if bi >= 0 and (not found or r * cell > math.sqrt(best) + 0.05):
            break
        r += 1
    return math.sqrt(best), bi


def nearest_safe(verts, grid, cell, p):
    d, i = nearest(verts, grid, cell, p)
    if i >= 0:
        return d, i
    best, bi = 1e18, -1                        # 网格内找不到 → 全量扫描兜底
    for k, v in enumerate(verts):
        dd = (v[0] - p[0]) ** 2 + (v[1] - p[1]) ** 2 + (v[2] - p[2]) ** 2
        if dd < best:
            best, bi = dd, k
    return math.sqrt(best), bi


def main():
    skin = decode_bin(load_js_mod(SKIN_JS))
    grid, cell = build_grid(skin)
    print("皮肤顶点 %d（网格单元 %.2f）" % (len(skin), cell))

    mer = load_js_mod(MER_JS)
    pts = mer["points"]
    fixed_scale = fixed_snap = 0
    worst_before = worst_after = 0.0
    changed = []
    for p in pts:
        q = [p["x"], p["y"], p["z"]]
        d0, i0 = nearest_safe(skin, grid, cell, q)
        worst_before = max(worst_before, d0)
        q3 = [c / 3.0 for c in q]
        d3, i3 = nearest_safe(skin, grid, cell, q3)
        if d3 < 0.2 and d0 > 0.3:
            q, d0, i0 = q3, d3, i3
            fixed_scale += 1
        if 0.05 < d0 < 0.35:                      # 轻微离皮 → 吸附到最近皮顶点
            q = list(skin[i0])
            fixed_snap += 1
        p["x"], p["y"], p["z"] = q
        dn = nearest_safe(skin, grid, cell, q)[0]
        worst_after = max(worst_after, dn)
        if dn > 0.1:
            changed.append((p["name"], round(dn, 3)))
    print("÷3 尺度校正 %d 点；贴皮吸附 %d 点" % (fixed_scale, fixed_snap))
    print("最大离皮距离：修正前 %.3f → 修正后 %.3f" % (worst_before, worst_after))
    if changed:
        print("仍偏离 >0.1 的点(%d): %s" % (len(changed), changed[:8]))

    for f in (MER_JS, ACU_JSON):
        bak = f + ".bak_scale3_20260916"
        if not os.path.exists(bak):            # 只在首次备份，避免覆盖原始件
            shutil.copy2(f, bak)
    open(MER_JS, "w", encoding="utf-8").write("module.exports = " + json.dumps(mer, ensure_ascii=False, separators=(",", ":")))
    print("✅ 写入", MER_JS)

    # 同步数据集源头
    src = json.load(open(ACU_JSON, encoding="utf-8"))
    by_id = {p["id"]: p for p in src["acupoints"]}
    n = 0
    for p in pts:
        pid = p.get("i", p.get("id"))
        if pid in by_id:
            by_id[pid]["pos"] = {"x": p["x"], "y": p["y"], "z": p["z"]}
            n += 1
    json.dump(src, open(ACU_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("✅ 同步数据集 %d 点 → %s" % (n, ACU_JSON))


if __name__ == "__main__":
    main()
