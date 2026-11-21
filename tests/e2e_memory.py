"""端到端：每个智能体自己的记忆（真实模型）。
在一个会话里告诉它一件以后用得上的事 → 它自己记下 → 换一个新会话它还记得；另一个智能体不知道。

前提：设置 MAC_TEST_BASE_URL / MAC_TEST_API_KEY / MAC_TEST_MODEL（见 tests/README.md）。
用法：python tests/e2e_memory.py
"""
import asyncio
import json
import sys

import httpx
import websockets

from harness import API, FAST, WS, make_provider, need_model  # noqa: E402  默认起临时服务器，不碰你的数据

fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": []}))
    out = []
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 300))
        if ev["type"] == "message" and ev["message"].get("conv_id") == conv_id and not ev["message"].get("streaming"):
            out = [x for x in out if x["id"] != ev["message"]["id"]] + [ev["message"]]
        if ev["type"] == "running" and ev.get("conv_id") == conv_id and not ev["running"]:
            return [m for m in out if m["role"] == "agent"]


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        made = {"providers": [], "agents": [], "convs": []}
        try:
            p = await make_provider(c, "memory-e2e")
            made["providers"].append(p["id"])
            mk = lambda name: c.post(API + "/agents", json={"name": name, "provider_id": p["id"], "model": FAST, "no_tools": True,  # noqa: E731
                                                            "system_prompt": "你是用户的长期助理，回答简短。"})
            a = (await mk("老搭档")).json()
            b = (await mk("新同事")).json()
            made["agents"] += [a["id"], b["id"]]
            check("新建的智能体默认开启记忆", a["memory"] is True)

            c1 = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
            made["convs"].append(c1["id"])
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                said = await turn(ws, c1["id"], "先认识一下：我们团队正在做的记账 App 名字叫「账米」，下个月 15 号上线。以后你跟我汇报进度都用表格。")
                mems = (await c.get(API + "/agents/%s/memories" % a["id"])).json()["memories"]
                print("         记下的：", [m["text"] for m in mems])
                check("它自己记下了以后用得上的事", any("账米" in m["text"] for m in mems), [x["content"][:200] for x in said])
                check("记忆标签不出现在正文里", all("<remember>" not in x["content"] for x in said))
                check("会话里提示记住了什么", any(x.get("memories") for x in said))

                # 新会话：它还记得；另一个智能体不知道
                c2 = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
                c3 = (await c.post(API + "/conversations", json={"agent_ids": [b["id"]]})).json()
                made["convs"] += [c2["id"], c3["id"]]
                q = "我们正在做的那个 App 叫什么名字？只回答名字。"
                ans_a = (await turn(ws, c2["id"], q))[-1]["content"]
                ans_b = (await turn(ws, c3["id"], q))[-1]["content"]
                print("         老搭档：", ans_a[:60], "｜ 新同事：", ans_b[:60])
                check("换一个新会话，它还记得", "账米" in ans_a, ans_a)
                check("记忆只属于它自己，别的智能体不知道", "账米" not in ans_b, ans_b)

            # 关掉它的记忆后，不再带上
            await c.put(API + "/agents/" + a["id"], json={**a, "memory": False})
            c4 = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
            made["convs"].append(c4["id"])
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                ans = (await turn(ws, c4["id"], q))[-1]["content"]
            check("关掉记忆后不再带上", "账米" not in ans, ans)
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
