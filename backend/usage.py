"""用量统计：按天 × 智能体 × 模型累计 token，提供全局和单个会话的统计接口。"""
import time
from typing import Any, Dict, List

from fastapi import APIRouter

import settings
import store

router = APIRouter()

def record_usage(agent: Dict[str, Any], model: str, cid: str, use: Dict[str, Any]) -> None:
    """按「日期 × 智能体 × 模型」累计用量。单独存放，删掉会话也不影响总账。"""
    day = time.strftime("%Y-%m-%d")
    key = "%s|%s|%s" % (day, agent.get("id", ""), model)
    doc = store.get_doc("usage", key) or {"day": day, "agent_id": agent.get("id", ""), "model": model,
                                           "calls": 0, "in": 0, "out": 0, "cached": 0, "saved": 0, "est": 0}
    doc["agent_name"] = agent.get("name", "")
    doc["calls"] += 1
    for k in ("in", "out", "cached", "saved"):
        doc[k] += int(use.get(k) or 0)
    doc["est"] += 1 if use.get("est") else 0
    convs = doc.setdefault("convs", {})
    convs[cid] = convs.get(cid, 0) + int(use.get("in") or 0) + int(use.get("out") or 0)
    store.set_doc("usage", key, doc)


def _sum_usage(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {k: sum(int(r.get(k) or 0) for r in rows) for k in ("calls", "in", "out", "cached", "saved", "est")}


@router.get("/api/usage")
def usage_summary(days: int = 30):
    """用量统计：总计、今天、按天、按模型、按智能体、用得最多的会话。"""
    rows = store.list_docs("usage")
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (max(1, min(days, 365)) - 1) * 86400))
    recent = [r for r in rows if r["day"] >= since]
    today = time.strftime("%Y-%m-%d")

    def group(key):
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in recent:
            out.setdefault(key(r), []).append(r)
        return out

    titles = {c["id"]: c.get("title") or "未命名会话" for c in store.list_docs("conversation")}
    conv_tot: Dict[str, int] = {}
    for r in recent:
        for cid, n in (r.get("convs") or {}).items():
            conv_tot[cid] = conv_tot.get(cid, 0) + n
    return {
        "total": _sum_usage(rows), "range": _sum_usage(recent), "today": _sum_usage([r for r in rows if r["day"] == today]),
        "days": [{"day": d, **_sum_usage(g)} for d, g in sorted(group(lambda r: r["day"]).items())],
        "models": sorted(({"model": m, **_sum_usage(g)} for m, g in group(lambda r: r["model"] or "未知").items()), key=lambda x: -(x["in"] + x["out"])),
        "agents": sorted(({"agent": g[-1].get("agent_name") or "已删除", **_sum_usage(g)} for _, g in group(lambda r: r["agent_id"]).items()), key=lambda x: -(x["in"] + x["out"])),
        "convs": [{"id": cid, "title": titles.get(cid, "（已删除的会话）"), "tokens": n}
                  for cid, n in sorted(conv_tot.items(), key=lambda x: -x[1])[:10]],
        "thrifty": settings.value("thrifty", True),
    }


@router.get("/api/conversations/{cid}/usage")
def conv_usage(cid: str):
    """单个会话的用量：按智能体汇总这个会话里每条回复记下的数字。"""
    per: Dict[str, Dict[str, Any]] = {}
    for m in store.list_messages(cid):
        if m.get("role") != "agent" or not (m.get("tokens_in") or m.get("tokens_out")):
            continue
        row = per.setdefault(m.get("agent_name") or "?", {"agent": m.get("agent_name") or "?", "model": m.get("model", ""),
                                                         "calls": 0, "in": 0, "out": 0, "cached": 0, "saved": 0, "est": 0})
        row["calls"] += 1
        for k in ("in", "out", "cached", "saved"):
            row[k] += int(m.get("tokens_" + k) or 0)
        row["est"] += 1 if m.get("tokens_est", True) else 0
    agents = sorted(per.values(), key=lambda x: -(x["in"] + x["out"]))
    return {"total": _sum_usage(agents), "agents": agents}


@router.delete("/api/usage")
def clear_usage():
    for r in store.list_docs("usage"):
        store.delete_doc("usage", r["id"])
    return {"ok": True}
