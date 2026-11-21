"""端到端自检（只连真实服务，不使用任何模拟）。

前提：本机 Ollama 已启动且至少有一个模型。
加 --cloud 时，还会经由 env:DASHSCOPE_API_KEY 引用测试通义千问云端接口（会产生少量调用）。
用法：backend/.venv/Scripts/python tests/e2e.py [ollama模型名] [--cloud]
"""
import asyncio
import json
import os
import sys

import httpx
import websockets

from harness import API, BASE, FAST, STRONG, WS, channels, make_provider, need_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


def finals(events):
    return [e["message"] for e in events
            if e["type"] == "message" and e["message"].get("role") == "agent" and not e["message"]["streaming"]]


async def turn(ws, conv_id, content, targets=None, stop_after=None):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": targets or []}))
    events, deltas = [], 0
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 300))
        # events are broadcast to every client, so ignore other conversations that may be active
        if (ev.get("message") or ev.get("conversation") or ev).get("conv_id", ev.get("conversation", {}).get("id", conv_id)) != conv_id:
            continue
        events.append(ev)
        if ev["type"] == "delta":
            deltas += 1
            if stop_after and deltas == stop_after:
                await ws.send(json.dumps({"type": "stop", "conv_id": conv_id}))
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return events


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=300) as c:
        model = FAST
        print("模型: %s\n" % model)
        targets = [(ch["protocol"], ch["label"], ch["base_url"], ch["api_key"], ch["model"]) for ch in channels()]
        if "--cloud" in sys.argv and os.environ.get("DASHSCOPE_API_KEY"):
            targets.append(("openai", "通义千问（云端）", "https://dashscope.aliyuncs.com/compatible-mode/v1", "env:DASHSCOPE_API_KEY", "qwen-turbo"))
        created = {"providers": [], "agents": [], "convs": []}
        try:
            agents = []
            for i, (proto, label, base, key, mdl) in enumerate(targets):
                p = (await c.post(API + "/providers", json={"name": label, "protocol": proto, "base_url": base, "api_key": key})).json()
                created["providers"].append(p["id"])
                check(label + ": 接口不回传密钥", "api_key" not in p)
                r = await c.post(API + "/providers/%s/models" % p["id"])
                check(label + ": 获取模型列表", r.status_code == 200 and len(r.json()["models"]) >= 1, r.text)
                r = await c.post(API + "/providers/%s/test" % p["id"], json={"model": mdl})
                check(label + ": 真实流式对话", r.status_code == 200, r.text)
                if r.status_code == 200:
                    print("         %sms  回复: %s" % (r.json()["ms"], r.json()["reply"][:60].replace("\n", " ")))
                a = (await c.post(API + "/agents", json={"no_tools": True, 
                    "name": ["阿橙", "小柏", "老秦", "阿岚", "云舟"][i], "provider_id": p["id"], "model": mdl,
                    "system_prompt": "回答务必简短，不超过两句话。", "max_tokens": 600})).json()
                created["agents"].append(a["id"])
                agents.append(a)
            # 渠道少于 4 个时（比如只配了一个云端渠道），用第一个渠道补足成员，后面的接力 / 并行测试需要至少 4 个
            while agents and len(agents) < 4:
                a = (await c.post(API + "/agents", json={"no_tools": True, "name": ["阿橙", "小柏", "老秦", "阿岚", "云舟"][len(agents)],
                    "provider_id": created["providers"][0], "model": targets[0][4],
                    "system_prompt": "回答务必简短，不超过两句话。", "max_tokens": 600})).json()
                created["agents"].append(a["id"])
                agents.append(a)

            ids = [a["id"] for a in agents]
            conv = (await c.post(API + "/conversations", json={"agent_ids": ids[:3], "mode": "sequential", "rounds": 2})).json()
            created["convs"].append(conv["id"])
            async with websockets.connect(WS) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                check("WebSocket 握手", json.loads(await ws.recv())["type"] == "ready")

                ev = await turn(ws, conv["id"], "用一句话说说你最喜欢的水果，并说出你自己的名字。")
                f = finals(ev)
                check("接力 2 轮 × 3 个智能体 = 6 条回复", len(f) == 6, len(f))
                check("发言顺序正确", [m["agent_name"] for m in f] == ["阿橙", "小柏", "老秦"] * 2, [m["agent_name"] for m in f])
                check("全部有内容且无错误", all(m["content"] and not m["error"] for m in f), [(m["agent_name"], m["error"]) for m in f])
                check("流式增量到达", sum(1 for e in ev if e["type"] == "delta") > 6)
                check("自动命名会话", any(e["type"] == "conversation" for e in ev))
                for m in f[:3]:
                    print("         [%s] %s" % (m["agent_name"], m["content"][:70].replace("\n", " ")))

                ev = await turn(ws, conv["id"], "只请老秦补充一句。", targets=[ids[2]])
                check("点名：只有被点名者发言", [m["agent_name"] for m in finals(ev)] == ["老秦"], [m["agent_name"] for m in finals(ev)])

                ev = await turn(ws, conv["id"], "", targets=[ids[0]])
                msgs = [e["message"] for e in ev if e["type"] == "message" and not e["message"].get("streaming")]
                check("空消息点名 = 直接让它发言", [m.get("agent_name") for m in msgs] == ["阿橙"] and not msgs[0]["error"], msgs)

                await c.put(API + "/conversations/" + conv["id"], json={**conv, "title": "并行", "mode": "parallel", "rounds": 1, "agent_ids": ids[-2:]})
                ev = await turn(ws, conv["id"], "一句话解释什么是递归。")
                f = finals(ev)
                check("并行：全部作答且无错误", len(f) == 2 and all(m["content"] and not m["error"] for m in f), [(m["agent_name"], m["error"]) for m in f])
                starts = [i for i, e in enumerate(ev) if e["type"] == "message" and e["message"].get("streaming")]
                first_delta = next(i for i, e in enumerate(ev) if e["type"] == "delta")
                check("并行：同时开始", len(starts) == 2 and max(starts) < first_delta)

                ev = await turn(ws, conv["id"], "请写一篇 800 字的文章介绍长城。", targets=[ids[-2]], stop_after=8)
                f = finals(ev)
                check("停止：中断并保留已生成内容", len(f) == 1 and (f[0]["content"] or f[0]["reasoning"]) and len(f[0]["content"]) < 1500, f)

                bad = (await c.post(API + "/agents", json={"no_tools": True, "name": "错模型", "provider_id": created["providers"][0], "model": "no-such-model-xyz"})).json()
                dead = (await c.post(API + "/providers", json={"name": "dead", "protocol": "openai", "base_url": "http://127.0.0.1:9"})).json()
                noenv = (await c.post(API + "/providers", json={"name": "noenv", "protocol": "openai", "base_url": channels()[0]["base_url"], "api_key": "env:MAC_NO_SUCH_VAR"})).json()
                dead_a = (await c.post(API + "/agents", json={"no_tools": True, "name": "断线", "provider_id": dead["id"], "model": "x"})).json()
                noenv_a = (await c.post(API + "/agents", json={"no_tools": True, "name": "缺变量", "provider_id": noenv["id"], "model": model})).json()
                created["agents"] += [bad["id"], dead_a["id"], noenv_a["id"]]
                created["providers"] += [dead["id"], noenv["id"]]
                check("env 引用只回显变量名", noenv["key_hint"] == "环境变量 MAC_NO_SUCH_VAR")
                c2 = (await c.post(API + "/conversations", json={"agent_ids": [bad["id"], dead_a["id"], noenv_a["id"], ids[0]]})).json()
                created["convs"].append(c2["id"])
                f = finals(await turn(ws, c2["id"], "你好"))
                check("模型不存在：给出上游报错", any(k in f[0]["error"] for k in ("404", "not found", "不存在", "does not exist")), f[0]["error"])
                check("连不上：给出可读错误", "无法连接" in f[1]["error"], f[1]["error"])
                check("环境变量缺失：给出可读错误", "MAC_NO_SUCH_VAR" in f[2]["error"], f[2]["error"])
                check("前面出错不影响后面的智能体", len(f) == 4 and f[3]["content"] and not f[3]["error"], f[3])

            saved = (await c.get(API + "/conversations/%s/messages" % conv["id"])).json()["messages"]
            check("消息已持久化", len(saved) == 1 + 6 + 1 + 1 + 1 + 1 + 2 + 1 + 1, len(saved))
        finally:
            for x in (await c.get(API + "/lessons")).json()["lessons"]:  # 测试智能体记下的经验不留在库里
                if x["by"] in ("阿橙", "小柏", "老秦", "阿岚", "云舟", "错模型", "断线", "缺变量"):
                    await c.delete(API + "/lessons/" + x["id"])
            for cid in created["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in created["agents"]:
                await c.delete(API + "/agents/" + aid)
            for pid in created["providers"]:
                await c.delete(API + "/providers/" + pid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
