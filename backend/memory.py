"""每个智能体自己的记忆：只属于它、跨会话保留的长期知识（关于用户的偏好和背景、项目的关键事实、
定下的决定、它摸索出的有效做法）。和共享经验库的区别：经验是全队都要遵守的规则，记忆是它个人的积累。

省 token 的做法和经验库一样：
- 写入靠回复里的 <remember>…</remember> 标签，不额外调用模型；
- 置顶的和数量很少时全部常驻在系统提示里（每轮不变，便于接口缓存）；其余只在和当前问题相关时附在本次消息里。
外部智能体（Claude Code 等）有自己的记忆系统，这里不管它们。
"""
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException

import settings
import store
from common import _need, _s, _tokens
from lessons import _HOLLOW, _similar, lesson_quality

router = APIRouter()

MEMORY_TAG = re.compile(r"<remember>(.*?)</remember>", re.S)
MAX_MEMORY_CHARS = 300
MAX_PER_REPLY = 3
MEMORY_ALWAYS = 250      # 一个智能体的记忆总量不超过这么多 token 时全部常驻
MAX_RELEVANT = 5         # 超过后，每次最多附上几条相关记忆
MEMORY_RULE = (
    "【你的记忆】只属于你、跨会话保留。当对话里出现以后的会话还用得上的信息（用户的偏好和背景、项目的关键事实、定下的决定、你摸索出的有效做法）时，"
    "在回复末尾写 <remember>一句具体的话</remember>；这次对话里一次性的内容、团队规则都不要记。"
)


def enabled(agent: Dict[str, Any]) -> bool:
    return not agent.get("external") and agent.get("memory", True) is not False and settings.value("memory", True)


def agent_memories(agent_id: str) -> List[Dict[str, Any]]:
    return sorted((m for m in store.list_docs("memory") if m.get("agent_id") == agent_id),
                  key=lambda m: (not m.get("pinned"), -m.get("updated", m["created"])))


def _hit(text: str, hint: str) -> bool:
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}  # noqa: E731
    return len(grams(text.lower()) & grams((hint or "").lower())) >= 2


def memory_note(agent: Dict[str, Any], hint: str = "", thrifty: bool = True) -> Tuple[str, str]:
    """返回（固定部分，本次相关部分）。"""
    if not enabled(agent):
        return "", ""
    mems = agent_memories(agent["id"])
    if not thrifty or sum(_tokens(m["text"]) for m in mems) <= MEMORY_ALWAYS:
        fixed, rest = mems, []
    else:
        fixed, rest = [m for m in mems if m.get("pinned")], [m for m in mems if not m.get("pinned")]
    stable = MEMORY_RULE + ("\n你记得：\n" + "\n".join("- " + m["text"] for m in fixed) if fixed else "")
    hits = [m for m in rest if _hit(m["text"], hint)][:MAX_RELEVANT]
    return stable, ("【你记得的相关内容】\n" + "\n".join("- " + m["text"] for m in hits) if hits else "")


_CHATTER = ("好的", "收到", "抱歉", "我会", "我将", "我已", "明白", "没问题")


def memory_quality(text: str) -> bool:
    """比经验库宽松：个人记忆可以是偏好、背景这类没有数字的话，但不能是客套话和空话。"""
    text = text.strip()
    if not 8 <= len(text) <= MAX_MEMORY_CHARS or text.startswith(_CHATTER) or text.startswith("我"):
        return False
    return lesson_quality(text) or not _HOLLOW.search(text)


def take_memories(msg: Dict[str, Any], agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从回复里取出 <remember>，存进这个智能体的记忆，并从正文里去掉标签。和已有记忆相近的就更新那一条。"""
    found = [" ".join(t.split())[:MAX_MEMORY_CHARS] for t in MEMORY_TAG.findall(msg.get("content") or "") if t.strip()]
    if not found:
        return []
    rest = MEMORY_TAG.sub("", msg["content"]).strip()
    msg["content"] = rest or " ".join(found)  # 整条回复只有记忆标签：当正文显示
    if not rest or not enabled(agent):
        return []
    mine = agent_memories(agent["id"])
    saved = []
    for text in found[:MAX_PER_REPLY]:
        if not memory_quality(text):
            continue
        same = next((m for m in mine if _similar(text, m["text"])), None)
        doc = {"agent_id": agent["id"], "text": text, "conv_id": msg.get("conv_id", ""),
               "pinned": bool(same and same.get("pinned")), "updated": msg.get("created", 0)}
        m = store.put_doc("memory", doc, same["id"] if same else None)  # 相近的记忆：用新说法覆盖旧的
        if not same:
            mine.append(m)
        saved.append({"id": m["id"], "text": text, "updated": bool(same)})
    return saved


def counts() -> Dict[str, int]:
    """每个智能体有几条记忆（智能体列表上显示）。"""
    out: Dict[str, int] = {}
    for m in store.list_docs("memory"):
        out[m.get("agent_id", "")] = out.get(m.get("agent_id", ""), 0) + 1
    return out


def forget_agent(agent_id: str) -> None:
    """智能体被删除时，它的记忆一起删掉。"""
    for m in store.list_docs("memory"):
        if m.get("agent_id") == agent_id:
            store.delete_doc("memory", m["id"])


def clean_memory(d: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    old = old or {}
    text = " ".join(str(d.get("text") or "").split())[:MAX_MEMORY_CHARS]
    if not text:
        raise HTTPException(400, "记忆内容不能为空")
    return {"agent_id": old.get("agent_id") or _s(d.get("agent_id"), 40), "text": text, "conv_id": old.get("conv_id", ""),
            "pinned": bool(d.get("pinned", old.get("pinned"))), "updated": time.time()}


@router.get("/api/agents/{aid}/memories")
def list_memories(aid: str):
    return {"memories": agent_memories(aid)}


@router.post("/api/agents/{aid}/memories")
def add_memory(aid: str, d: Dict[str, Any] = Body(...)):
    agent = _need("agent", aid)
    if agent.get("external"):
        raise HTTPException(400, "外部智能体有自己的记忆系统，这里不管理")
    return store.put_doc("memory", clean_memory({**d, "agent_id": aid}))


@router.put("/api/memories/{mid}")
def update_memory(mid: str, d: Dict[str, Any] = Body(...)):
    old = _need("memory", mid)
    return store.put_doc("memory", clean_memory(d, old), mid)


@router.delete("/api/memories/{mid}")
def delete_memory(mid: str):
    store.delete_doc("memory", mid)
    return {"ok": True}


@router.delete("/api/agents/{aid}/memories")
def clear_memories(aid: str):
    forget_agent(aid)
    return {"ok": True}
