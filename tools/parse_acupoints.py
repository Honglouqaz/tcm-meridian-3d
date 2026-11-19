#!/usr/bin/env python3
"""解析 m-glxuewei 的 xwsj.lj → acupoints.json
格式: x y z mx my dx 角度x 角度y 穴位ID 拼音 中文名 经络ID 经络名 【释义】..【功能】..【位置】.."""
import json, re, collections

SRC = "/opt/data/tcm_data/meridian3d/m-glxuewei/assets/xwsj.lj"
OUT = "/opt/data/tcm_data/meridian3d/acupoints.json"

# 试编码
raw = None
for enc in ("utf-8", "gbk", "gb18030"):
    try:
        raw = open(SRC, encoding=enc).read()
        print(f"编码: {enc}")
        break
    except UnicodeDecodeError:
        continue
if raw is None:
    raise SystemExit("无法解码")

pts = []
meridians = collections.OrderedDict()
branches = []        # [2026-09-10] 经络分支折线（解剖上并行、需单独成线的段）
cur_branch = None    # 当前分支（#BRANCH 开始 / #MAIN 结束）
bad = 0
for i, line in enumerate(raw.splitlines()):
    line = line.strip()
    if not line:
        continue
    # [2026-09-10] 分支标记：#BRANCH <经络ID> <分支名> / #MAIN <经络ID>
    # 用于足太阳膀胱经这类"一条经脉两条平行线"的情形：
    #   背一外线（睛明…委中 + 合阳…至阴）为主线，背二内线（附分…秩边）为独立折线，
    #   否则单折线会出现 委中(y=-3.05) → 附分(y=+1.51) 跨 4.56 单位的回折跳变。
    if line.startswith("#BRANCH"):
        _f = line.split(None, 2)
        cur_branch = {"meridian_id": int(_f[1]),
                      "name": (_f[2].strip() if len(_f) > 2 else "分支"),
                      "points": []}
        branches.append(cur_branch)
        continue
    if line.startswith("#MAIN"):
        cur_branch = None
        continue
    # 前 13 个字段 + 3 段中文
    m = re.match(
        r"^(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+"      # x y z
        r"(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+"        # mx my dx
        r"(-?[\d.]+)\s+(-?[\d.]+)\s+"                      # 角度x 角度y
        r"(\d+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(\S+)\s*(.*)$", line)
    if not m:
        bad += 1
        continue
    (x, y, z, mx, my, dx, ax, ay, wid, py, cn, mid, mname, rest) = m.groups()
    rest = rest.strip()
    def seg(tag):
        mm = re.search(rf"【{tag}】(.*?)(?=【|$)", rest, re.S)
        return mm.group(1).strip() if mm else ""
    shiyi, gongneng, weizhi = seg("释义"), seg("功能"), seg("位置")
    pts.append({
        "id": int(wid), "py": py, "name": cn,
        "meridian_id": int(mid), "meridian": mname,
        "pos": {"x": float(x), "y": float(y), "z": float(z)},
        "shiyi": shiyi, "func": gongneng, "location": weizhi,
    })
    if cur_branch is not None and cur_branch["meridian_id"] == int(mid):
        cur_branch["points"].append(int(wid))
    else:
        meridians.setdefault(mid, {"id": int(mid), "name": mname, "points": []})["points"].append(int(wid))

print(f"解析穴位: {len(pts)} 条 (跳过 {bad} 行)")
print(f"经络: {len(meridians)} 条")
for mid, m in meridians.items():
    print(f"  {mid} {m['name']}: {len(m['points'])} 穴")
for b in branches:
    print(f"  [分支] {b['meridian_id']} {b['name']}: {len(b['points'])} 穴")
# 样例
if pts:
    s = pts[0]
    print("\n样例:", s["name"], s["py"], f"({s['pos']['x']}, {s['pos']['y']}, {s['pos']['z']})")
    print("  释义:", s["shiyi"][:40])
    print("  功能:", s["func"][:40])
    print("  位置:", s["location"][:40])

json.dump({"meridians": list(meridians.values()), "branches": branches, "acupoints": pts},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n✅ 输出: {OUT}")
