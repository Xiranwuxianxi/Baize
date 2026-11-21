"""通用小工具：输入清洗、按 id 取对象、判断请求来自本机 / 局域网、权限检查、token 估算。"""
from typing import Any, Dict

from fastapi import HTTPException, Request

import config
import settings
import store
import tools


# ------------------------------------------------------------------ 数据清洗
def _s(v: Any, limit: int = 200) -> str:
    return str(v or "").strip()[:limit]


def _num(v: Any, lo: float, hi: float, as_int: bool = False):
    if v is None or v == "":
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    n = max(lo, min(hi, n))
    return int(n) if as_int else n


def _need(kind: str, doc_id: str) -> Dict[str, Any]:
    doc = store.get_doc(kind, doc_id)
    if not doc:
        raise HTTPException(404, "对象不存在")
    return doc


_LOCAL_CLIENTS = ("127.0.0.1", "::1", "localhost")
_ADMIN_ONLY = "为了安全，权限类设置只能在运行本程序的这台电脑上修改。也可以先在这台电脑上设置访问口令，之后任何输入过口令的设备都能修改。"


LAN_OFF_TEXT = "局域网访问没有开启。请在运行本程序的电脑上打开控制台，到「设置 → 访问与网络」里开启局域网访问。"


def lan_allowed() -> bool:
    """局域网访问默认关闭；Docker 里分辨不出本机，始终放行（由访问口令保护）。"""
    return config.IN_DOCKER or bool(settings.value("lan", False))


def is_local(request: Request) -> bool:
    return bool(request.client) and request.client.host in _LOCAL_CLIENTS


def can_admin(request: Request) -> bool:
    """谁可以改权限：本机上的浏览器；或者已经设了访问口令（这时每个请求都验证过口令）。

    不这样限制的话，同一局域网里的任何人都能远程打开「在这台机器上执行命令」的开关。
    """
    return bool(config.TOKEN) or is_local(request)


def _tokens(text: str) -> int:
    """粗略估算 token 数：中日韩字符按 1 个算，其余按每 3 个字符 1 个算。宁可高估。"""
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    return cjk + (len(text) - cjk) // 3 + 4


def can_operate(agent: Dict[str, Any]) -> bool:
    return tools.usable() and not agent.get("no_tools") and not agent.get("external")
