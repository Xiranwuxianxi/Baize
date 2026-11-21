"""共享经验库：从回复里取出经验、判断值不值得记、按相关性带进上下文，以及经验的增删改接口。"""
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException

import settings
import store

from common import _need, _s, _tokens

router = APIRouter()

# ------------------------------------------------------------------ 共享经验库
# 团队踩过的坑：任何智能体犯错或被纠正后，用 <lesson>一句话</lesson> 记下来；之后所有智能体发言时都会带上，避免再犯。
LESSON_TAG = re.compile(r"<lesson>(.*?)</lesson>", re.S)
MAX_LESSONS_IN_PROMPT = 20
LESSON_RULE = (
    "只有在你犯了错、被用户纠正、操作失败、或用户明确告诉你一条规定时，才在回复末尾写 <lesson>一句话</lesson> 记下来，它会分享给整个团队；"
    "正常回答、你自己的推测或建议都不要写。"
    "必须写出具体内容本身（名称、格式、数值、正确做法），让没看过这段对话的同事也能照做；"
    "例如写「报销金额一律保留两位小数并带￥符号」，不要写「要遵循用户的格式要求」这种空话。"
)


LESSONS_ALWAYS = 300  # 经验总量不超过这么多 token 时全部常驻；超过后只带置顶的和与本次问题相关的


def _lesson_hit(text: str, hint: str) -> bool:
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}  # noqa: E731
    return len(grams(text.lower()) & grams((hint or "").lower())) >= 2


def lessons_note(hint: str = "", thrifty: bool = True) -> Tuple[str, str]:
    """返回（固定部分，本次问题相关部分）。固定部分每轮不变，便于接口缓存。"""
    if not settings.value("lessons", True):
        return "", ""
    items = sorted((x for x in store.list_docs("lesson") if not x.get("pending")),
                   key=lambda x: (not x.get("pinned"), -x["created"]))[:MAX_LESSONS_IN_PROMPT]
    head = "【团队经验】团队已确认的规则和踩过的坑。遇到相关情况时必须照做；它们不是对当前问题的回答，不要原样复述：\n"
    if not thrifty or sum(_tokens(x["text"]) for x in items) <= LESSONS_ALWAYS:
        return (head + "\n".join("- " + x["text"] for x in items) + "\n" if items else "") + LESSON_RULE, ""
    fixed = [x for x in items if x.get("pinned")]
    hits = [x for x in items if not x.get("pinned") and _lesson_hit(x["text"], hint)][:6]
    stable = (head + "\n".join("- " + x["text"] for x in fixed) + "\n" if fixed else "") + LESSON_RULE
    return stable, ("【和这次相关的团队经验，必须照做】\n" + "\n".join("- " + x["text"] for x in hits) if hits else "")


def take_lessons(msg: Dict[str, Any], agent: Dict[str, Any]) -> List[str]:
    """从回复里取出 <lesson>，存进经验库，并从正文里去掉标签。"""
    found = [" ".join(t.split())[:300] for t in LESSON_TAG.findall(msg.get("content") or "") if t.strip()]
    if not found:
        return []
    rest = LESSON_TAG.sub("", msg["content"]).strip()
    if not rest:
        # 整条回复只有一个经验标签：小模型把正常回答塞进了标签里。当正文显示，不记成经验
        msg["content"] = " ".join(found)
        return []
    msg["content"] = rest
    if not settings.value("lessons", True):
        return []
    if not lesson_triggered(msg, agent):
        return []  # 没有被纠正、没有出错：这时写的「经验」多半是普通回答
    review = settings.value("lessons_review", False)  # 打开后，合格的经验也要用户采纳才生效
    known = [x["text"] for x in store.list_docs("lesson")]
    saved = []
    for text in found[:3]:
        if lesson_quality(text) and not any(_similar(text, k) for k in known):
            known.append(text)
            doc = store.put_doc("lesson", {"text": text, "by": agent["name"], "conv_id": msg.get("conv_id", ""), "pinned": False, "pending": review})
            saved.append({"id": doc["id"], "text": text, "pending": review})
    return saved


# ---- 记经验的标准：有触发、有具体内容、不是自述、不重复 ----
_CORRECTION = re.compile(r"错|不对|不是|应该|应当|规定|一律|必须|务必|以后|下次|记住|别再|不要|禁止|纠正|搞错|改成|统一用")
_CONCRETE = re.compile(r"[0-9A-Za-z「」『』“”\"'`《》（）()\-_/\\.:：￥$%]")
_HOLLOW = re.compile(r"遵循用户|用户的要求|格式要求|礼貌|认真|仔细|注意细节|提供更多|更多上下文|准确的信息|确保回答|保持专业|理解用户|满足用户")


def lesson_triggered(msg: Dict[str, Any], agent: Dict[str, Any]) -> bool:
    """这一轮是否有值得记经验的理由：用户刚纠正或给了规定，或它自己的操作刚失败 / 被拒绝。"""
    recent = store.list_messages(msg.get("conv_id", ""), 12)
    for m in reversed(recent):
        if m.get("role") == "tool" and m.get("agent_id") == agent["id"] and m.get("status") in ("failed", "denied"):
            return True
        if m.get("role") == "agent" and m.get("agent_id") == agent["id"] and m.get("error"):
            return True
        if m.get("role") == "user":
            return bool(_CORRECTION.search(m.get("content") or ""))
    return False


def lesson_quality(text: str) -> bool:
    text = text.strip()
    if not 6 <= len(text) <= 200 or text.startswith(("我", "好的", "收到", "抱歉")):
        return False
    if _HOLLOW.search(text) and not _CONCRETE.search(text):
        return False
    return bool(_CONCRETE.search(text)) or len(text) >= 14  # 太短又没有任何具体内容的，多半是空话


def _similar(a: str, b: str) -> bool:
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}  # noqa: E731
    x, y = grams(a), grams(b)
    return bool(x and y) and len(x & y) / len(x | y) > 0.4


def clean_lesson(d: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    old = old or {}
    text = " ".join(str(d.get("text") or "").split())[:500]
    if not text:
        raise HTTPException(400, "经验内容不能为空")
    return {"text": text, "by": old.get("by") or _s(d.get("by"), 40) or "我", "conv_id": old.get("conv_id", ""),
            "pinned": bool(d.get("pinned", old.get("pinned"))), "pending": bool(d.get("pending", old.get("pending", False)))}


@router.get("/api/lessons")
def list_lessons():
    return {"lessons": sorted(store.list_docs("lesson"), key=lambda x: (not x.get("pinned"), -x["created"]))}


@router.post("/api/lessons")
def create_lesson(d: Dict[str, Any] = Body(...)):
    return store.put_doc("lesson", clean_lesson(d))


@router.put("/api/lessons/{lid}")
def update_lesson(lid: str, d: Dict[str, Any] = Body(...)):
    old = _need("lesson", lid)
    return store.put_doc("lesson", clean_lesson(d, old), lid)


@router.delete("/api/lessons/{lid}")
def delete_lesson(lid: str):
    store.delete_doc("lesson", lid)
    return {"ok": True}
