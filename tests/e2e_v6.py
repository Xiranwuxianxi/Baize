"""端到端自检（真实 Ollama + 真实 HTTP 客户端充当外部智能体）：
外部智能体接入、会话专属文件夹与文件链接、领头新建智能体前的确认、内容搜索、记录删除、添加渠道时拉取模型。

前提：本机 Ollama 已启动。会临时开启本地操作，结束后恢复原设置。
用法：backend/.venv/Scripts/python tests/e2e_v6.py
"""
import asyncio
import json
import os
import sys
import tempfile

import httpx
import websockets

from harness import API, BASE, FAST, STRONG, WS, channels, make_provider, need_model  # noqa: E402  默认起临时服务器，不碰你的数据
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content, decide=None, targets=None):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": targets or []}))
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


async def fake_external(c, token, reply):
    """A real HTTP client playing the outside agent: read the join text, poll, answer."""
    join = (await c.get(BASE + "/join/" + token)).text
    assert "/api/ext/" in join
    for _ in range(40):
        task = (await c.get(API + "/ext/%s/next?wait=5" % token, timeout=30)).json()
        if task.get("task_id"):
            await c.post(API + "/ext/%s/reply/%s" % (token, task["task_id"]), content=reply(task["prompt"]).encode("utf-8"),
                         headers={"Content-Type": "text/plain; charset=utf-8"})
            return task["prompt"]
    return None


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        before = (await c.get(API + "/settings")).json()
        made = {"providers": [], "agents": [], "convs": []}
        ws_root = tempfile.mkdtemp(prefix="mac-v6-")
        extra_dir = tempfile.mkdtemp(prefix="mac-v6-extra-")
        try:
            # ---- 添加渠道时拉取模型（未保存的配置） ----
            ch = channels()[0]
            r = await c.post(API + "/providers/preview-models", json={"protocol": ch["protocol"], "base_url": ch["base_url"], "api_key": ch["api_key"]})
            check("添加渠道前就能拉取模型", r.status_code == 200 and len(r.json()["models"]) >= 1, r.text)
            models = r.json().get("models", [])
            p = await make_provider(c, "v6")
            made["providers"].append(p["id"])

            # ---- 外部智能体 ----
            ext = (await c.post(API + "/agents", json={"name": "外援", "external": True, "ext_kind": "Claude Code", "no_tools": True})).json()
            made["agents"].append(ext["id"])
            check("外部智能体生成了连接口令", len(ext.get("ext_token") or "") > 10)
            check("未连接时显示离线", ext["id"] not in (await c.get(API + "/state")).json()["ext_online"])
            conv = (await c.post(API + "/conversations", json={"agent_ids": [ext["id"]]})).json()
            made["convs"].append(conv["id"])
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()
                agent_task = asyncio.ensure_future(fake_external(c, ext["ext_token"], lambda prompt: "外援收到：紫丁香-42"))
                await asyncio.sleep(1.5)
                check("轮询后显示已连接", ext["id"] in (await c.get(API + "/state")).json()["ext_online"])
                msgs = await turn(ws, conv["id"], "请回复暗号")
                prompt = await agent_task
                said = [m for m in msgs if m["role"] == "agent"]
                check("外部智能体收到的任务里带着用户的话", bool(prompt) and "请回复暗号" in prompt)
                check("外部智能体的回复出现在会话里", bool(said) and said[-1]["content"] == "外援收到：紫丁香-42" and not said[-1]["error"], said)

                # ---- 搜索聊天内容 ----
                hits = (await c.get(API + "/search", params={"q": "紫丁香-42"})).json()["hits"]
                check("搜索能找到聊天内容（不只标题）", any(h["conv_id"] == conv["id"] and "紫丁香-42" in h["text"] for h in hits), hits)

                # ---- 会话专属文件夹 + 额外文件夹 + 文件链接 ----
                await c.put(API + "/settings", json={"local": {"enabled": True, "workspace": ws_root}})
                ops = (await c.post(API + "/agents", json={"name": "写手", "provider_id": p["id"], "model": FAST, "system_prompt": "你做事干练。"})).json()
                made["agents"].append(ops["id"])
                c2 = (await c.post(API + "/conversations", json={"title": "文件测试", "agent_ids": [ops["id"]]})).json()
                made["convs"].append(c2["id"])
                c2 = (await c.put(API + "/conversations/" + c2["id"], json={**c2, "folders": [extra_dir, "Z:/definitely/missing"]})).json()
                check("额外文件夹只保留存在的路径", c2["folders"] == [os.path.abspath(extra_dir)], c2["folders"])
                msgs = await turn(ws, c2["id"], "请使用本地操作，把文字 hello-v6 写入文件 note.txt（用 <write> 标签），不要解释，直接操作。", decide=lambda m: "once")
                writes = [m for m in msgs if m["role"] == "tool" and m["action"].get("kind") == "write" and m["status"] == "done"]
                check("文件写进了会话自己的文件夹", bool(writes) and os.path.dirname(writes[0]["path"]) != os.path.realpath(ws_root)
                      and os.path.realpath(writes[0]["path"]).startswith(os.path.realpath(ws_root)), writes and writes[0]["path"])
                if writes:
                    r = await c.get(API + "/files", params={"conv": c2["id"], "path": writes[0]["action"]["path"]})
                    check("文件链接能直接打开", r.status_code == 200 and "hello-v6" in r.text, r.status_code)
                    r = await c.get(API + "/files", params={"conv": c2["id"], "path": "../../../windows/win.ini"})
                    check("文件链接不能跳出会话文件夹", r.status_code in (403, 404), r.status_code)
                    other = (await c.post(API + "/conversations", json={"title": "别的会话", "agent_ids": [ops["id"]]})).json()
                    made["convs"].append(other["id"])
                    r = await c.get(API + "/files", params={"conv": other["id"], "path": "note.txt"})
                    check("别的会话看不到这个会话的文件", r.status_code == 404, r.status_code)

                # ---- 领头新建智能体前确认 ----
                boss = (await c.post(API + "/agents", json={"name": "v6总管", "provider_id": p["id"], "model": FAST, "no_tools": True,
                                                            "description": "组建团队", "system_prompt": "你是团队负责人，回答简短。"})).json()
                made["agents"].append(boss["id"])
                c3 = (await c.post(API + "/conversations", json={"agent_ids": [boss["id"]], "mode": "lead", "lead_id": boss["id"], "rounds": 1})).json()
                made["convs"].append(c3["id"])
                ask = "现有智能体都不合适。请新建一个叫「对联师」的智能体（用 <agent> 标签），让它写一副关于春节的对联。"
                msgs = await turn(ws, c3["id"], ask, decide=lambda m: "deny")
                cards = [m for m in msgs if m["role"] == "tool" and m["action"].get("kind") == "hire"]
                now = (await c.get(API + "/state")).json()
                check("新建前弹出确认卡片", bool(cards), [m["content"][:160] for m in msgs if m["role"] == "agent"])
                check("拒绝后没有新建", not any(a.get("conv_id") == c3["id"] for a in now["agents"]))
                msgs = await turn(ws, c3["id"], "这次我同意。" + ask, decide=lambda m: "once")
                now = (await c.get(API + "/state")).json()
                hired = [a for a in now["agents"] if a.get("conv_id") == c3["id"]]
                check("同意后新建并入会", bool(hired) and hired[0]["id"] in next(x for x in now["conversations"] if x["id"] == c3["id"])["agent_ids"])

            # ---- 聊天记录管理 ----
            rec = (await c.get(API + "/records")).json()
            check("记录列表带有数据库位置和大小", rec["db_path"].endswith("mac.db") and rec["db_bytes"] > 0)
            folder = next((x["folder"] for x in rec["conversations"] if x["id"] == c2["id"]), "")
            r = (await c.post(API + "/records/delete", json={"ids": [c2["id"]], "files": True})).json()
            made["convs"].remove(c2["id"])
            check("删除选中的会话", r["removed"] == 1 and not any(x["id"] == c2["id"] for x in (await c.get(API + "/state")).json()["conversations"]))
            check("同时删除了会话文件夹", bool(folder) and not os.path.exists(folder), folder)
        finally:
            await c.put(API + "/settings", json={"local": {"enabled": before["local"]["enabled"], "workspace": before["local"]["workspace"]}})
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
            for pid in made["providers"]:
                await c.delete(API + "/providers/" + pid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
