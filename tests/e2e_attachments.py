"""端到端：消息附件（真实模型）。
1. 文本文件：上传一份表格，问里面的数字，智能体要答对（说明全文进了上下文）。
2. 图片 + 看图模型：上传一张纯红色图片，问颜色，要答出红色。
3. 图片 + 不支持看图的模型：不能报错，要正常回复（自动改成文字说明）。

前提：MAC_TEST_BASE_URL / MAC_TEST_API_KEY / MAC_TEST_MODEL（见 tests/README.md）。
看图模型用 MAC_TEST_VISION_MODEL（默认同 MAC_TEST_MODEL；glm-5.3-flash 能看图）；
第 3 项用 MAC_TEST_TEXT_MODEL（默认同 MAC_TEST_STRONG_MODEL），它看不看得懂图都行，只要不报错。
用法：python tests/e2e_attachments.py
"""
import asyncio
import json
import os
import struct
import sys
import zlib

import httpx
import websockets

from harness import API, FAST, STRONG, WS, make_provider, need_model  # noqa: E402  默认起临时服务器，不碰你的数据

VISION = os.environ.get("MAC_TEST_VISION_MODEL") or FAST
TEXT = os.environ.get("MAC_TEST_TEXT_MODEL") or STRONG
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:300] if extra and not cond else ""))
    if not cond:
        fails.append(name)


def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


async def turn(ws, conv_id, content, attachments):
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": [], "attachments": attachments}))
    out = {}
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 300))
        if ev["type"] == "message" and ev["message"].get("conv_id") == conv_id and not ev["message"].get("streaming"):
            out[ev["message"]["id"]] = ev["message"]
        if ev["type"] == "running" and ev.get("conv_id") == conv_id and not ev["running"]:
            return list(out.values())


async def main():
    need_model()
    async with httpx.AsyncClient(timeout=120) as c:
        made = {"providers": [], "agents": [], "convs": []}
        try:
            p = await make_provider(c, "attach-e2e")
            made["providers"].append(p["id"])

            async def agent(name, model):
                a = (await c.post(API + "/agents", json={"name": name, "provider_id": p["id"], "model": model, "no_tools": True,
                                                         "system_prompt": "回答简短，一两句话。"})).json()
                made["agents"].append(a["id"])
                conv = (await c.post(API + "/conversations", json={"agent_ids": [a["id"]]})).json()
                made["convs"].append(conv["id"])
                return conv["id"]

            async def upload(cid, name, data):
                r = await c.post(API + "/conversations/%s/attachments" % cid, params={"name": name}, content=data)
                r.raise_for_status()
                return r.json()

            async with websockets.connect(WS, ping_interval=None, max_size=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()

                cid = await agent("表格助理", FAST)
                csv = "产品,季度,销量\n星河,Q1,1203\n云杉,Q1,8817\n松果,Q1,452\n".encode("utf-8")
                a = await upload(cid, "销量.csv", csv)
                check("CSV 识别为文本附件", a["kind"] == "text", a)
                msgs = await turn(ws, cid, "附件里云杉的销量是多少？只回答数字。", [a])
                user = next((m for m in msgs if m["role"] == "user"), {})
                reply = " ".join(m.get("content") or "" for m in msgs if m["role"] == "agent")
                check("用户消息带着附件", [x["name"] for x in user.get("attachments") or []] == ["销量.csv"], user)
                check("读懂了文本附件里的数字", "8817" in reply, reply)

                red = png(64, 64, (220, 20, 20))
                cid = await agent("看图助理", VISION)
                img = await upload(cid, "颜色.png", red)
                check("PNG 识别为图片附件", img["kind"] == "image", img)
                msgs = await turn(ws, cid, "这张图片是什么颜色？只回答颜色。", [img])
                agent_msgs = [m for m in msgs if m["role"] == "agent"]
                reply = " ".join(m.get("content") or "" for m in agent_msgs)
                print("         看图模型（%s）：%s" % (VISION, reply[:120]))
                check("看图模型认出了红色", "红" in reply or "red" in reply.lower(), [m.get("error") for m in agent_msgs])

                cid = await agent("文字助理", TEXT)
                img = await upload(cid, "颜色.png", red)
                msgs = await turn(ws, cid, "这张图片是什么颜色？", [img])
                agent_msgs = [m for m in msgs if m["role"] == "agent"]
                reply = " ".join(m.get("content") or "" for m in agent_msgs)
                print("         另一个模型（%s）：%s" % (TEXT, reply[:160]))
                check("换一个模型（不一定能看图）也正常回复，不报错", reply.strip() and not any(m.get("error") for m in agent_msgs),
                      [m.get("error") for m in agent_msgs])
        finally:
            for cid in made["convs"]:
                await c.delete(API + "/conversations/" + cid)
            for aid in made["agents"]:
                await c.delete(API + "/agents/" + aid)
            for pid in made["providers"]:
                await c.delete(API + "/providers/" + pid)
    print("\n" + ("全部通过" if not fails else "失败：%s" % fails))
    sys.exit(1 if fails else 0)


asyncio.run(main())
