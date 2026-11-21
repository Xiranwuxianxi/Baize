"""最小的 MCP 客户端：支持 stdio（启动本地进程）和 HTTP（Streamable HTTP）两种接入方式。

只实现会用到的部分：initialize、tools/list、tools/call。
全部是同步代码，由调用方放到线程里执行；这样不依赖事件循环类型，在 Windows 上也能稳定启动子进程。
"""
import json
import os
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional

import httpx

PROTOCOL = "2025-03-26"
CLIENT = {"name": "baize", "version": "0.7"}
TIMEOUT = 60


class MCPError(Exception):
    pass


class _Stdio:
    def __init__(self, cfg: Dict[str, Any]):
        cmd = str(cfg.get("command") or "").strip()
        if not cmd:
            raise MCPError("没有填写启动命令")
        exe = shutil.which(cmd) or cmd  # Windows 上 npx、uvx 实际是 .cmd 文件，需要先找到完整路径
        env = {**os.environ, **{str(k): str(v) for k, v in (cfg.get("env") or {}).items()}}
        try:
            self.proc = subprocess.Popen(
                [exe, *[str(a) for a in cfg.get("args") or []]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, cwd=cfg.get("cwd") or None, bufsize=0,
            )
        except OSError as e:
            raise MCPError("启动失败：%s（命令：%s）" % (e, cmd))
        self.lock = threading.Lock()
        self.next_id = 0
        self.pending: Dict[int, Dict[str, Any]] = {}
        self.cond = threading.Condition()
        self.err: List[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:  # 收集 stderr，出错时给用户看
        for line in self.proc.stderr:
            self.err = (self.err + [line.decode("utf-8", "replace").rstrip()])[-20:]

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg):
                with self.cond:
                    self.pending[msg["id"]] = msg
                    self.cond.notify_all()
        with self.cond:
            self.cond.notify_all()

    def _send(self, obj: Dict[str, Any]) -> None:
        try:
            self.proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            raise MCPError("进程已退出。" + " ".join(self.err[-3:]))

    def request(self, method: str, params: Dict[str, Any]) -> Any:
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        with self.cond:
            ok = self.cond.wait_for(lambda: rid in self.pending or self.proc.poll() is not None, TIMEOUT)
            msg = self.pending.pop(rid, None)
        if msg is None:
            raise MCPError(("进程已退出。" + " ".join(self.err[-3:])) if self.proc.poll() is not None or ok else "等待响应超时")
        if "error" in msg:
            raise MCPError(str((msg["error"] or {}).get("message") or msg["error"]))
        return msg.get("result")

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass


class _Http:
    def __init__(self, cfg: Dict[str, Any]):
        self.url = str(cfg.get("url") or "").strip()
        if not self.url.startswith(("http://", "https://")):
            raise MCPError("地址必须以 http:// 或 https:// 开头")
        self.headers = {str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}
        self.session = ""
        self.next_id = 0
        self.client = httpx.Client(timeout=TIMEOUT)

    def _post(self, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session:
            h["Mcp-Session-Id"] = self.session
        try:
            r = self.client.post(self.url, json=body, headers=h)
        except httpx.HTTPError as e:
            raise MCPError("连不上 %s：%s" % (self.url, e))
        if r.status_code >= 400:
            raise MCPError("HTTP %s：%s" % (r.status_code, r.text[:300]))
        self.session = r.headers.get("mcp-session-id", self.session)
        if "id" not in body or not r.content:
            return None
        if "text/event-stream" in r.headers.get("content-type", ""):
            for line in r.text.splitlines():  # 取第一条对应本次请求的响应
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and msg.get("id") == body["id"]:
                        return msg
            raise MCPError("服务器没有返回响应")
        return r.json()

    def request(self, method: str, params: Dict[str, Any]) -> Any:
        self.next_id += 1
        msg = self._post({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params}) or {}
        if "error" in msg:
            raise MCPError(str((msg["error"] or {}).get("message") or msg["error"]))
        return msg.get("result")

    def notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def alive(self) -> bool:
        return True

    def close(self) -> None:
        self.client.close()


_conns: Dict[str, Any] = {}
_lock = threading.Lock()


def _connect(cfg: Dict[str, Any]):
    conn = _Http(cfg) if cfg.get("transport") == "http" else _Stdio(cfg)
    try:
        conn.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT})
        conn.notify("notifications/initialized")
    except Exception:
        conn.close()
        raise
    return conn


def _get(cfg: Dict[str, Any]):
    key = cfg["id"]
    with _lock:
        conn = _conns.get(key)
        if conn and conn.alive() and conn.cfg_sig == _sig(cfg):
            return conn
        if conn:
            conn.close()
        conn = _connect(cfg)
        conn.cfg_sig = _sig(cfg)
        _conns[key] = conn
        return conn


def _sig(cfg: Dict[str, Any]) -> str:
    return json.dumps({k: cfg.get(k) for k in ("transport", "command", "args", "env", "url", "headers", "cwd")}, sort_keys=True)


def drop(server_id: str) -> None:
    with _lock:
        conn = _conns.pop(server_id, None)
    if conn:
        conn.close()


def list_tools(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        result = _get(cfg).request("tools/list", {}) or {}
    except MCPError:
        drop(cfg["id"])
        raise
    out = []
    for t in result.get("tools") or []:
        schema = t.get("inputSchema") or {}
        props = schema.get("properties") or {}
        need = set(schema.get("required") or [])
        out.append({
            "name": t.get("name", ""),
            "description": (t.get("description") or "").strip(),
            "params": [p + ("*" if p in need else "") for p in props],
        })
    return out


def call_tool(cfg: Dict[str, Any], tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        result = _get(cfg).request("tools/call", {"name": tool, "arguments": args}) or {}
    except MCPError as e:
        drop(cfg["id"])
        return {"ok": False, "output": str(e)}
    parts = []
    for c in result.get("content") or []:
        if c.get("type") == "text":
            parts.append(c.get("text") or "")
        else:
            parts.append("[%s 类型的内容，未显示]" % c.get("type"))
    text = "\n".join(parts).strip() or "（没有输出）"
    if len(text) > 8000:
        text = text[:8000] + "\n…（输出过长，已截断）"
    return {"ok": not result.get("isError"), "output": text}
