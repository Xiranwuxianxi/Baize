"""端到端自检（真实 Ollama）：长上下文、输出上限、自动补救，以及头像图片校验。

前提：本机 Ollama 已启动，且有一个支持思考的模型。
用法：backend/.venv/Scripts/python tests/e2e_limits.py [模型名]
"""
import asyncio
import json
import sys

import httpx
import websockets

from harness import API, BASE, OLLAMA, WS, need_model, need_ollama, ollama_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:400] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": []}))
    last = None
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 600))
        if (ev.get("message") or ev.get("conversation") or ev).get("conv_id", ev.get("conversation", {}).get("id", conv_id)) != conv_id:
            continue
        if ev["type"] == "message" and ev["message"].get("role") == "agent" and not ev["message"]["streaming"]:
            last = ev["message"]
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return last


async def main():
    need_ollama()
    async with httpx.AsyncClient(timeout=120) as c:
        tags = sorted((await c.get(OLLAMA + "/api/tags")).json()["models"], key=lambda m: m["size"])
        model = next((a for a in sys.argv[1:] if not a.startswith("--")), None) or tags[0]["name"]
        default_ctx = (await c.get(API + "/state")).json()["env"]["ollama_ctx"]
        print("模型: %s   默认上下文: %s\n" % (model, default_ctx))
        made = {"providers": [], "agents": [], "convs": []}
        try:
            p = (await c.post(API + "/providers", json={"name": "limits-e2e", "protocol": "ollama", "base_url": OLLAMA})).json()
            made["providers"].append(p["id"])
            check("渠道默认不写死上下文长度", p.get("num_ctx") is None, p.get("num_ctx"))

            async def agent(name, **kw):
                a = (await c.post(API + "/agents", json={"no_tools": True, "name": name, "provider_id": p["id"], "model": model, **kw})).json()
                made["agents"].append(a["id"])
                return a

            async def conv(a):
                cv = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
                made["convs"].append(cv["id"])
                return cv

            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()

                # ---- 长历史：以前 Ollama 用 4096 的窗口，这种长度必然只有思考没有正文 ----
                a = await agent("长文测试", system_prompt="回答务必简短。")
                cv = await conv(a)
                essay = "".join("第%d段：团队讨论了需求范围、风险与排期，并记录了若干待办事项。" % i for i in range(1, 181))  # 约 6000 字
                m = await turn(ws, cv["id"], essay + "\n\n以上是会议记录。请用一句话概括它在讲什么。")
                check("约 6000 字的输入仍能给出正文", bool(m and m["content"]) and not m["error"], m and m["error"])
                print("         回复: %s" % (m["content"][:80].replace("\n", " ") if m else None))
                loaded = [x for x in (await c.get(OLLAMA + "/api/ps")).json()["models"] if x["name"] == model]
                check("Ollama 按默认上下文长度加载模型", bool(loaded) and loaded[0].get("context_length") == default_ctx, loaded and loaded[0].get("context_length"))

                # ---- 超出窗口的历史会被自动裁剪，而不是让模型撞墙 ----
                huge = "".join("第%d条：这是一段用来占位的历史记录，内容并不重要。" % i for i in range(1, 1200))  # 远超 8192 token
                m = await turn(ws, cv["id"], huge + "\n\n忽略上面的占位内容。请只回答：一加一等于几？")
                check("远超上下文窗口的输入：自动裁剪后仍有正文", bool(m and m["content"]) and not m["error"], m and m["error"])
                print("         回复: %s" % (m["content"][:80].replace("\n", " ") if m else None))

                # ---- 输出上限极小：思考会把额度用光，应自动关掉思考重问一次 ----
                tiny = await agent("小额度测试", max_tokens=40)
                cv2 = await conv(tiny)
                m = await turn(ws, cv2["id"], "请详细分析一下为什么天空是蓝色的。")
                check("输出上限只有 40 也能拿到正文（自动补救）", bool(m and m["content"]) and not m["error"], m and (m["error"], len(m["reasoning"])))
                print("         思考 %d 字，正文: %s" % (len(m["reasoning"]) if m else 0, m["content"][:60].replace("\n", " ") if m else None))
                check("被截断的回复带有截断标记或已给出正文", bool(m and (m.get("truncated") or m["content"])))

                # ---- 渠道可以自定义上下文长度 ----
                p2 = (await c.put(API + "/providers/" + p["id"], json={"name": "limits-e2e", "protocol": "ollama", "base_url": OLLAMA, "num_ctx": 4096})).json()
                check("上下文长度可在渠道上设置", p2.get("num_ctx") == 4096, p2.get("num_ctx"))
                m = await turn(ws, cv2["id"], "用一个词回答：水的化学式是什么？")
                loaded = [x for x in (await c.get(OLLAMA + "/api/ps")).json()["models"] if x["name"] == model]
                check("修改后模型按新的上下文长度加载", bool(loaded) and loaded[0].get("context_length") == 4096, loaded and loaded[0].get("context_length"))

            # ---- 头像图片 ----
            ok = await agent("头像测试", avatar_image=PNG)
            check("合法的图片头像被保存", ok["avatar_image"] == PNG)
            for label, bad in (("SVG", "data:image/svg+xml;base64,PHN2Zy8+"), ("外链", "https://example.com/a.png"),
                               ("脚本", "javascript:alert(1)"), ("超大", "data:image/png;base64," + "A" * 300000)):
                r = await agent("头像测试-" + label, avatar_image=bad)
                check("拒绝不安全或过大的头像：" + label, r["avatar_image"] == "", r["avatar_image"][:40])
            kept = (await c.put(API + "/agents/" + ok["id"], json={**ok, "avatar_image": ""})).json()
            check("可以移除已上传的头像", kept["avatar_image"] == "")
        finally:
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
            for pid in made["providers"]:
                await c.delete(API + "/providers/" + pid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
