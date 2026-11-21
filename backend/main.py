"""白泽 · 多智能体控制台后端：REST 管理接口 + WebSocket 实时对话编排。"""
import asyncio
import hmac
import shutil
import os
import re
import socket
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import config  # 必须最先导入：它负责加载 .env 和 config.yaml
import providers
import manage
import store
import settings  # noqa: E402  loads UI-managed settings on top of the file/env defaults
import tools
import external
import files
import lessons
import memory
import skills
import usage
import backup
import attachments
from common import LAN_OFF_TEXT, _ADMIN_ONLY, _LOCAL_CLIENTS, _need, _s, can_admin, is_local, lan_allowed
from hub import _stop, _stop_and_wait, broadcast, clients, tasks
from files import conv_dirs
from cleaning import clean_agent, clean_conv, clean_provider, image_from_file, public_provider, set_chief
from lessons import LESSON_TAG
from skills import SKILL_READ
from external import ext_online
import orchestra
from orchestra import approvals, run_conversation, strip_agent_tags

HOST, PORT = config.HOST, config.PORT
DIST = os.path.join(config.ROOT, "frontend", "dist")

with open(os.path.join(config.ROOT, "VERSION"), encoding="utf-8") as _version_file:
    VERSION = _version_file.read().strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    orchestra.SHUTTING_DOWN["now"] = False
    try:
        yield
    finally:
        orchestra.SHUTTING_DOWN["now"] = True


app = FastAPI(title="Multi-Agents Control", version=VERSION, lifespan=lifespan)
# 各功能模块的接口（必须在最后挂载前端静态文件之前注册）
for _module in (files, attachments, usage, lessons, memory, skills, external, backup):
    app.include_router(_module.router)

# 上次退出时若有操作还停在「等待确认 / 执行中」，现在已经没人执行了：标成已取消，卡片不会永远卡住
ORPHANED_ACTIONS = store.cancel_orphaned_actions()


def _token_ok(value: Optional[str]) -> bool:
    return not config.TOKEN or hmac.compare_digest(unquote(value or "").encode(), config.TOKEN.encode())


# ---- 口令尝试次数限制：同一个地址 10 分钟内输错 10 次，锁 15 分钟。本机永远不锁，免得把自己关在外面 ----
FAIL_WINDOW, FAIL_LIMIT, BLOCK_SECONDS = 600, 10, 900
_failures: Dict[str, List[float]] = {}
_blocked: Dict[str, float] = {}


def _blocked_for(ip: str) -> int:
    """这个地址还要锁多少秒（0 = 没锁）。"""
    left = _blocked.get(ip, 0) - time.time()
    if left <= 0:
        _blocked.pop(ip, None)
        return 0
    return int(left) + 1


def _note_failure(ip: str) -> None:
    if ip in _LOCAL_CLIENTS:
        return
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < FAIL_WINDOW] + [now]
    _failures[ip] = recent
    if len(recent) >= FAIL_LIMIT:
        _blocked[ip] = now + BLOCK_SECONDS
        _failures.pop(ip, None)


def blocked_view() -> List[Dict[str, Any]]:
    out = []
    for ip in list(_blocked):
        left = _blocked_for(ip)
        if left:
            out.append({"ip": ip, "seconds": left})
    return out


# 安全响应头：页面只加载自己的脚本和样式，不允许被别的网站嵌入
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                               "font-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; "
                               "object-src 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    ip = request.client.host if request.client else ""
    # 外部智能体的连接口（/join/口令、/api/ext/口令/…）自带一个只属于它的随机口令，
    # 所以别的电脑上的智能体总能连进来，不需要为它打开整个控制台的局域网访问
    ext_path = path.startswith("/join/") or path.startswith("/api/ext/")
    if not lan_allowed() and not is_local(request) and not ext_path:
        return PlainTextResponse(LAN_OFF_TEXT, status_code=403)
    wait = _blocked_for(ip)
    if wait:
        return JSONResponse({"detail": "口令输错次数太多，请 %d 分钟后再试（可在运行本程序的电脑上「设置 → 访问与网络」里解除）" % (wait // 60 + 1)},
                            status_code=429, headers={"Retry-After": str(wait)})
    # 口令只认请求头：放在网址里会进浏览器历史、代理和访问日志
    if path.startswith("/api/") and not path.startswith("/api/ext/") and not _token_ok(request.headers.get("x-access-token")):
        _note_failure(ip)
        return JSONResponse({"detail": "需要访问口令"}, status_code=401)
    if path.startswith("/api/") and not path.startswith("/api/ext/") and request.method != "GET" and tools.remote_locked() and not is_local(request):
        return JSONResponse({"detail": tools.REMOTE_LOCKED_TEXT}, status_code=403)
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


@app.get("/api/security/blocked")
def security_blocked():
    return {"blocked": blocked_view(), "limit": FAIL_LIMIT, "window_minutes": FAIL_WINDOW // 60, "block_minutes": BLOCK_SECONDS // 60}


@app.post("/api/security/unblock")
def security_unblock(request: Request, d: Dict[str, Any] = Body(default={})):
    """解除锁定（只能在本机或输入过口令的设备上操作）。不带 ip 就全部解除。"""
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    ip = _s(d.get("ip"), 60)
    for table in (_blocked, _failures):
        if ip:
            table.pop(ip, None)
        else:
            table.clear()
    return {"blocked": blocked_view()}


def sync_config() -> None:
    """把 config.yaml 里声明的渠道和智能体写入数据库（固定 id，重启即覆盖），并清掉已从文件删除的。"""
    def key(item: Dict[str, Any], i: int) -> str:
        return "cfg-" + (re.sub(r"[^a-zA-Z0-9_-]", "", str(item.get("id") or "")) or str(i))

    wanted: Dict[str, set] = {"provider": set(), "agent": set()}
    for i, item in enumerate(config.PROVIDERS):
        pid = key(item, i)
        old = store.get_doc("provider", pid) or {}
        try:
            data = clean_provider({**item, "api_key": item.get("api_key") or ""}, old)
        except HTTPException:
            config.CONFIG_ERROR = "config.yaml 里的渠道「%s」使用了不支持的协议：%s" % (item.get("name") or pid, item.get("protocol"))
            continue
        data["managed"] = True
        store.set_doc("provider", pid, data)
        wanted["provider"].add(pid)
    for i, item in enumerate(config.AGENTS):
        aid = key(item, i)
        ref = item.get("provider")
        image = image_from_file(str(item["avatar_file"])) if item.get("avatar_file") else item.get("avatar_image")
        data = clean_agent({**item, "avatar_image": image, "provider_id": ("cfg-" + str(ref)) if ref else item.get("provider_id")}, "", store.get_doc("agent", aid) or {})
        data["managed"] = True
        store.set_doc("agent", aid, data)
        wanted["agent"].add(aid)
        if data["chief"]:
            set_chief(aid)
    for kind, ids in wanted.items():
        for doc in store.list_docs(kind):
            if doc.get("managed") and doc["id"] not in ids:
                store.delete_doc(kind, doc["id"])


sync_config()
orchestra.recover_interrupted()  # 上次服务停止时没跑完的会话：标记出来，界面上给「继续」


@app.post("/api/conversations/{cid}/interrupted/dismiss")
def dismiss_interrupted(cid: str):
    """不想继续被打断的那次回复：去掉提示。"""
    orchestra.clear_run(cid)
    return {"ok": True}


def _preview(cid: str) -> Dict[str, Any]:
    """会话列表里显示的最后一条消息摘要。"""
    last = store.list_messages(cid, 1)
    if not last:
        return {}
    m = last[0]
    if m.get("role") == "tool":
        text = tools.describe(m["action"])
    else:
        text = SKILL_READ.sub("", LESSON_TAG.sub("", manage.strip(strip_agent_tags(tools.strip_actions(m.get("content") or ""))))).strip() or m.get("error") or ""
    return {"who": m.get("agent_name") or "", "text": " ".join(re.sub(r"[*#`>]+", "", text).split())[:80], "at": m.get("created")}


# ------------------------------------------------------------------ REST
@app.get("/api/state")
def state(request: Request):
    convs = store.list_docs("conversation")
    for c in convs:
        c["last"] = _preview(c["id"])
    return {
        "providers": [public_provider(p) for p in store.list_docs("provider")],
        "agents": store.list_docs("agent"),
        "conversations": convs,
        "protocols": providers.PROTOCOLS,
        "presets": providers.PRESETS,
        "running": list(tasks),
        "skills": [{"id": k["id"], "name": k["name"], "description": k.get("description", "")} for k in store.list_docs("skill")],
        "mcp": [{"id": m["id"], "name": m["name"], "enabled": m.get("enabled"), "tools": len(m.get("tools") or []), "error": bool(m.get("error"))} for m in store.list_docs("mcp")],
        "interrupted": orchestra.interrupted_ids(),
        "ext_online": [a["id"] for a in store.list_docs("agent") if a.get("external") and (ext_online(a) or (a.get("ext_mode") == "cli" and a.get("ext_cmd")))],
        "memory_counts": memory.counts(),
        "env": {
            "local": {**tools.status(), "can_admin": can_admin(request)},
            "config_file": os.path.basename(config.CONFIG_PATH) if config.CONFIG_LOADED else "",
            "config_error": config.CONFIG_ERROR,
            "ollama_ctx": providers.OLLAMA_DEFAULT_CTX,
        },
    }


@app.post("/api/providers")
def create_provider(d: Dict[str, Any] = Body(...)):
    return public_provider(store.put_doc("provider", clean_provider(d)))


@app.put("/api/providers/{pid}")
def update_provider(pid: str, d: Dict[str, Any] = Body(...)):
    old = _need("provider", pid)
    return public_provider(store.put_doc("provider", clean_provider(d, old), pid))


@app.delete("/api/providers/{pid}")
def delete_provider(pid: str):
    store.delete_doc("provider", pid)
    return {"ok": True}


@app.post("/api/providers/{pid}/models")
async def provider_models(pid: str):
    p = _need("provider", pid)
    try:
        models = await providers.list_models(p)
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))
    p["models"] = models
    store.put_doc("provider", p, pid)
    return {"models": models}


@app.post("/api/providers/{pid}/test")
async def provider_test(pid: str, d: Dict[str, Any] = Body(default={})):
    p = _need("provider", pid)
    model = _s(d.get("model")) or p.get("default_model") or (p.get("models") or [""])[0]
    if not model:
        raise HTTPException(400, "请先填写默认模型，或点击“获取模型”")
    reply = ""

    async def run():
        nonlocal reply
        msgs = [{"role": "user", "content": "你好，请只回复两个字：收到"}]
        async for kind, text in providers.stream(p, model, "", msgs, {"max_tokens": 256}):
            if kind == "text":
                reply += text

    started = time.time()
    try:
        await asyncio.wait_for(run(), 60)
    except asyncio.TimeoutError:
        raise HTTPException(504, "测试超时（60 秒）")
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "model": model, "reply": reply.strip()[:200], "ms": int((time.time() - started) * 1000)}


# ------------------------------------------------------------------ 设置（界面里可改，不必动配置文件）
def settings_view(request: Request) -> Dict[str, Any]:
    local = config.LOCAL
    return {
        "local": {
            **tools.status(),
            "allow_outside_workspace": local["allow_outside_workspace"],
            "timeout": local["timeout"],
            "max_steps": local["max_steps"],
        },
        "token_set": bool(config.TOKEN),
        "lan_open": lan_allowed() and not config.LOOPBACK,
        "lan": bool(settings.value("lan", False)),
        "lan_bind_ok": not config.LOOPBACK,
        "lan_urls": ["http://%s:%d" % (ip, config.PORT) for ip in lan_ips()],
        "public_url": settings.value("public_url", ""),
        "in_docker": config.IN_DOCKER,
        "home": config.HOME,          # 你的数据放在哪（不在项目文件夹里）
        "data_dir": config.DATA_DIR,
        "can_admin": can_admin(request),
        "is_local": is_local(request),
        "grants": [{"id": a["id"], "name": a["name"]} for a in store.list_docs("agent") if a.get("auto_approve")],
        "files": settings.list_files(60),
        "team": settings.value("team", "ask"),
        "lessons": settings.value("lessons", True),
        "memory": settings.value("memory", True),
        "native_tools": settings.value("native_tools", True),
        "thrifty": settings.value("thrifty", True),
        "lessons_review": settings.value("lessons_review", False),
        "chief_id": next((a["id"] for a in store.list_docs("agent") if a.get("chief")), ""),
    }


@app.get("/api/settings")
def get_settings(request: Request):
    return settings_view(request)


@app.put("/api/settings")
async def put_settings(request: Request, d: Dict[str, Any] = Body(...)):
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    try:
        settings.update(d)
        if "chief_id" in d:  # the permanent lead agent
            for a in store.list_docs("agent"):
                want = a["id"] == d["chief_id"] and not a.get("conv_id")
                if bool(a.get("chief")) != want:
                    a["chief"] = want
                    store.put_doc("agent", a, a["id"])
    except settings.SettingsError as e:
        raise HTTPException(400, str(e))
    await broadcast({"type": "refresh"})
    return settings_view(request)


@app.post("/api/settings/open-workspace")
def open_workspace(request: Request):
    if config.IN_DOCKER:
        raise HTTPException(400, "程序运行在 Docker 容器里，没有文件管理器可以打开。工作区对应宿主机上挂载的 workspace 目录。")
    if not is_local(request):
        raise HTTPException(403, "只能在运行本程序的这台电脑上打开文件夹。工作区位置：%s" % config.LOCAL["workspace"])
    try:
        settings.open_workspace()
    except Exception as e:
        raise HTTPException(500, "打不开文件夹：%s" % e)
    return {"ok": True}


@app.post("/api/settings/open-data")
def open_data_folder(request: Request):
    """在文件管理器里打开你的数据目录（数据库、备份前另存的副本都在这里）。"""
    if config.IN_DOCKER or not is_local(request):
        raise HTTPException(403, "只能在运行本程序的这台电脑上打开。数据位置：%s" % config.HOME)
    try:
        settings.open_folder(config.HOME)
    except Exception as e:
        raise HTTPException(500, "打不开文件夹：%s" % e)
    return {"ok": True}


@app.post("/api/agents/{aid}/revoke")
async def revoke_agent(aid: str, request: Request):
    """撤销对某个智能体的永久授权。"""
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    agent = _need("agent", aid)
    agent["auto_approve"] = False
    store.put_doc("agent", agent, aid)
    await broadcast({"type": "refresh"})
    return settings_view(request)


def _guard_cmd(request: Request, d: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> None:
    """命令行模式会在这台电脑上执行命令：只有能改权限的设备才能设置或修改它。"""
    if d.get("ext_cmd") and d.get("ext_cmd") != (old or {}).get("ext_cmd") and not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)


@app.post("/api/agents")
def create_agent(request: Request, d: Dict[str, Any] = Body(...)):
    _guard_cmd(request, d)
    agent = store.put_doc("agent", clean_agent(d))
    if agent["chief"]:
        set_chief(agent["id"])
    return agent


@app.put("/api/agents/{aid}")
def update_agent(aid: str, request: Request, d: Dict[str, Any] = Body(...)):
    old = _need("agent", aid)
    _guard_cmd(request, d, old)
    agent = store.put_doc("agent", clean_agent(d, old.get("conv_id") or "", old), aid)
    if agent["chief"]:
        set_chief(aid)
    return agent


@app.post("/api/agents/{aid}/promote")
def promote_agent(aid: str):
    """把只属于某个会话的智能体加入全局。"""
    agent = _need("agent", aid)
    agent["conv_id"] = ""
    return store.put_doc("agent", agent, aid)


@app.delete("/api/agents/{aid}")
def delete_agent(aid: str):
    store.delete_doc("agent", aid)
    memory.forget_agent(aid)
    return {"ok": True}


@app.post("/api/conversations/{cid}/agents")
def create_agent_in_conv(cid: str, request: Request, d: Dict[str, Any] = Body(...)):
    _guard_cmd(request, d)
    """在会话里新建智能体并直接加入该会话；global 为真时同时成为全局智能体。"""
    conv = _need("conversation", cid)
    agent = store.put_doc("agent", clean_agent(d, "" if d.get("global") else cid))
    conv["agent_ids"] = conv["agent_ids"] + [agent["id"]]
    conv = store.put_doc("conversation", conv, cid)
    return {"agent": agent, "conversation": conv}


@app.post("/api/conversations")
def create_conv(d: Dict[str, Any] = Body(...)):
    return store.put_doc("conversation", clean_conv(d))


@app.put("/api/conversations/{cid}")
def update_conv(cid: str, d: Dict[str, Any] = Body(...)):
    _need("conversation", cid)
    return store.put_doc("conversation", clean_conv(d, cid), cid)


@app.delete("/api/conversations/{cid}")
async def delete_conv(cid: str):
    await _stop_and_wait(cid)
    store.clear_messages(cid)
    for a in store.list_docs("agent"):  # 只属于这个会话的智能体随会话一起删除（连同它的记忆）
        if a.get("conv_id") == cid:
            store.delete_doc("agent", a["id"])
            memory.forget_agent(a["id"])
    store.delete_doc("conversation", cid)
    return {"ok": True}


@app.get("/api/conversations/{cid}/messages")
def conv_messages(cid: str):
    return {"messages": store.list_messages(cid)}


@app.delete("/api/conversations/{cid}/messages")
async def conv_clear(cid: str):
    await _stop_and_wait(cid)
    store.clear_messages(cid)
    return {"ok": True}


@app.delete("/api/messages/{mid}")
def message_delete(mid: str):
    store.delete_message(mid)
    return {"ok": True}


# ------------------------------------------------------------------ 编排
async def handle_send(sock: WebSocket, d: Dict[str, Any]) -> None:
    cid = _s(d.get("conv_id"), 40)
    conv = store.get_doc("conversation", cid)
    if not conv:
        return await sock.send_json({"type": "error", "text": "会话不存在"})
    if cid in tasks:
        return await sock.send_json({"type": "error", "text": "智能体还在发言，请稍候或先停止"})
    targets = [i for i in (d.get("targets") or []) if i in conv["agent_ids"]]
    if not conv["agent_ids"]:
        return await sock.send_json({"type": "error", "text": "这个会话还没有智能体，请先在会话设置里添加"})
    content = str(d.get("content") or "").strip()[:100000]
    files_in = attachments.clean(conv, d.get("attachments"))  # 只认本会话 attachments/ 下确实存在的文件
    if content or files_in:
        msg = {"id": store.new_id(), "conv_id": cid, "role": "user", "content": content, "created": time.time()}
        if files_in:
            msg["attachments"] = files_in
        store.save_message(msg)
        await broadcast({"type": "message", "message": msg})
        if conv["title"] == "新会话":
            conv["title"] = (content or files_in[0]["name"]).replace("\n", " ")[:24]
            conv = store.put_doc("conversation", conv, cid)
            await broadcast({"type": "conversation", "conversation": conv})
    tasks[cid] = asyncio.ensure_future(run_conversation(cid, targets))
    await broadcast({"type": "running", "conv_id": cid, "running": True})


async def handle_retry(sock: WebSocket, d: Dict[str, Any]) -> None:
    """重新生成：删掉这条回复及其之后的所有消息，让同一个智能体重答（领头模式走领头流程）。"""
    cid = _s(d.get("conv_id"), 40)
    conv = store.get_doc("conversation", cid)
    if not conv:
        return await sock.send_json({"type": "error", "text": "会话不存在"})
    if cid in tasks:
        return await sock.send_json({"type": "error", "text": "智能体还在发言，请稍候或先停止"})
    mid = _s(d.get("message_id"), 40)
    msgs = store.list_messages(cid)
    at = next((i for i, m in enumerate(msgs) if m["id"] == mid), -1)
    if at < 0 or msgs[at].get("role") != "agent":
        return await sock.send_json({"type": "error", "text": "只能从智能体的回复重新生成"})
    agent_id = msgs[at].get("agent_id")
    if conv.get("mode") != "lead" and agent_id not in conv["agent_ids"]:
        return await sock.send_json({"type": "error", "text": "这个智能体已不在会话里"})
    removed = [m["id"] for m in msgs[at:]]
    for m in msgs[at:]:
        store.delete_message(m["id"])
    tasks[cid] = asyncio.ensure_future(run_conversation(cid, [] if conv.get("mode") == "lead" else [agent_id]))
    await broadcast({"type": "removed", "conv_id": cid, "ids": removed})
    await broadcast({"type": "running", "conv_id": cid, "running": True})


@app.websocket("/ws")
async def ws_endpoint(sock: WebSocket):
    if not lan_allowed() and not (sock.client and sock.client.host in _LOCAL_CLIENTS):
        await sock.close(code=4403)
        return
    await sock.accept()
    try:
        while True:
            d = await sock.receive_json()
            if not isinstance(d, dict):
                continue
            kind = d.get("type")
            if kind == "auth":
                ip = sock.client.host if sock.client else ""
                if _blocked_for(ip):
                    await sock.send_json({"type": "unauthorized", "text": "口令输错次数太多，请稍后再试"})
                elif _token_ok(d.get("token")):
                    clients.add(sock)
                    await sock.send_json({"type": "ready", "running": list(tasks)})
                else:
                    _note_failure(ip)
                    await sock.send_json({"type": "unauthorized"})
            elif sock not in clients:
                continue
            elif kind in ("send", "permit", "stop", "retry", "stop_member", "retry_member") and tools.remote_locked() and not (sock.client and sock.client.host in _LOCAL_CLIENTS):
                await sock.send_json({"type": "error", "text": tools.REMOTE_LOCKED_TEXT})
            elif kind == "send":
                await handle_send(sock, d)
            elif kind == "retry":
                await handle_retry(sock, d)
            elif kind == "stop":
                _stop(_s(d.get("conv_id"), 40))
            elif kind == "stop_member":  # 只停止并行分派里的某一位成员
                orchestra.stop_member(_s(d.get("conv_id"), 40), _s(d.get("agent_id"), 40))
            elif kind == "retry_member":  # 重做某位成员的那项任务（会话空闲时）
                cid = _s(d.get("conv_id"), 40)
                if cid in tasks:
                    await sock.send_json({"type": "error", "text": "智能体还在发言，请等这一轮结束再重做"})
                elif store.get_doc("conversation", cid):
                    tasks[cid] = asyncio.ensure_future(orchestra.retry_member(cid, _s(d.get("agent_id"), 40), _s(d.get("batch"), 40)))
                    await broadcast({"type": "running", "conv_id": cid, "running": True})
            elif kind == "permit":
                fut = approvals.get(_s(d.get("id"), 40))
                if fut and not fut.done():
                    fut.set_result(d.get("decision") if d.get("decision") in ("once", "five", "forever", "always") else "deny")
    except Exception:
        pass
    finally:
        clients.discard(sock)


# ------------------------------------------------------------------ 前端静态资源
# ------------------------------------------------------------------ 搜索、记录管理、模型预拉取
@app.get("/api/search")
def search(q: str = ""):
    """按聊天内容搜索：返回命中的会话和一小段上下文。"""
    q = q.strip()
    if not q:
        return {"hits": []}
    hits: Dict[str, Dict[str, Any]] = {}
    low = q.lower()
    for m in store.search_messages(q):
        text = m.get("content") or ""
        at = text.lower().find(low)
        if at < 0 or m["conv_id"] in hits:
            continue
        start = max(0, at - 18)
        snippet = ("…" if start else "") + " ".join(strip_agent_tags(tools.strip_actions(text[start:at + len(q) + 40])).split())
        hits[m["conv_id"]] = {"conv_id": m["conv_id"], "who": m.get("agent_name") or ("我" if m.get("role") == "user" else ""), "text": snippet, "at": m.get("created")}
    return {"hits": list(hits.values())}


@app.get("/api/records")
def records():
    """设置页的「聊天记录」：每个会话占了多少，数据库总共多大。"""
    stats = store.message_stats()
    rows = []
    for c in store.list_docs("conversation"):
        n, size, last = stats.get(c["id"], (0, 0, None))
        root, _ = conv_dirs(c)
        rows.append({"id": c["id"], "title": c["title"], "messages": n, "bytes": size, "last": last or c["created"],
                     "folder": root if os.path.isdir(root) else ""})
    rows.sort(key=lambda r: -r["last"])
    return {"conversations": rows, "db_path": store.DB_PATH, "db_bytes": store.db_size()}


@app.post("/api/records/delete")
async def delete_records(d: Dict[str, Any] = Body(...)):
    """删除选中的会话（连同它们的消息和只属于它们的智能体），可选同时删除会话文件夹，然后压缩数据库。"""
    removed = 0
    for cid in [str(i) for i in (d.get("ids") or [])][:500]:
        conv = store.get_doc("conversation", cid)
        if not conv:
            continue
        await _stop_and_wait(cid)
        if d.get("files"):
            root, _ = conv_dirs(conv)
            if os.path.isdir(root) and tools.inside(root, [config.LOCAL["workspace"]]) and os.path.realpath(root) != os.path.realpath(config.LOCAL["workspace"]):
                shutil.rmtree(root, ignore_errors=True)
        store.clear_messages(cid)
        for a in store.list_docs("agent"):
            if a.get("conv_id") == cid:
                store.delete_doc("agent", a["id"])
                memory.forget_agent(a["id"])
        store.delete_doc("conversation", cid)
        removed += 1
    store.vacuum()
    await broadcast({"type": "refresh"})
    return {"removed": removed, "db_bytes": store.db_size()}


@app.post("/api/providers/preview-models")
async def preview_models(d: Dict[str, Any] = Body(...)):
    """添加渠道时就能拉取模型列表：用表单里还没保存的配置直接去问。"""
    old = store.get_doc("provider", _s(d.get("id"), 40)) or {}
    candidate = clean_provider(d, old)  # 编辑时没重新填密钥，就沿用已保存的
    try:
        return {"models": await providers.list_models(candidate)}
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))


MANAGER_PROMPT = "你是工具管家，负责帮用户添加、查找和整理技能与 MCP 服务。做事干练，回答简短；用户给你网址时，直接动手添加。"


@app.post("/api/manager")
def manager_conversation():
    """找到（或建好）管家智能体和它的会话，前端随后把用户的话发进去。"""
    agents = store.list_docs("agent")
    boss = next((a for a in agents if a.get("manager") and not a.get("conv_id")), None)
    if not boss:
        base = next((a for a in agents if a.get("chief") and a.get("provider_id")), None) or next((a for a in agents if a.get("provider_id")), None)
        provider = store.get_doc("provider", base["provider_id"]) if base else next(iter(store.list_docs("provider")), None)
        if not provider:
            raise HTTPException(400, "还没有模型渠道。先到「渠道」页添加一个，管家才能工作。")
        boss = store.put_doc("agent", clean_agent({
            "name": "工具管家", "avatar": "ph:Wrench", "color": "amber", "manager": True, "no_tools": False,
            "description": "添加、查找、整理技能和 MCP 服务", "system_prompt": MANAGER_PROMPT,
            "provider_id": provider["id"], "model": (base or {}).get("model") or provider.get("default_model", ""),
        }))
    if boss.get("no_tools"):  # 早期版本建的管家被禁止了本地操作，装不了 CLI
        boss["no_tools"] = False
        boss = store.put_doc("agent", boss, boss["id"])
    conv = next((c for c in store.list_docs("conversation") if c.get("agent_ids") == [boss["id"]] and c.get("mode") != "lead"), None)
    if not conv:
        conv = store.put_doc("conversation", clean_conv({"title": "技能与 MCP 管理", "agent_ids": [boss["id"]]}))
    return {"conversation": conv, "agent": boss}


# ------------------------------------------------------------------ 局域网
def lan_ips() -> List[str]:
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    main_ip = _lan_ip()  # 默认路由所在的网卡，通常就是手机连的那个 Wi‑Fi
    rest = sorted(ip for ip in ips if ip != main_ip and not ip.startswith(("127.", "169.254.")))
    return ([main_ip] if not main_ip.startswith("127.") else []) + rest


if os.path.isdir(DIST):
    class WebFiles(StaticFiles):
        """index.html must always be revalidated so a rebuilt frontend shows up at once; hashed assets may be cached."""

        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            if resp.headers.get("content-type", "").startswith("text/html"):
                resp.headers["Cache-Control"] = "no-cache"
            return resp

    app.mount("/", WebFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/")
    def no_frontend():
        return PlainTextResponse("前端尚未构建：请在 frontend 目录执行 npm install && npm run build", status_code=503)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    import uvicorn

    print("\n  白泽 · 多智能体控制台已启动")
    print("  电脑访问: http://localhost:%d" % PORT)
    if HOST == "0.0.0.0":
        print("  手机访问: http://%s:%d  （需与电脑在同一局域网）" % (_lan_ip(), PORT))
    print("  访问口令: %s" % ("已启用" if config.TOKEN else "未设置（可在 config.yaml 的 server.token 或环境变量 MAC_TOKEN 设置）"))
    print("  你的数据: %s（不在项目文件夹里，发布或复制项目不会带上它）" % config.HOME)
    for line in config.MIGRATED:
        print("  已从旧位置搬过来 · " + line)
    print("  配置文件: %s" % (config.CONFIG_PATH if config.CONFIG_LOADED else "未使用（把 config.example.yaml 复制为 %s 即可）" % os.path.join(config.HOME, "config.yaml")))
    if config.CONFIG_ERROR:
        print("  !! " + config.CONFIG_ERROR)
    if ORPHANED_ACTIONS:
        print("  已清理: %d 条上次退出时未完成/待确认的操作，标记为已取消" % ORPHANED_ACTIONS)
    local = tools.status()
    print("  本地操作: %s" % ("已开启，工作目录 %s" % local["workspace"] if local["usable"] else local["reason"]))
    if config.IN_DOCKER:
        print("  运行环境: Docker 容器（本地操作只作用于容器内和挂载的目录）")
    print()
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
