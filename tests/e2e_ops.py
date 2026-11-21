"""端到端自检（真实模型）：配置文件、总智能体拉人、在「设置」里管理本地操作、四档授权。

需要一个专门的测试实例，不要对着日常使用的实例跑。准备一份 config.yaml，只需要：
  - server.host 为 127.0.0.1（不要在文件里开启 local_access，本脚本通过设置接口开启）
  - 一个可用的渠道；一个 chief: true 的智能体；至少一个其他全局智能体
用 MAC_CONFIG / MAC_DATA_DIR 指向临时位置启动后端，再运行：
  backend/.venv/Scripts/python tests/e2e_ops.py http://127.0.0.1:18770 [用作工作区的临时目录]
"""
import asyncio
import json
import os
import sys
import tempfile

import httpx
import websockets

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18770").rstrip("/")
WORKSPACE = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="mac-ws-")
API = BASE + "/api"
WS = BASE.replace("http", "ws", 1) + "/ws"
fails = []


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("  -> " + str(extra)[:400] if extra and not cond else ""))
    if not cond:
        fails.append(name)


async def turn(ws, conv_id, content, decide=None):
    """发一条消息并等会话跑完。decide(tool消息) 返回 deny / once / five / forever，用来回应审批请求。"""
    await ws.send(json.dumps({"type": "send", "conv_id": conv_id, "content": content, "targets": []}))
    out, asked = [], []
    while True:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 600))
        if ev["type"] == "refresh":
            continue
        if (ev.get("message") or ev.get("conversation") or ev).get("conv_id", ev.get("conversation", {}).get("id", conv_id)) != conv_id:
            continue
        if ev["type"] == "message":
            m = ev["message"]
            if m["role"] == "tool" and m["status"] == "pending" and m["id"] not in asked:
                asked.append(m["id"])
                await ws.send(json.dumps({"type": "permit", "id": m["id"], "decision": decide(m) if decide else "deny"}))
            if not m.get("streaming"):
                out = [x for x in out if x["id"] != m["id"]] + [m]
        if ev["type"] == "error":
            print("         error event:", ev.get("text"))
            return out, asked
        if ev["type"] == "running" and not ev["running"]:
            return out, asked


def show(msgs):
    for m in msgs:
        if m["role"] == "tool":
            print("         [操作 %s] %s -> %s（%s）" % (m["agent_name"], json.dumps(m["action"], ensure_ascii=False)[:70], m["status"], m.get("granted")))
        elif m["role"] == "notice":
            print("         [提示] " + m["content"])
        elif m["role"] == "agent":
            print("         [%s] %s%s" % (m["agent_name"], m["content"][:90].replace("\n", " / "), ("  ERR " + m["error"]) if m["error"] else ""))


def tools_of(msgs):
    return [m for m in msgs if m["role"] == "tool"]


async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        s = (await c.get(API + "/state")).json()
        chief = next((a for a in s["agents"] if a.get("chief")), None)
        others = [a for a in s["agents"] if not a.get("chief") and not a.get("conv_id")]
        check("配置文件已加载", bool(s["env"]["config_file"]) and not s["env"]["config_error"], s["env"])
        check("配置声明的渠道与智能体已入库并标记", all(p["managed"] for p in s["providers"]) and bool(chief) and chief.get("managed"))
        if not (chief and others):
            sys.exit("测试实例不满足前提，见文件开头的说明")
        made = []
        try:
            # ---- 设置：不碰配置文件，全部通过接口 ----
            before = (await c.get(API + "/settings")).json()
            check("默认关闭本地操作", before["local"]["enabled"] is False and before["local"]["usable"] is False)
            check("本机访问可以修改权限设置", before["can_admin"] is True)
            r = await c.put(API + "/settings", json={"local": {"workspace": WORKSPACE}})
            check("在设置里更改工作区", r.status_code == 200 and os.path.samefile(r.json()["local"]["workspace"], WORKSPACE), r.text)
            r = await c.put(API + "/settings", json={"local": {"workspace": ""}})
            check("拒绝空的工作区路径", r.status_code == 400, r.text)
            r = await c.put(API + "/settings", json={"local": {"enabled": True, "timeout": 30}})
            now = r.json()
            check("在设置里开启本地操作并立即生效", now["local"]["enabled"] and now["local"]["usable"] and now["local"]["timeout"] == 30, now["local"])
            check("状态接口同步反映", (await c.get(API + "/state")).json()["env"]["local"]["usable"] is True)

            target = others[0]
            async with websockets.connect(WS, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "auth", "token": ""}))
                await ws.recv()

                # ---- 总智能体拉人 ----
                conv = (await c.post(API + "/conversations", json={"agent_ids": [chief["id"]], "mode": "lead", "lead_id": chief["id"], "rounds": 1})).json()
                made.append(conv["id"])
                msgs, _ = await turn(ws, conv["id"], "请安排%s写一句关于月亮的短诗，然后把他的诗转给我。" % target["name"])
                show(msgs)
                after = next(x for x in (await c.get(API + "/state")).json()["conversations"] if x["id"] == conv["id"])
                said = [m for m in msgs if m["role"] == "agent"]
                check("总智能体把会话外的智能体拉进了会话", target["id"] in after["agent_ids"], after["agent_ids"])
                check("被拉进来的智能体完成任务，最后由总智能体答复",
                      any(m["agent_id"] == target["id"] and m.get("task") and m["content"] for m in said) and said[-1]["agent_id"] == chief["id"])

                solo = (await c.post(API + "/conversations", json={"agent_ids": [chief["id"]]})).json()
                made.append(solo["id"])

                def write_ask(name, text):
                    return "请使用本地操作，把文字 %s 写入文件 %s（用 <write> 标签），不要解释，直接操作。" % (text, name)

                # ---- 不允许 ----
                msgs, asked = await turn(ws, solo["id"], write_ask("deny.txt", "nope"), decide=lambda m: "deny")
                show(msgs)
                ops = tools_of(msgs)
                check("智能体发出了操作请求，并弹出审批", bool(ops) and len(asked) >= 1, [m["content"][:160] for m in msgs if m["role"] == "agent"])
                check("不允许：没有执行", bool(ops) and all(m["status"] == "denied" for m in ops) and not os.path.exists(os.path.join(WORKSPACE, "deny.txt")))
                check("审批卡片带有完整的文件路径", bool(ops) and os.path.isabs(ops[0].get("path") or "") and ops[0]["path"].endswith("deny.txt"), ops and ops[0].get("path"))
                check("路径落在工作区里", bool(ops) and os.path.normcase(ops[0]["path"]).startswith(os.path.normcase(os.path.realpath(WORKSPACE))), ops and ops[0].get("path"))

                # ---- 允许一次：下一次还要再问 ----
                msgs, asked = await turn(ws, solo["id"], "这次同意。" + write_ask("once.txt", "hello-once"), decide=lambda m: "once")
                show(msgs)
                check("允许一次：文件写入了工作区", os.path.exists(os.path.join(WORKSPACE, "once.txt")), [(m["status"], m.get("output")) for m in tools_of(msgs)])
                msgs, asked = await turn(ws, solo["id"], write_ask("once2.txt", "again"), decide=lambda m: "deny")
                check("允许一次之后，下一个操作仍然询问", len(asked) >= 1, [m.get("granted") for m in tools_of(msgs)])

                # ---- 允许五次：这一次 + 之后四次不问 ----
                msgs, asked = await turn(ws, solo["id"], write_ask("five1.txt", "f1"), decide=lambda m: "five")
                show(msgs)
                left = next(x for x in (await c.get(API + "/state")).json()["conversations"] if x["id"] == solo["id"]).get("approve_left")
                check("允许五次：执行并记下剩余 4 次", os.path.exists(os.path.join(WORKSPACE, "five1.txt")) and left == 4, left)
                msgs, asked = await turn(ws, solo["id"], write_ask("five2.txt", "f2"), decide=lambda m: "deny")
                show(msgs)
                left = next(x for x in (await c.get(API + "/state")).json()["conversations"] if x["id"] == solo["id"]).get("approve_left")
                check("额度内的操作不再询问，并扣减次数", not asked and os.path.exists(os.path.join(WORKSPACE, "five2.txt")) and left == 4 - len(tools_of(msgs)), (asked, left, len(tools_of(msgs))))

                # ---- 永久允许：对这个智能体，在别的会话里也不再问 ----
                fresh = (await c.post(API + "/conversations", json={"agent_ids": [chief["id"]]})).json()
                made.append(fresh["id"])
                msgs, asked = await turn(ws, fresh["id"], "请使用本地操作执行命令 echo forever-ok（用 <run> 标签），然后告诉我输出。", decide=lambda m: "forever")
                show(msgs)
                runs = [m for m in tools_of(msgs) if m["action"]["kind"] == "run"]
                check("永久允许：命令执行并拿到输出", any("forever-ok" in (m.get("output") or "") for m in runs), [(m["status"], m.get("output")) for m in runs])
                check("命令卡片带有执行目录", bool(runs) and os.path.samefile(runs[0]["cwd"], WORKSPACE), runs and runs[0].get("cwd"))
                view = (await c.get(API + "/settings")).json()
                check("设置页列出被永久授权的智能体", [g["id"] for g in view["grants"]] == [chief["id"]], view["grants"])
                another = (await c.post(API + "/conversations", json={"agent_ids": [chief["id"]]})).json()
                made.append(another["id"])
                msgs, asked = await turn(ws, another["id"], write_ask("forever.txt", "f"), decide=lambda m: "deny")
                check("永久允许在新会话里同样生效", not asked and os.path.exists(os.path.join(WORKSPACE, "forever.txt")), asked)

                # ---- 撤销 ----
                view = (await c.post(API + "/agents/%s/revoke" % chief["id"])).json()
                check("在设置里撤销永久授权", view["grants"] == [])
                msgs, asked = await turn(ws, another["id"], write_ask("after-revoke.txt", "x"), decide=lambda m: "deny")
                check("撤销后重新开始询问", len(asked) >= 1 and not os.path.exists(os.path.join(WORKSPACE, "after-revoke.txt")), asked)

                # ---- 关掉总开关 ----
                off = (await c.put(API + "/settings", json={"local": {"enabled": False}})).json()
                msgs, asked = await turn(ws, another["id"], write_ask("off.txt", "x"), decide=lambda m: "once")
                check("关闭总开关后不再有任何操作", off["local"]["usable"] is False and not tools_of(msgs) and not os.path.exists(os.path.join(WORKSPACE, "off.txt")))

            files = [f["path"] for f in (await c.get(API + "/settings")).json()["files"]]
            check("设置页能看到工作区里的文件", {"once.txt", "five1.txt", "five2.txt", "forever.txt"} <= set(files), files)

            # ---- 访问口令也在设置里管 ----
            r = await c.put(API + "/settings", json={"token": "s3cret-口令"})
            check("在设置里设置访问口令", r.status_code == 200 and r.json()["token_set"] is True, r.text)
            check("设置后未带口令的请求被拒绝", (await c.get(API + "/state")).status_code == 401)
            auth = {"X-Access-Token": "s3cret-%E5%8F%A3%E4%BB%A4"}
            check("带口令可以访问", (await c.get(API + "/state", headers=auth)).status_code == 200)
            r = await c.put(API + "/settings", json={"token": ""}, headers=auth)
            check("在设置里清除访问口令", r.status_code == 200 and (await c.get(API + "/state")).status_code == 200)
        finally:
            await c.put(API + "/settings", json={"local": {"enabled": False}})
            for cid in made:
                await c.delete(API + "/conversations/" + cid)
    print("\n%s" % ("全部通过" if not fails else "失败 %d 项: %s" % (len(fails), fails)))
    sys.exit(1 if fails else 0)


asyncio.run(main())
