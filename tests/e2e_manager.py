"""端到端自检（真实 Ollama + 真实网址）：管家智能体添加、搜索、删除技能，添加 MCP。

前提：本机 Ollama 已启动；能访问 github.com。
用法：backend/.venv/Scripts/python tests/e2e_manager.py
"""
import asyncio
import json
import os
import sys

import httpx
import websockets

from harness import API, BASE, OLLAMA, WS, need_model, need_ollama, ollama_model  # noqa: E402  默认起临时服务器，不碰你的数据
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://github.com/anthropics/skills/tree/main/skills/pdf"
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content, decide):
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


def show(msgs):
    for m in msgs:
        if m["role"] == "tool":
            print("         [操作] %s -> %s（%s）%s" % (m["action"]["kind"], m["status"], m.get("granted"), (m.get("output") or "")[:70].replace("\n", " ")))
        elif m["role"] == "agent":
            print("         [%s] %s" % (m["agent_name"], m["content"][:110].replace("\n", " / ")))


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        before = {k["id"] for k in (await c.get(API + "/skills")).json()["skills"]}
        mcp_before = {m["id"] for m in (await c.get(API + "/mcp")).json()["servers"]}
        # 只用自己临时建的管家，绝不碰用户已有的管家和它的会话
        prov = need_model()
        boss = (await c.post(API + "/agents", json={"name": "测试管家", "manager": True, "provider_id": prov["id"], "model": prov["default_model"],
                                                    "system_prompt": "你是工具管家，用户给网址就直接添加，回答简短。"})).json()
        conv = (await c.post(API + "/conversations", json={"title": "测试管家会话", "agent_ids": [boss["id"]]})).json()
        try:
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()

                msgs = await turn(ws, conv["id"], URL, lambda m: "once")
                show(msgs)
                new = [k for k in (await c.get(API + "/skills")).json()["skills"] if k["id"] not in before]
                adds = [m for m in msgs if m["role"] == "tool" and m["action"]["kind"] == "skill_add"]
                check("只贴网址，管家就去添加技能", bool(adds), [m["content"][:200] for m in msgs if m["role"] == "agent"])
                check("添加前请用户确认", bool(adds) and adds[0]["granted"] == "允许一次", adds and adds[0].get("granted"))
                check("技能真的加进来了，内容来自网址", len(new) == 1 and new[0]["name"] == "pdf" and new[0]["source"], new)

                msgs = await turn(ws, conv["id"], "现在有哪些和 PDF 有关的技能？", lambda m: "deny")
                show(msgs)
                finds = [m for m in msgs if m["role"] == "tool" and m["action"]["kind"] == "skill_find"]
                check("搜索是只读操作，不打扰用户", bool(finds) and all(m["granted"] == "只读操作，无需确认" for m in finds), finds)
                check("搜索找到了刚添加的技能", any("pdf" in (m.get("output") or "") for m in finds))

                cfg = json.dumps({"mcpServers": {"mgr-test": {"command": sys.executable, "args": [os.path.join(HERE, "mcp_test_server.py")]}}})
                msgs = await turn(ws, conv["id"], "帮我添加这个 MCP 配置：" + cfg, lambda m: "once")
                show(msgs)
                added = [m for m in (await c.get(API + "/mcp")).json()["servers"] if m["id"] not in mcp_before]
                check("管家按配置添加了 MCP 并连上", len(added) == 1 and len(added[0]["tools"]) == 2, added)

                if new:
                    msgs = await turn(ws, conv["id"], "把刚才加的 pdf 技能删掉。", lambda m: "deny")
                    show(msgs)
                    rm = [m for m in msgs if m["role"] == "tool" and m["action"]["kind"] == "skill_remove"]
                    still = new[0]["id"] in {k["id"] for k in (await c.get(API + "/skills")).json()["skills"]}
                    check("删除前请确认，拒绝后没有删除", bool(rm) and rm[0]["status"] == "denied" and still, rm)
        finally:
            for k in (await c.get(API + "/skills")).json()["skills"]:
                if k["id"] not in before:
                    await c.delete(API + "/skills/" + k["id"])
            for m in (await c.get(API + "/mcp")).json()["servers"]:
                if m["id"] not in mcp_before:
                    await c.delete(API + "/mcp/" + m["id"])
            await c.delete(API + "/conversations/" + conv["id"])
            await c.delete(API + "/agents/" + boss["id"])
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
