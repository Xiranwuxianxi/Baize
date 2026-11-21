"""实测省 token 的效果（真实云端模型）：同一组智能体、同样的多轮讨论，分别在「省 token」开 / 关下跑，对比发给模型的总量。
也检查技能按需加载、会话置顶。只创建并清理自己的临时数据。

前提：至少有一个设置了默认模型的渠道。
用法：backend/.venv/Scripts/python tests/e2e_tokens.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import websockets

from harness import API, BASE, OLLAMA, WS, need_model, need_ollama, ollama_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []
TOPIC = ["我们要给一家咖啡店做会员小程序，大家各自从自己的角度说说最重要的一点。", "好，针对刚才说的，各自补充一个具体的落地做法。",
         "有人提到积分，展开说说积分规则怎么设计。", "最后，各自用一句话总结你的建议。"]


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": []}))
    out = []
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 900))
        if ev["type"] == "refresh":
            continue
        if (ev.get("message") or ev.get("conversation") or ev).get("conv_id", ev.get("conversation", {}).get("id", conv_id)) != conv_id:
            continue
        if ev["type"] == "message" and not ev["message"].get("streaming"):
            m = ev["message"]
            if m["role"] == "tool" and m["status"] == "pending":
                await ws.send(json.dumps({"type": "permit", "id": m["id"], "decision": "once"}))
            out = [x for x in out if x["id"] != m["id"]] + [m]
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return out


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        s = (await c.get(API + "/state")).json()
        prov = need_model()
        thrifty_before = (await c.get(API + "/settings")).json()["thrifty"]
        made = {"agents": [], "convs": [], "skills": []}

        async def agent(name, **kw):
            a = (await c.post(API + "/agents", json={"name": name, "provider_id": prov["id"], "model": prov["default_model"], "no_tools": True, **kw})).json()
            made["agents"].append(a["id"])
            return a

        try:
            # 跑一段真实的多人讨论（省 token 关，回复长短由模型决定），
            # 再拿同一段历史，在开 / 关两种设置下重算每一次发言要发给模型的上下文 —— 这样对比不受回复长短随机性影响
            team = [await agent(n, description=d, system_prompt="你是%s。" % d)
                    for n, d in (("产品甲", "产品经理"), ("运营乙", "运营专家"), ("技术丙", "技术负责人"))]
            await c.put(API + "/settings", json={"thrifty": False})
            cv = (await c.post(API + "/conversations", json={"agent_ids": [a["id"] for a in team], "mode": "sequential", "rounds": 1})).json()
            made["convs"].append(cv["id"])
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                for q in TOPIC:
                    await turn(ws, cv["id"], q)
            cu = (await c.get(API + "/conversations/%s/usage" % cv["id"])).json()
            print("         会话用量：%s" % cu["total"])
            check("会话用量按智能体统计出来了", cu["total"]["calls"] >= 12 and len(cu["agents"]) == 3, cu)
            # 个别请求接口可能不回传用量（这时按字数估算并标明），绝大多数应是真实数字
            check("用量基本都是接口返回的真实数字", cu["total"]["est"] <= max(1, cu["total"]["calls"] // 6), cu["total"])
            gu = (await c.get(API + "/usage")).json()
            check("全局用量里能看到这个会话", any(x["id"] == cv["id"] for x in gu["convs"]) and gu["today"]["calls"] >= 12, gu["today"])
            history = (await c.get(API + "/conversations/%s/messages" % cv["id"])).json()
            history = history.get("messages", history) if isinstance(history, dict) else history
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
            import harness
            if not harness.DATA:
                print("  跳过开 / 关对比：它要读取测试服务器的数据库，只能在临时测试服务器上做（不要设置 MAC_TEST_URL）")
            else:
                os.environ["MAC_DATA_DIR"] = harness.DATA  # 读临时服务器的库，绝不读你自己的数据
                import context as core  # 只用它的上下文拼装函数，不改任何数据
                conv = {**cv, "agent_ids": [a["id"] for a in team]}
                real_value = core.settings.value
                totals = {}
                for mode in (False, True):
                    core.settings.value = (lambda m: lambda k, d=None: m if k == "thrifty" else real_value(k, d))(mode)
                    total = 0
                    for i, m in enumerate(history):
                        if m["role"] != "agent":
                            continue
                        who = next(a for a in team if a["id"] == m["agent_id"])
                        system, msgs = core.build_context(conv, who, history[:i])
                        total += core._tokens(system) + sum(core._tokens(x["content"]) for x in msgs)
                    totals[mode] = total
                core.settings.value = real_value
                n = sum(1 for m in history if m["role"] == "agent")
                saved = 1 - totals[True] / max(1, totals[False])
                print("         同一段讨论 %d 次发言：关 ≈%d token，开 ≈%d token，节省约 %.0f%%" % (n, totals[False], totals[True], saved * 100))
                check("开启后同样的讨论明显更省（至少省 20%）", saved >= 0.2, totals)

            # ---- 技能按需加载（省 token 开启时） ----
            await c.put(API + "/settings", json={"thrifty": True})
            big = "\n".join("第%d步：仔细检查发票抬头、税号、金额与日期是否一致，并记录异常。" % i for i in range(1, 60))
            sk = (await c.post(API + "/skills", json={"name": "发票核对", "description": "核对发票信息是否完整一致", "instructions": big})).json()
            made["skills"].append(sk["id"])
            a = await agent("财务助理", system_prompt="回答简短。", skills=[sk["id"]])
            cv = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
            made["convs"].append(cv["id"])
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                m1 = next(m for m in await turn(ws, cv["id"], "今天天气怎么样？随便聊一句。") if m["role"] == "agent")
                msgs = await turn(ws, cv["id"], "帮我核对一张发票，要注意哪些地方？")
            m2 = [m for m in msgs if m["role"] == "agent"][0]
            print("         无关问题约 %d token；相关问题约 %d token（技能全文约 %d 字）" % (m1["tokens_in"], m2["tokens_in"], len(big)))
            check("问题和技能无关时不带技能全文", m1["tokens_in"] < len(big) // 2, m1["tokens_in"])
            check("问题相关时技能被用上", m2["tokens_in"] > len(big) // 3 or any(x["role"] == "tool" and x["action"].get("kind") == "skill_read" for x in msgs))
            check("技能全文已附上时不再多读一次", not any(x["role"] == "tool" and x["action"].get("kind") == "skill_read" for x in msgs),
                  [x["action"] for x in msgs if x["role"] == "tool"])

            # ---- 置顶 ----
            p = (await c.put(API + "/conversations/" + cv["id"], json={**cv, "pinned": True})).json()
            check("会话可以置顶", p["pinned"] is True)
        finally:
            await c.put(API + "/settings", json={"thrifty": thrifty_before})
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
            for sid in made["skills"]:
                await c.delete(API + "/skills/" + sid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
