"""端到端自检（真实 Ollama）：会话内创建智能体 / 加入全局 / 领头统筹。

前提：本机 Ollama 已启动。
用法：backend/.venv/Scripts/python tests/e2e_lead.py [领头人用的模型] [成员用的模型]
领头人需要能按格式分派任务，建议用稍大一点的模型；默认取本机最大的模型领头、最小的做成员。
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
    done = []
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 600))
        # events are broadcast to every client, so ignore other conversations that may be active
        if (ev.get("message") or ev).get("conv_id", conv_id) != conv_id:
            continue
        if ev["type"] == "message" and ev["message"].get("role") == "agent" and not ev["message"]["streaming"]:
            done.append(ev["message"])
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return done


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=600) as c:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        lead_model = args[0] if args else STRONG
        member_model = args[1] if len(args) > 1 else FAST
        print("领头人模型: %s   成员模型: %s\n" % (lead_model, member_model))
        made = {"providers": [], "agents": [], "convs": []}
        try:
            p = await make_provider(c, "lead-e2e")
            made["providers"].append(p["id"])

            async def agent(name, desc, model, prompt=""):
                a = (await c.post(API + "/agents", json={"no_tools": True, "name": name, "description": desc, "provider_id": p["id"], "model": model, "system_prompt": prompt})).json()
                made["agents"].append(a["id"])
                return a

            boss = await agent("老周", "团队负责人，负责拆解任务和汇总", lead_model, "你是团队负责人，做事干练。")

            # ---------- 会话内创建智能体 ----------
            conv = (await c.post(API + "/conversations", json={"agent_ids": [boss["id"]]})).json()
            made["convs"].append(conv["id"])
            r = (await c.post(API + "/conversations/%s/agents" % conv["id"], json={"no_tools": True, 
                "name": "春生", "description": "诗人，只写关于春天的短诗", "provider_id": p["id"], "model": member_model,
                "system_prompt": "你是诗人，只用一两句话写诗。"})).json()
            local = r["agent"]
            check("会话内创建：智能体归属本会话", local["conv_id"] == conv["id"])
            check("会话内创建：自动加入该会话", r["conversation"]["agent_ids"] == [boss["id"], local["id"]])
            r2 = (await c.post(API + "/conversations/%s/agents" % conv["id"], json={"no_tools": True, 
                "name": "秋实", "description": "诗人，只写关于秋天的短诗", "provider_id": p["id"], "model": member_model,
                "system_prompt": "你是诗人，只用一两句话写诗。", "global": True})).json()
            shared = r2["agent"]
            made["agents"].append(shared["id"])
            check("勾选加入全局：成为全局智能体并入会", shared["conv_id"] == "" and shared["id"] in r2["conversation"]["agent_ids"])

            other = (await c.post(API + "/conversations", json={"agent_ids": [local["id"], shared["id"]]})).json()
            made["convs"].append(other["id"])
            check("仅本会话的智能体不能被别的会话选用", other["agent_ids"] == [shared["id"]], other["agent_ids"])
            edited = (await c.put(API + "/agents/" + local["id"], json={**local, "description": "诗人，只写春天"})).json()
            check("编辑后归属不变", edited["conv_id"] == conv["id"])

            temp = (await c.post(API + "/conversations", json={"agent_ids": [boss["id"]]})).json()
            t1 = (await c.post(API + "/conversations/%s/agents" % temp["id"], json={"no_tools": True, "name": "临时甲"})).json()["agent"]
            t2 = (await c.post(API + "/conversations/%s/agents" % temp["id"], json={"no_tools": True, "name": "临时乙"})).json()["agent"]
            promoted = (await c.post(API + "/agents/%s/promote" % t2["id"])).json()
            made["agents"].append(t2["id"])
            await c.delete(API + "/conversations/" + temp["id"])
            left = {a["id"] for a in (await c.get(API + "/state")).json()["agents"]}
            check("之后加入全局：归属清空", promoted["conv_id"] == "")
            check("删除会话：仅本会话的智能体一并删除", t1["id"] not in left)
            check("删除会话：已加入全局的保留", t2["id"] in left and boss["id"] in left)

            # ---------- 领头统筹 ----------
            conv = (await c.get(API + "/state")).json()["conversations"]
            conv = next(x for x in conv if x["id"] == made["convs"][0])
            conv = (await c.put(API + "/conversations/" + conv["id"], json={**conv, "mode": "lead", "lead_id": boss["id"], "rounds": 1})).json()
            check("领头模式保存", conv["mode"] == "lead" and conv["lead_id"] == boss["id"])
            async with websockets.connect(WS) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                done = await turn(ws, conv["id"], "请安排春生写一句关于春天的诗，安排秋实写一句关于秋天的诗，等他们写完后，你把两句合在一起发给我。")
            for m in done:
                tag = "领头" if m.get("lead") else "成员"
                print("         [%s %s] %s%s" % (tag, m["agent_name"], m["content"][:90].replace("\n", " / "), ("  ERR " + m["error"]) if m["error"] else ""))
                for a in m.get("assignments") or []:
                    print("             -> 分派 @%s：%s" % (a["name"], a["task"][:60].replace("\n", " ")))
            check("全程无错误", all(not m["error"] for m in done), [(m["agent_name"], m["error"]) for m in done])
            check("领头人最先发言", bool(done) and done[0].get("lead") and done[0]["agent_name"] == "老周")
            first = next((m for m in done if m.get("assignments")), None)
            check("领头人按格式分派了任务", bool(first), done[0]["content"] if done else "")
            if first:
                names = [a["name"] for a in first["assignments"]]
                check("分派对象是两位成员", sorted(names) == ["春生", "秋实"], names)
                members = [m for m in done if m.get("task")]
                # 成员默认同时开工，谁先交付不一定：只要每个被分派的人都交付了
                check("被分派的成员各自完成任务", sorted(m["agent_name"] for m in members) == sorted(names) and all(m["content"] for m in members), [m["agent_name"] for m in members])
                check("成员是同时开工的（同一批次）", len({m.get("batch") for m in members}) == 1 and bool(members[0].get("batch")), [m.get("batch") for m in members])
                check("成员在领头人分派之后发言", done.index(members[0]) > done.index(first) if members else False)
                check("最后由领头人答复用户", done[-1].get("lead") and not done[-1].get("assignments") and done[-1]["content"], done[-1]["agent_name"])
                check("达到轮数上限后不再分派", sum(1 for m in done if m.get("assignments")) == 1)
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
