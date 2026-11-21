"""实时推送与运行中的任务：所有打开的页面（WebSocket）和每个会话正在跑的编排任务。"""
import asyncio
from typing import Any, Dict

from fastapi import WebSocket



clients: "set[WebSocket]" = set()
tasks: Dict[str, "asyncio.Task[None]"] = {}
member_tasks: Dict[str, Dict[str, "asyncio.Task[None]"]] = {}  # 并行分派时每位成员各自的任务：可以单独停止某一个


async def broadcast(event: Dict[str, Any]) -> None:
    for sock in list(clients):
        try:
            await sock.send_json(event)
        except Exception:
            clients.discard(sock)


def _stop(cid: str) -> None:
    task = tasks.get(cid)
    if task:
        task.cancel()


async def _stop_and_wait(cid: str) -> None:
    """停止并等它收尾：被中断的回复会在收尾时落库，必须等它写完再清空/删除。"""
    task = tasks.get(cid)
    if task:
        task.cancel()
        await asyncio.wait([task], timeout=10)
