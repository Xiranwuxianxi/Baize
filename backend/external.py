"""外部智能体：命令行直接调用，或通过连接指令轮询领取任务、提交回复。"""
import asyncio
import codecs
import hmac
import json
import os
import re
import signal
import subprocess
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

import providers
import settings
import store
import tools

from common import _tokens
from hub import broadcast
from files import conv_dirs
from usage import record_usage
from context import build_context

router = APIRouter()

# ------------------------------------------------------------------ 外部智能体
# Claude Code、OpenClaw、Hermes 这类自带工具的智能体，通过一条指令连进来：它们轮询领取任务、提交回复。
externals: Dict[str, Dict[str, Any]] = {}  # 连接口令 -> {"queue", "waiting", "seen"}
EXT_ONLINE_SECONDS = 75
EXT_REPLY_TIMEOUT = 900  # 默认时限（秒）；每个外部智能体可以在设置里单独调


def ext_timeout(agent: Dict[str, Any]) -> int:
    """这个外部智能体一轮最多等多久（秒）。"""
    return int(agent.get("ext_timeout") or EXT_REPLY_TIMEOUT // 60) * 60


def _ext(token: str) -> Dict[str, Any]:
    return externals.setdefault(token, {"queue": asyncio.Queue(), "waiting": {}, "seen": 0.0})


def ext_online(agent: Dict[str, Any]) -> bool:
    slot = externals.get(agent.get("ext_token") or "")
    return bool(slot) and time.time() - slot["seen"] < EXT_ONLINE_SECONDS


def _ext_agent(token: str) -> Dict[str, Any]:
    agent = next((a for a in store.list_docs("agent") if a.get("external") and a.get("ext_token")
                  and hmac.compare_digest(a["ext_token"], token or "")), None)
    if not agent:
        raise HTTPException(404, "连接口令无效，这个外部智能体可能已被删除")
    return agent


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _windows_descendants(pid: int) -> List[int]:
    """Find descendants without relying on taskkill's WMI permissions."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        fn = getattr(kernel, name)
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        fn.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    children: Dict[int, List[int]] = {}
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            children.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(snapshot)

    descendants = [pid]
    seen = {pid}
    for parent in descendants:
        for child in children.get(parent, []):
            if child not in seen:
                seen.add(child)
                descendants.append(child)
    return descendants[:0:-1]  # Children must stop before their parents.


def _kill_tree(proc: "subprocess.Popen[bytes]") -> None:
    """连同它启动的子进程一起结束（只杀 shell 的话，真正干活的程序还会在后台跑）。"""
    try:
        if os.name == "nt":
            try:
                result = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                result = None
            if result is None or result.returncode != 0:
                try:
                    for pid in _windows_descendants(proc.pid):
                        try:
                            os.kill(pid, signal.SIGTERM)
                        except OSError as e:
                            if e.winerror != 87:  # Process already exited.
                                raise
                finally:
                    proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()
    proc.wait()


async def run_cli_agent(cmd: str, prompt: str, cwd: str, timeout: int,
                        on_text: Optional[Callable[[str], Awaitable[None]]] = None) -> str:
    """命令行模式：在会话文件夹里调用一次外部智能体，题目从标准输入给它，标准输出就是回复。

    输出边产生边交给 on_text（界面上实时看到它在写什么），不用等它全部做完。
    超时、或用户点了停止时，连同子进程一起结束。
    """
    prompt_file = ""
    if "{prompt_file}" in cmd:  # 有的命令行工具只认文件参数
        prompt_file = os.path.join(cwd, ".mac-prompt.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(prompt)
        cmd = cmd.replace("{prompt_file}", '"%s"' % prompt_file)
    env = {**tools.run_env(), "NO_COLOR": "1"}
    group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    loop = asyncio.get_running_loop()
    chunks: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
    err: List[bytes] = []
    proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, **group)

    def feed() -> None:  # 题目写进标准输入（放在线程里，内容很长时不会卡住）
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass

    def pump() -> None:  # 一有输出就交出来
        while True:
            data = proc.stdout.read1(4096)
            if not data:
                break
            loop.call_soon_threadsafe(chunks.put_nowait, data)
        loop.call_soon_threadsafe(chunks.put_nowait, None)

    def drain_err() -> None:
        err.append(proc.stderr.read())

    workers = [threading.Thread(target=fn, daemon=True) for fn in (feed, pump, drain_err)]
    for worker in workers:
        worker.start()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    out = ""
    deadline = time.time() + timeout
    try:
        while True:
            left = deadline - time.time()
            if left <= 0:
                raise providers.ProviderError("外部智能体超过 %d 分钟没有完成，已终止（可以在它的设置里调长时限）" % max(1, timeout // 60))
            try:
                data = await asyncio.wait_for(chunks.get(), min(left, 1.0))
            except asyncio.TimeoutError:
                continue
            if data is None:
                break
            text = _ANSI.sub("", decoder.decode(data))
            if text:
                out += text
                if on_text:
                    await on_text(text)
        out += decoder.decode(b"", final=True)
        code = await asyncio.to_thread(proc.wait)
    except BaseException:  # 超时、用户停止、出错：都把它结束掉
        await asyncio.to_thread(_kill_tree, proc)
        raise
    finally:
        # Reap the pipe readers before asyncio.run() can close their event loop.
        for worker in workers:
            await asyncio.to_thread(worker.join)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()
        if prompt_file and os.path.exists(prompt_file):
            os.remove(prompt_file)
    if code != 0:  # 失败时有的工具把报错打在标准输出里，不能当成回复
        stderr = tools._decode(b"".join(err)).strip()
        raise providers.ProviderError("「%s」执行失败（退出码 %s）：%s" % (cmd.split()[0], code, (stderr or out.strip())[-600:] or "没有输出"))
    return _ANSI.sub("", out).strip()


async def ask_external(conv: Dict[str, Any], agent: Dict[str, Any], msg: Dict[str, Any],
                       history: Optional[List[Dict[str, Any]]], note: str, ask: str) -> None:
    """把这一轮交给外部智能体：命令行模式直接调用一次；连接模式放进它的任务队列，等它提交回复。"""
    cli = agent.get("ext_mode") == "cli" and agent.get("ext_cmd")
    if not cli and not ext_online(agent):
        raise providers.ProviderError("外部智能体「%s」还没有连接。到「智能体」页复制它的连接指令，发给它即可。" % agent["name"])
    if history is None:
        history = store.list_messages(conv["id"], conv.get("context_limit") or 40)
    system, msgs = build_context(conv, agent, history, note, ask)
    lines = ["# 你的身份与规则", system, "", "# 对话记录（从旧到新）"]
    for m in msgs[-12:]:
        lines.append(("【你之前的回复】\n" if m["role"] == "assistant" else "") + m["content"])
        lines.append("")
    lines.append("# 现在轮到你回复。只提交你要在会话里说的话，不要附带过程说明。")
    prompt_tokens = _tokens("\n".join(lines))
    try:
        await _ask_external(conv, agent, msg, lines, cli)
    finally:  # 外部智能体自己调模型，拿不到真实用量：按发给它的内容和它的回复估算
        out = _tokens(msg["content"]) if msg["content"] else 0
        msg.update(tokens_in=prompt_tokens, tokens_out=out, tokens_est=True)
        record_usage(agent, msg.get("model", ""), conv["id"], {"in": prompt_tokens, "out": out, "est": True})


async def _ask_external(conv: Dict[str, Any], agent: Dict[str, Any], msg: Dict[str, Any], lines: List[str], cli: Any) -> None:
    if cli:
        root, _ = conv_dirs(store.get_doc("conversation", conv["id"]) or conv, create=True)

        async def live(text: str) -> None:  # 它写一点，界面上就出现一点
            msg["content"] += text
            await broadcast({"type": "delta", "conv_id": conv["id"], "id": msg["id"], "kind": "text", "text": text})

        msg["content"] = await run_cli_agent(agent["ext_cmd"], "\n".join(lines), root, ext_timeout(agent), live)
        if not msg["content"]:
            msg["error"] = "外部智能体没有输出任何内容"
        return
    slot = _ext(agent["ext_token"])
    task_id = store.new_id()
    fut: "asyncio.Future[str]" = asyncio.get_event_loop().create_future()
    slot["waiting"][task_id] = fut
    await slot["queue"].put({"task_id": task_id, "prompt": "\n".join(lines)})
    try:
        reply = await asyncio.wait_for(fut, ext_timeout(agent))
    except asyncio.TimeoutError:
        raise providers.ProviderError("外部智能体「%s」在 %d 分钟内没有回复，可能已经断开" % (agent["name"], ext_timeout(agent) // 60))
    finally:
        slot["waiting"].pop(task_id, None)
    msg["content"] = reply.strip()
    await broadcast({"type": "delta", "conv_id": conv["id"], "id": msg["id"], "kind": "text", "text": msg["content"]})
    if not msg["content"]:
        msg["error"] = "外部智能体提交了空回复"


_JOIN_TEXT = """你被邀请以「{name}」的身份加入一个多智能体协作会话。{desc}

请一直重复下面两步，直到用户让你停止。只需要能发 HTTP 请求（例如 curl）。

第一步：领取任务（最长会等 25 秒才返回）
  curl -s "{base}/api/ext/{token}/next"
返回 JSON。task_id 为 null 表示暂时没有任务，立刻再执行第一步；否则 prompt 字段就是轮到你回复的内容。

第二步：完成 prompt 里的任务，然后把你的回复作为请求正文提交（纯文本，UTF-8）
  curl -s -X POST "{base}/api/ext/{token}/reply/<task_id>" -H "Content-Type: text/plain; charset=utf-8" --data-binary @回复文件
内容较短时也可以直接用 -d "回复内容"。提交后回到第一步。

注意：
- 提交的内容会原样显示在会话里，只写你要说的话。
- 你可以使用自己的工具完成任务，但不要改动与任务无关的东西。
- 连续 {idle} 秒没有执行第一步会被视为离线，所以空闲时也要继续轮询。
现在就从第一步开始。
"""


@router.get("/join/{token}")
def join(token: str, request: Request):
    agent = _ext_agent(token)
    base = str(request.base_url).rstrip("/")
    pub = settings.value("public_url", "")
    if pub and urlparse(pub).hostname == request.url.hostname:
        base = pub  # 经反向代理 / 穿透进来时，后面的请求也要走同一个外网地址（含 https）
    desc = ("你的职责：" + agent["description"]) if agent.get("description") else ""
    return PlainTextResponse(_JOIN_TEXT.format(name=agent["name"], desc=desc, base=base, token=token, idle=EXT_ONLINE_SECONDS))


@router.get("/api/ext/{token}/next")
async def ext_next(token: str, wait: int = 25):
    _ext_agent(token)
    slot = _ext(token)
    was_online = time.time() - slot["seen"] < EXT_ONLINE_SECONDS
    slot["seen"] = time.time()
    if not was_online:
        await broadcast({"type": "refresh"})  # 界面上把它标成已连接
    try:
        task = await asyncio.wait_for(slot["queue"].get(), max(1, min(50, wait)))
    except asyncio.TimeoutError:
        task = {"task_id": None}
    slot["seen"] = time.time()
    return task


@router.post("/api/ext/{token}/reply/{task_id}")
async def ext_reply(token: str, task_id: str, request: Request):
    _ext_agent(token)
    slot = _ext(token)
    slot["seen"] = time.time()
    fut = slot["waiting"].get(task_id)
    if not fut or fut.done():
        raise HTTPException(404, "这个任务不存在或已经结束（可能超时或被用户停止）。请回到第一步领取新任务。")
    raw = await request.body()
    text = raw.decode("utf-8", "replace")
    if "json" in (request.headers.get("content-type") or ""):
        try:
            data = json.loads(text)
            text = str(data.get("content") or data.get("reply") or data.get("text") or "") if isinstance(data, dict) else text
        except ValueError:
            pass
    fut.set_result(text[:200000])
    return {"ok": True}
