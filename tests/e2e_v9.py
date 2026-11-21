"""端到端自检（真实 Ollama）：管家能用 bash 执行命令、共享经验库的记录与跨智能体生效、外部智能体精简接入。

前提：本机 Ollama 已启动。会临时开启本地操作，结束后恢复。
用法：backend/.venv/Scripts/python tests/e2e_v9.py
"""
import asyncio
import json
import sys

import httpx
import websockets

from harness import API, BASE, OLLAMA, WS, need_model, need_ollama, ollama_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content, decide=lambda m: "once"):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": []}))
    out = []
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 600))
        if ev["type"] == "refresh":
            continue
        if (ev.get("message") or ev.get("conversation") or ev).get("conv_id", ev.get("conversation", {}).get("id", conv_id)) != conv_id:
            continue
        if ev["type"] == "message":
            m = ev["message"]
            if m["role"] == "tool" and m["status"] == "pending":
                await ws.send(json.dumps({"type": "permit", "id": m["id"], "decision": decide(m)}))
            if not m.get("streaming"):
                out = [x for x in out if x["id"] != m["id"]] + [m]
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return out


def said(msgs):
    return [m for m in msgs if m["role"] == "agent"]


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        before = (await c.get(API + "/settings")).json()
        lessons_before = {x["id"] for x in (await c.get(API + "/lessons")).json()["lessons"]}
        made = {"providers": [], "agents": [], "convs": []}
        try:
            await c.put(API + "/settings", json={"local": {"enabled": True, "shell": "auto"}, "lessons": True})
            st = (await c.get(API + "/settings")).json()["local"]
            check("Windows 上自动选用 bash", st["shell_name"] == "bash" and st["bash_found"], st)

            # ---- 管家执行 bash 命令（管道） ----
            # 只用自己临时建的管家，绝不碰用户已有的管家和它的会话
            prov = need_model()
            boss = (await c.post(API + "/agents", json={"name": "测试管家", "manager": True, "provider_id": prov["id"], "model": prov["default_model"], "system_prompt": "你是工具管家，回答简短。"})).json()
            made["agents"].append(boss["id"])
            mgr = {"agent": boss, "conversation": (await c.post(API + "/conversations", json={"agent_ids": [boss["id"]]})).json()}
            made["convs"].append(mgr["conversation"]["id"])
            check("管家不再被禁止本地操作", mgr["agent"]["no_tools"] is False)
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                msgs = await turn(ws, mgr["conversation"]["id"], "请在终端执行这条命令并告诉我输出：echo multi-agent | tr a-z A-Z")
                runs = [m for m in msgs if m["role"] == "tool" and m["action"]["kind"] == "run"]
                check("管家直接执行命令而不是拒绝", bool(runs), [m["content"][:200] for m in said(msgs)])
                check("bash 管道命令执行成功", any("MULTI-AGENT" in (m.get("output") or "") for m in runs), [(m["action"], m.get("output")) for m in runs])

                # ---- 共享经验库 ----
                p = prov
                a = (await c.post(API + "/agents", json={"name": "甲方助理", "provider_id": p["id"], "model": p["default_model"], "no_tools": True, "system_prompt": "回答简短。"})).json()
                b = (await c.post(API + "/agents", json={"name": "乙方助理", "provider_id": p["id"], "model": p["default_model"], "no_tools": True, "system_prompt": "回答简短。"})).json()
                made["agents"] += [a["id"], b["id"]]
                c1 = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
                c2 = (await c.post(API + "/conversations", json={"agent_ids": [b["id"]]})).json()
                made["convs"] += [c1["id"], c2["id"]]
                await turn(ws, c1["id"], "我们公司的项目代号是什么？随便猜一个。")
                msgs = await turn(ws, c1["id"], "错了。我们公司规定：所有项目代号一律以「青鸟-」开头，后面跟三位数字，例如 青鸟-042。以后别再搞错。")
                learned = [x for x in (await c.get(API + "/lessons")).json()["lessons"] if x["id"] not in lessons_before]
                print("         记下的经验：", [x["text"] for x in learned])
                check("被纠正后自己记下一条经验", bool(learned) and any("青鸟" in x["text"] for x in learned), [m["content"][:200] for m in said(msgs)])
                check("经验标签不显示在正文里", all("<lesson>" not in m["content"] for m in said(msgs)))
                review = (await c.get(API + "/settings")).json().get("lessons_review", False)
                check("经验按设置生效（需要审核时先待确认，否则直接生效）", all(bool(x.get("pending")) == bool(review) for x in learned), learned)
                for x in learned:  # 只保留和这次纠正有关的那条
                    if "青鸟" in x["text"]:
                        await c.put(API + "/lessons/" + x["id"], json={**x, "pending": False})
                    else:
                        await c.delete(API + "/lessons/" + x["id"])
                msgs = await turn(ws, c2["id"], "给我们的新项目起一个代号，只回答代号本身。")
                ans = said(msgs)[-1]["content"] if said(msgs) else ""
                print("         另一个智能体的回答：", ans[:60])
                check("另一个智能体在另一个会话里遵守了这条经验", "青鸟-" in ans, ans)

            # ---- 经验可编辑 ----
            if learned:
                x = learned[0]
                r = (await c.put(API + "/lessons/" + x["id"], json={**x, "text": x["text"] + "（已核对）", "pinned": True})).json()
                check("经验可编辑、可置顶", r["text"].endswith("（已核对）") and r["pinned"])

            # ---- 外部智能体：不需要角色设定 ----
            ext = (await c.post(API + "/agents", json={"name": "Claude Code", "external": True, "ext_kind": "Claude Code", "no_tools": True})).json()
            made["agents"].append(ext["id"])
            check("外部智能体只要名字和类型就能接入", ext["external"] and ext["ext_token"] and ext["system_prompt"] == "")
        finally:
            await c.put(API + "/settings", json={"local": {"enabled": before["local"]["enabled"], "shell": before["local"]["shell"]}, "lessons": before["lessons"]})
            for x in (await c.get(API + "/lessons")).json()["lessons"]:
                if x["id"] not in lessons_before:
                    await c.delete(API + "/lessons/" + x["id"])
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
            for pid in made["providers"]:
                await c.delete(API + "/providers/" + pid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
