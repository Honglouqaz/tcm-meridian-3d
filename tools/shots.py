#!/usr/bin/env python3
"""渲染 3D 经络图谱并抓多视角截图（用于人工/视觉验收）"""
import asyncio, base64, json, sys
import aiohttp

OUT = "/opt/data/cache/scratch/meridian3d/docs"
URL = "http://127.0.0.1:8797/demo/index.html"


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.get("http://127.0.0.1:9333/json/list") as r:
            t = [x for x in await r.json() if x["type"] == "page"][0]
        ws = await s.ws_connect(t["webSocketDebuggerUrl"], max_msg_size=128 * 1024 * 1024)
        i = 0

        async def send(method, params=None):
            nonlocal i
            i += 1
            await ws.send_json({"id": i, "method": method, "params": params or {}})
            while True:
                d = await ws.receive_json()
                if d.get("id") == i:
                    return d

        async def js(expr):
            r = await send("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
            res = r.get("result", {}).get("result", {})
            if r.get("result", {}).get("exceptionDetails"):
                return "EXC: " + json.dumps(r["result"]["exceptionDetails"].get("text"))[:200]
            return res.get("value")

        async def shot(name, wait=1.2):
            await asyncio.sleep(wait)
            r = await send("Page.captureScreenshot", {"format": "jpeg", "quality": 88})
            p = f"{OUT}/shot_{name}.jpg"
            open(p, "wb").write(base64.b64decode(r["result"]["data"]))
            print("📷", p)

        await send("Page.enable")
        await send("Runtime.enable")
        await send("Network.enable")
        await send("Network.setCacheDisabled", {"cacheDisabled": True})   # 否则 GLB 走缓存，改了文件看不到
        await send("Emulation.setDeviceMetricsOverride",
                   {"width": 1500, "height": 1900, "deviceScaleFactor": 1, "mobile": False})
        await send("Page.navigate", {"url": URL})
        # 等模型加载完（加载遮罩隐藏），最多 90 秒
        for _ in range(90):
            await asyncio.sleep(1)
            done = await js("document.getElementById('load').style.display === 'none'")
            if done:
                break
        else:
            print("⚠️ 加载超时，仍截图")
        await asyncio.sleep(2)

        print("状态:", await js("document.getElementById('stat').textContent"))
        print("错误:", await js("document.getElementById('err').textContent || '(无)'"))
        print("穴位数:", await js("document.querySelectorAll('canvas').length"))

        # 1) 默认：皮肤 + 经络 + 穴位（前视）
        await js("document.querySelector('.views button[data-view=front]').click()")
        await shot("front_default")

        # 2) 骨骼 + 肌肉打开（这两个模型是懒加载的，等它们真的进来再截图）
        await js("""(()=>{const b=[...document.querySelectorAll('.layers button')];
          b.find(x=>x.dataset.layer==='skeleton').click();
          b.find(x=>x.dataset.layer==='muscles').click(); return 'ok'})()""")
        for _ in range(60):
            await asyncio.sleep(1)
            if await js("!!(window.__layers&&window.__layers.skeleton&&window.__layers.muscles)"):
                break
        await asyncio.sleep(1.5)
        await shot("front_layers")

        # 3) 后视（督脉）
        await js("document.querySelector('.views button[data-view=back]').click()")
        await shot("back_dumai")

        # 4) 左视（看任督是否贴体表）
        await js("document.querySelector('.views button[data-view=left]').click()")
        await shot("left_profile")

        # 4.5) 左视 内视（皮肤几乎全透，看经络与骨骼关系）
        await js("""(()=>{const b=[...document.querySelectorAll('.layers button')];
          const x=b.find(x=>x.dataset.layer==='xray'); if(!x.classList.contains('on')) x.click(); return 'ok'})()""")
        await shot("left_xray")

        # 4.6) 进针模拟：选中足三里（骨骼可见 + 内视），看针与下方骨
        print("选中:", await js("window.__pick('足三里')"))
        await shot("needle_zusanli")

        # 5) 斜视 + 骨骼
        await js("""(()=>{const b=[...document.querySelectorAll('.layers button')];
          b.find(x=>x.dataset.layer==='muscles').click();
          document.querySelector('.views button[data-view=iso]').click(); return 'ok'})()""")
        await shot("iso_skeleton")

        ws.close()


asyncio.run(main())
