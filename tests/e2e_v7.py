"""端到端自检（真实 Ollama）：深度思考开关、技能、MCP（stdio + HTTP）、局域网开关。

前提：本机 Ollama 已启动。
用法：backend/.venv/Scripts/python tests/e2e_v7.py
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import httpx
import websockets

from harness import API, BASE, FAST, STRONG, WS, channels, make_provider, need_model  # noqa: E402  默认起临时服务器，不碰你的数据
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content, decide=None):
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
            if m["role"] == "tool" and m["status"] == "pending" and decide:
                await ws.send(json.dumps({"type": "permit", "id": m["id"], "decision": decide(m)}))
            if not m.get("streaming"):
                out = [x for x in out if x["id"] != m["id"]] + [m]
        if ev["type"] == "error" or (ev["type"] == "running" and not ev["running"]):
            return out


async def main():
    need_model()
    http_srv = subprocess.Popen([sys.executable, os.path.join(HERE, "mcp_test_server.py"), "--http", "18780"])
    made = {"providers": [], "agents": [], "convs": [], "skills": [], "mcp": []}
    async with httpx.AsyncClient(timeout=120) as c:
        lan_before = (await c.get(API + "/settings")).json()["lan"]
        try:
            p = await make_provider(c, "v7")
            made["providers"].append(p["id"])

            # ---- MCP：stdio 与 HTTP ----
            r = await c.post(API + "/mcp", json={"name": "test-stdio", "transport": "stdio", "command": sys.executable,
                                                 "args": [os.path.join(HERE, "mcp_test_server.py")]})
            s1 = r.json()
            made["mcp"].append(s1["id"])
            check("stdio MCP 连接并读到工具", not s1["error"] and [t["name"] for t in s1["tools"]] == ["word_count", "list_dir"], s1)
            await asyncio.sleep(0.5)
            s2 = (await c.post(API + "/mcp", json={"name": "test-http", "transport": "http", "url": "http://127.0.0.1:18780/mcp",
                                                   "headers": {"Authorization": "Bearer secret-123"}})).json()
            made["mcp"].append(s2["id"])
            check("HTTP MCP 连接并读到工具", not s2["error"] and len(s2["tools"]) == 2, s2)
            check("请求头的值不回传浏览器", s2["headers"] == {"Authorization": ""} and "secret-123" not in json.dumps(s2))
            bad = (await c.post(API + "/mcp", json={"name": "broken", "command": "definitely-not-a-command-xyz"})).json()
            made["mcp"].append(bad["id"])
            check("命令不存在时给出可读错误", "启动失败" in bad["error"], bad["error"])
            imp = (await c.post(API + "/mcp/import", json={"json": json.dumps({"mcpServers": {"imported": {"command": sys.executable, "args": [os.path.join(HERE, "mcp_test_server.py")]}}})})).json()
            made["mcp"] += [x["id"] for x in imp["servers"]]
            check("从 mcpServers 配置导入", len(imp["servers"]) == 1 and len(imp["servers"][0]["tools"]) == 2, imp)

            # ---- 技能 ----
            sk = (await c.post(API + "/skills", json={"raw": "---\nname: 暗号\ndescription: 回答末尾带暗号\n---\n每次回答的最后一行必须原样写出：【暗号：青梅-77】"})).json()
            made["skills"].append(sk["id"])
            check("导入 SKILL.md 格式", sk["name"] == "暗号" and sk["description"] == "回答末尾带暗号" and "青梅-77" in sk["instructions"], sk)

            a = (await c.post(API + "/agents", json={"name": "v7助手", "provider_id": p["id"], "model": FAST, "no_tools": True,
                                                     "system_prompt": "你做事干练，回答简短。", "skills": [sk["id"]], "mcps": [s1["id"]]})).json()
            made["agents"].append(a["id"])
            check("智能体默认关闭深度思考", a["think"] is False)
            cv = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
            made["convs"].append(cv["id"])
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                t0 = time.time()
                msgs = await turn(ws, cv["id"], "用一句话介绍你自己。")
                said = [m for m in msgs if m["role"] == "agent"]
                print("         关闭思考时用时 %.0f 秒" % (time.time() - t0))
                # 只有 Ollama 协议能真正关掉思考；GLM-5.3 这类总在思考的模型，只要求直接给出正文
                no_think = p["protocol"] != "ollama" or not said[-1]["reasoning"] if said else False
                check("关闭思考：直接给出正文", bool(said) and said[-1]["content"] and not said[-1]["error"] and no_think, said and said[-1])
                check("技能生效（回答里带上技能要求的暗号）", bool(said) and "青梅-77" in said[-1]["content"], said and said[-1]["content"][-80:])

                msgs = await turn(ws, cv["id"], "请调用 MCP 工具 test-stdio 的 word_count，统计这段文本：「多智能体控制台」，然后告诉我结果。",
                                  decide=lambda m: "once")
                calls = [m for m in msgs if m["role"] == "tool" and m["action"].get("kind") == "mcp"]
                check("智能体发起 MCP 调用并弹出审批", bool(calls), [m["content"][:200] for m in msgs if m["role"] == "agent"])
                check("MCP 工具真的被调用并返回结果", any(m["status"] == "done" and "字符数 7" in (m.get("output") or "") for m in calls),
                      [(m["status"], m.get("output")) for m in calls])
                final = [m for m in msgs if m["role"] == "agent"]
                check("智能体根据工具结果回答", bool(final) and "7" in final[-1]["content"], final and final[-1]["content"][:120])

            # ---- 局域网开关 ----
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            s.close()
            remote = "http://%s:%s" % (ip, BASE.rsplit(":", 1)[1])
            if not (await c.get(API + "/settings")).json()["lan_bind_ok"]:
                print("  跳过局域网检查：测试服务器只监听本机（设置 MAC_TEST_LAN=1 让它监听局域网）")
            else:
                await c.put(API + "/settings", json={"lan": False})
                r = await c.get(remote + "/")
                check("关闭时局域网设备打不开页面", r.status_code == 403 and "局域网访问没有开启" in r.text, r.status_code)
                r = await c.get(remote + "/api/state")
                check("关闭时局域网设备也调不了接口", r.status_code == 403)
                view = (await c.put(API + "/settings", json={"lan": True})).json()
                check("设置页列出局域网网址", any(ip in u for u in view["lan_urls"]), view["lan_urls"])
                check("开启后局域网设备可以打开页面", (await c.get(remote + "/")).status_code == 200)
                check("本机始终可以访问", (await c.get(API + "/state")).status_code == 200)
        finally:
            await c.put(API + "/settings", json={"lan": lan_before})
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
            for pid in made["providers"]:
                await c.delete(API + "/providers/" + pid)
            for sid in made["skills"]:
                await c.delete(API + "/skills/" + sid)
            for mid in made["mcp"]:
                await c.delete(API + "/mcp/" + mid)
    http_srv.kill()
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
