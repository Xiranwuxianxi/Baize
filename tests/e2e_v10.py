"""端到端自检（真实服务）：用已配置的云端渠道跑领头统筹、经验库的判断标准、命令行模式的外部智能体。

前提：至少有一个可用的渠道；本机装了 Claude Code（claude）和 / 或 Kimi CLI（kimi）。
用法：backend/.venv/Scripts/python tests/e2e_v10.py
"""
import asyncio
import json
import shutil
import sys

import httpx
import websockets

from harness import API, BASE, OLLAMA, WS, need_model, need_ollama, ollama_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content, targets=None):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": targets or []}))
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
        print("渠道: %s / %s\n" % (prov["name"], prov["default_model"]))
        lessons_before = {x["id"] for x in (await c.get(API + "/lessons")).json()["lessons"]}
        made = {"agents": [], "convs": []}

        async def agent(name, **kw):
            a = (await c.post(API + "/agents", json={"name": name, "provider_id": prov["id"], "model": prov["default_model"], "no_tools": True, **kw})).json()
            made["agents"].append(a["id"])
            return a

        async def conv(ids, **kw):
            cv = (await c.post(API + "/conversations", json={"agent_ids": ids, **kw})).json()
            made["convs"].append(cv["id"])
            return cv

        try:
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()

                # ---- 云端模型跑领头统筹 ----
                boss = await agent("测试总管", description="分派任务", system_prompt="你是团队负责人，回答简短。")
                poet = await agent("测试诗人", description="只写短诗", system_prompt="你是诗人，只写一句诗。")
                cv = await conv([boss["id"], poet["id"]], mode="lead", lead_id=boss["id"], rounds=1)
                msgs = await turn(ws, cv["id"], "请安排测试诗人写一句关于雪的诗，然后转给我。")
                said = [m for m in msgs if m["role"] == "agent"]
                check("云端模型：领头分派、成员完成、领头答复", any(m["agent_id"] == poet["id"] and m.get("task") for m in said)
                      and said[-1]["agent_id"] == boss["id"] and not any(m["error"] for m in said), [(m["agent_name"], m["error"]) for m in said])

                # ---- 经验库：普通对话不记，纠正后记，内容具体 ----
                lesson_new = lambda all_: [x for x in all_ if x["id"] not in lessons_before]  # noqa: E731
                a = await agent("测试助理", system_prompt="回答简短。")
                cv2 = await conv([a["id"]])
                await turn(ws, cv2["id"], "今天适合做什么？随便说一句。")
                await turn(ws, cv2["id"], "给我讲个简短的冷笑话。")
                normal = lesson_new((await c.get(API + "/lessons")).json()["lessons"])
                check("普通对话不记经验", not normal, [x["text"] for x in normal])
                await turn(ws, cv2["id"], "给我们公司的新项目起个代号。")
                msgs = await turn(ws, cv2["id"], "不对。公司规定：项目代号一律用「白鹭-」开头，后面跟三位数字，例如 白鹭-007。以后别再搞错。")
                got = lesson_new((await c.get(API + "/lessons")).json()["lessons"])
                print("         记下的经验：", [x["text"] for x in got])
                check("被纠正后自动记下具体的经验并直接生效", any("白鹭" in x["text"] and not x.get("pending") for x in got), [m["content"][:160] for m in msgs if m["role"] == "agent"])
                b = await agent("另一个助理", system_prompt="回答简短。")
                cv3 = await conv([b["id"]])
                msgs = await turn(ws, cv3["id"], "给一个新项目起代号，只回答代号本身。")
                ans = next((m["content"] for m in msgs if m["role"] == "agent"), "")
                print("         另一个智能体：", ans[:40])
                check("另一个智能体照着经验做", "白鹭-" in ans, ans)

                # ---- 外部智能体：命令行直接调用，不需要开窗口 ----
                for kind, cmd, exe in (("Claude Code", "claude -p --output-format text", "claude"), ("Kimi Code", "kimi --quiet", "kimi")):
                    if not shutil.which(exe):
                        print("         跳过 %s：本机没有安装" % kind)
                        continue
                    ext = (await c.post(API + "/agents", json={"name": kind, "external": True, "ext_kind": kind, "ext_mode": "cli", "ext_cmd": cmd, "no_tools": True})).json()
                    made["agents"].append(ext["id"])
                    cv4 = await conv([ext["id"]])
                    msgs = await turn(ws, cv4["id"], "这是一次连通测试。请只回复四个字：收到测试")
                    m = next((x for x in msgs if x["role"] == "agent"), {})
                    print("         %s 回复：%s" % (kind, (m.get("content") or m.get("error") or "")[:80].replace("\n", " ")))
                    check("%s 命令行模式直接调用并拿到回复" % kind, bool(m.get("content")) and "收到测试" in m["content"] and not m.get("error"), m.get("error"))
        finally:
            for x in (await c.get(API + "/lessons")).json()["lessons"]:
                if x["id"] not in lessons_before:
                    await c.delete(API + "/lessons/" + x["id"])
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
