# 数据许可与来源

本仓库有三类内容，许可各不相同：

| 内容 | 文件 | 许可 |
|---|---|---|
| 代码 | `tools/*.py`、`demo/index.html`、`demo/vendor/*` | **MIT** |
| 穴位数据 | `data/acupoints.json`、`data/meridians.json` | **CC BY 4.0** |
| 解剖网格与贴体坐标 | `demo/models/*.glb`、`data/body.json` | **CC BY-SA 2.1 JP** |

## 1. 解剖网格：BodyParts3D 4.3

- 来源：**BodyParts3D**，© 日本 **DBCLS**（Database Center for Life Science / ライフサイエンス統合データベースセンター）
- 项目主页：https://lifesciencedb.jp/bp3d/
- 许可：**Creative Commons Attribution-ShareAlike 2.1 Japan（CC BY-SA 2.1 JP）**
- 使用部件：整具体表 `FJ2810`（FMA7163 Skin）、骨骼部件 406 个、主要肌群 125 个
- 本项目做的工作：坐标系换算（Z-up → Y-up、mm → 本项目单位）、部件合批、GLB 导出、
  以及把 361 个穴位投影到皮肤表面。**这些衍生文件同样以 CC BY-SA 2.1 JP 提供。**
- 引用建议：*BodyParts3D, © The Database Center for Life Science licensed under CC Attribution-Share Alike 2.1 Japan*

## 2. 穴位数据：CC BY 4.0

- **三维坐标初版**：开源项目 `meiroo/m-glxuewei`（Android 经络穴位 3D 演示，README 注明首版数据由 lhdx_lee 提供）。致谢上游作者的开放工作。
- **名称 / 定位 / 释义 / 主治**：依据 **GB/T 12346-2021《经穴名称与定位》** 与公开针灸学教材逐条校订，
  累计修正在案 **437 处**（错字、异体字、定位表述、拼音大小写、经络归属错误、
  以及 **id ≥ 310 的 88 个穴位坐标被整体放大 3 倍**——上游漏了 `/3`）。
- 校订后的数据以本仓库 `data/acupoints.json` 为**唯一真源**，以 **CC BY 4.0** 发布。

## 关于「事实数据」

穴位名称、经络归属、定位描述属于**国家标准规定的事实性内容**，不因汇编而产生独占。
本仓库主张的是**校订劳动**（437 处修正 + 坐标标定 + 贴体投影）与代码，不主张对传统知识本身的任何独占。

## 商用提示

- 代码 MIT：可自由商用。
- 穴位数据 CC BY 4.0：可商用，需署名。
- **解剖网格（含 `data/body.json` 与 `demo/models/*.glb`）CC BY-SA 2.1 JP：可商用，但需署名，
  且对其修改后的衍生作品须以相同许可发布。** 如果你的产品不能接受 ShareAlike，
  请自行替换 `demo/models/` 下的网格（贴体坐标 `data/body.json` 需要用你自己的网格重跑
  `tools/build_real_body.py`）。
