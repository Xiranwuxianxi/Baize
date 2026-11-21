"""端到端自检（真实 Ollama）：领头人在回答过程中自己定义并新建智能体。

前提：本机 Ollama 已启动。
用法：backend/.venv/Scripts/python tests/e2e_hire.py [领头人用的模型]
领头人需要能按格式输出，默认取本机最大的模型。
"""
import asyncio
import json
import sys

import httpx
import websockets

from harness import API, BASE, FAST, STRONG, WS, channels, make_provider, need_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:400] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": []}))
    out = []
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 600))
        if ev["type"] == "refresh":
            continue
        if (ev.get("message") or ev.get("conversation") or ev).get("conv_id", ev.get("conversation", {}).get("id", conv_id)) != conv_id:
            continue
        if ev["type"] == "message" and not ev["message"].get("streaming"):
            m = ev["message"]
            if m["role"] == "tool" and m["status"] == "pending":  # 新建 / 移除成员要用户确认：像用户一样点「允许」
                await ws.send(json.dumps({"type": "permit", "id": m["id"], "decision": "once"}))
            out = [x for x in out if x["id"] != m["id"]] + [m]
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return out


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        model = next((a for a in sys.argv[1:] if not a.startswith("--")), None) or STRONG
        print("领头人模型: %s\n" % model)
        made = {"providers": [], "agents": [], "convs": []}
        try:
            p = await make_provider(c, "hire-e2e")
            made["providers"].append(p["id"])
            boss = (await c.post(API + "/agents", json={"no_tools": True, 
                "name": "招聘总管", "provider_id": p["id"], "model": model, "description": "负责组建团队并安排工作",
                "system_prompt": "你是团队负责人，做事干练，回答简短。"})).json()
            made["agents"].append(boss["id"])
            conv = (await c.post(API + "/conversations", json={"agent_ids": [boss["id"]], "mode": "lead", "lead_id": boss["id"], "rounds": 1})).json()
            made["convs"].append(conv["id"])
            before = {a["id"] for a in (await c.get(API + "/state")).json()["agents"]}

            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                msgs = await turn(ws, conv["id"], "我需要一位专门写日本俳句的「俳句诗人」。现有的智能体都不合适，请你新建这样一个智能体，自己给它写好角色设定，然后让它写一首关于秋天的俳句，最后把俳句转给我。")

            for m in msgs:
                if m["role"] == "notice":
                    print("         [提示] " + m["content"])
                elif m["role"] == "agent":
                    print("         [%s] %s%s" % (m["agent_name"], m["content"][:150].replace("\n", " / "), ("  ERR " + m["error"]) if m["error"] else ""))
                    for h in m.get("hired") or []:
                        print("             -> 新建「%s」：%s" % (h["name"], h["description"]))

            s = (await c.get(API + "/state")).json()
            new = [a for a in s["agents"] if a["id"] not in before]
            now = next(x for x in s["conversations"] if x["id"] == conv["id"])
            said = [m for m in msgs if m["role"] == "agent"]
            check("全程无错误", all(not m["error"] for m in said), [(m["agent_name"], m["error"]) for m in said])
            check("领头人新建了智能体", len(new) >= 1, [m["content"][:200] for m in said[:1]])
            if new:
                a = new[0]
                print("         新智能体: 名字=%s | 简介=%s | 设定=%s" % (a["name"], a["description"], a["system_prompt"][:80].replace("\n", " ")))
                check("角色设定由领头人自己写，不是空的", len(a["system_prompt"]) >= 10, a["system_prompt"])
                check("新智能体只属于这个会话", a["conv_id"] == conv["id"])
                check("新智能体已加入会话", a["id"] in now["agent_ids"], now["agent_ids"])
                check("沿用领头人的渠道和模型", a["provider_id"] == boss["provider_id"] and a["model"] == boss["model"])
                check("会话里出现新建提示", any(m["role"] == "notice" and a["name"] in m["content"] and "新建" in m["content"] for m in msgs))
                check("领头人的消息记录了新建结果", any(m.get("hired") for m in said))
                check("新智能体收到任务并完成", any(m["agent_id"] == a["id"] and m.get("task") and m["content"] for m in said), [(m["agent_name"], bool(m.get("task"))) for m in said])
                check("最后由领头人答复用户", said[-1]["agent_id"] == boss["id"])
                promoted = (await c.post(API + "/agents/%s/promote" % a["id"])).json()
                made["agents"].append(a["id"])
                check("可以把它加入全局", promoted["conv_id"] == "")
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
