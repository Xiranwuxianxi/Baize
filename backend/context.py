"""上下文拼装：把多方对话整理成某个智能体视角的 system + messages，并按省 token 规则裁剪。"""
from typing import Any, Dict, List, Optional



import attachments
import manage
import settings
import store
import tools

from common import _tokens, can_operate
from files import conv_dirs
from lessons import lessons_note
from memory import memory_note
from skills import extras_note


def build_context(conv: Dict[str, Any], agent: Dict[str, Any], history: List[Dict[str, Any]],
                  note: str = "", ask: str = "", thrifty: Optional[bool] = None, native: bool = False):
    """把多方对话整理成“以该智能体为第一人称”的 system + messages。

    note 追加到系统提示词末尾（如领头人的职责说明）；ask 作为最后一条指令附在对话末尾。
    """
    agents = {a["id"]: a for a in store.list_docs("agent")}
    others = [agents[i]["name"] for i in conv["agent_ids"] if i in agents and i != agent["id"]]
    system = "你的名字是「%s」。" % agent["name"]
    if agent.get("system_prompt"):
        system += "\n\n" + agent["system_prompt"]
    if others:
        system += (
            "\n\n【多智能体会话】同场的其他智能体：%s。他们的发言会以「[名字]:」开头出现在对话里，"
            "没有前缀的内容来自用户。请只以你自己的身份发言，不要在回复开头加名字前缀，也不要替别人发言。"
            % "、".join(others)
        )
    if note:
        system += "\n\n" + note
    if can_operate(agent):
        system += "\n\n" + tools.note(*conv_dirs(conv), native=native)
    # 省 token：系统提示词每轮保持不变（各家接口会缓存相同的开头，重复部分便宜得多）；
    # 和这次问题相关的技能全文、经验放到最后一条消息里，用完就不再重复发送
    thrifty = settings.value("thrifty", True) if thrifty is None else thrifty
    last_user = next((m.get("content") or "" for m in reversed(history) if m.get("role") == "user"), "")
    extra, dynamic = extras_note(agent, last_user, thrifty, native)
    shared, dyn_lessons = lessons_note(last_user, thrifty)
    remembered, dyn_memory = memory_note(agent, last_user, thrifty)
    dynamic = "\n\n".join(x for x in (dyn_memory, dyn_lessons, dynamic) if x)
    if shared:
        extra = (shared + "\n\n" + extra).strip()
    if remembered:
        extra = (remembered + "\n\n" + extra).strip()
    if agent.get("manager"):
        extra = (extra + "\n\n" + manage.NOTE + "\n" + manage.install_note(tools.skills_dir())).strip()
    if extra:
        system += "\n\n" + extra
    msgs: List[Dict[str, str]] = []
    # 省 token：最近几条保持原样，更早的只留开头（多智能体每次发言都要重发历史，这是最大的开销）
    keep_from = len(history) - KEEP_RECENT
    latest_user = max((i for i, m in enumerate(history) if m.get("role") == "user"), default=-1)

    def clip(text: str, i: int, limit_recent: int = 4000) -> str:
        if not thrifty or i >= len(history) - 2:
            limit = limit_recent        # 最近两条：完整
        elif i >= keep_from:
            limit = MID_CLIP            # 稍早几条：保留主体
        else:
            limit = OLD_CLIP            # 更早的：只留开头
        return text if len(text) <= limit else text[:limit] + "…（较早内容已省略）"

    for i, m in enumerate(history):
        role = m.get("role")
        if role == "notice":
            continue  # 入群之类的界面提示，不进上下文
        mine = m.get("agent_id") == agent["id"]
        pics: List[Dict[str, str]] = []
        if role == "tool":
            if m["action"].get("kind") in ("hire", "fire"):
                # 让领头人知道新建 / 移除的结果，否则被拒绝后它会以为对方已经存在
                if not mine or m.get("status") not in ("done", "denied"):
                    continue
                verb = "新建" if m["action"]["kind"] == "hire" else "移除"
                result = "已完成" if m["status"] == "done" else "用户没有同意，未执行；如仍需要，请重新写出标签"
                text = "[系统] %s智能体「%s」：%s" % (verb, m["action"].get("name", ""), result)
                if msgs and msgs[-1]["role"] == "user":
                    msgs[-1]["content"] += "\n\n" + text
                else:
                    msgs.append({"role": "user", "content": text})
                continue
            if m.get("status") in ("pending", "cancelled"):
                continue
            head = "操作结果" if mine else "%s 执行了操作" % (m.get("agent_name") or "其他智能体")
            state = {"done": "成功", "failed": "失败", "denied": "用户拒绝了这次操作"}.get(m.get("status"), "")
            text = "[%s] %s\n状态：%s\n%s" % (head, tools.describe(m["action"]), state, clip(m.get("output") or "", i, 2000))
            role = "user"
        else:
            text = clip((m.get("content") or "").strip(), i)
            if role == "user" and m.get("attachments"):
                # 附件：最新一条给全文和图片，更早的只留文件名和开头，避免每轮重复发送大段内容
                latest = i == latest_user
                text = (text + "\n\n" + attachments.context_text(conv, m["attachments"], latest)).strip()
                if latest:
                    pics = attachments.images(conv, m["attachments"])
            if not text:
                continue
            if role == "user":
                role = "user"
            elif mine:
                role = "assistant"
            else:
                role, text = "user", "[%s]: %s" % (m.get("agent_name") or "其他智能体", text)
        if msgs and msgs[-1]["role"] == role:  # 各协议都要求/偏好角色交替，合并相邻同角色
            msgs[-1]["content"] += "\n\n" + text
        else:
            msgs.append({"role": role, "content": text})
        if pics:  # 图片跟着这条用户消息走（合并相邻消息时也一并带上）
            msgs[-1].setdefault("images", []).extend(pics)
    if thrifty:
        msgs = trim_history(msgs, HISTORY_BUDGET)
    if not msgs:
        msgs.append({"role": "user", "content": "（请开始发言）"})
    if msgs[0]["role"] != "user":
        msgs.insert(0, {"role": "user", "content": "（对话开始）"})
    tail = "\n\n".join(x for x in (dynamic, ask) if x)
    if msgs[-1]["role"] == "user":
        if tail:
            msgs[-1]["content"] += "\n\n" + tail
    else:
        msgs.append({"role": "user", "content": "\n\n".join(x for x in (dynamic, ask or "（请继续）") if x)})
    return system, msgs


def trim_history(msgs: List[Dict[str, str]], budget: int) -> List[Dict[str, str]]:
    """历史总量超出预算时，从最早的开始丢（至少留最近 4 段），开头注明省略了多少。"""
    total = sum(_tokens(m["content"]) for m in msgs)
    dropped = 0
    while len(msgs) > 4 and total > budget:
        total -= _tokens(msgs[0]["content"])
        msgs = msgs[1:]
        dropped += 1
    if dropped:
        head = "（更早的 %d 段对话已省略，以节省用量；需要时可以请用户补充。）" % dropped
        if msgs[0]["role"] == "user":
            msgs[0] = {**msgs[0], "content": head + "\n\n" + msgs[0]["content"]}
        else:
            msgs.insert(0, {"role": "user", "content": head})
    return msgs


MEMBER_CONTEXT = 6  # 受派成员只需要任务和最近几条消息
KEEP_RECENT = 4   # 最近几条消息完整保留
OLD_CLIP = 200    # 更早的消息每条最多保留多少字
MID_CLIP = 600    # 最近几条里，除最新两条外每条最多保留多少字
HISTORY_BUDGET = 3000  # 省 token 时，每次发给模型的历史最多约多少 token


def fit_context(system: str, msgs: List[Dict[str, str]], ctx: int) -> List[Dict[str, str]]:
    """上下文窗口有限时（Ollama），从最早的消息开始丢，给思考和正文留出空间。

    不这样做的话，历史一长，模型刚想完就撞上窗口上限，一个字的正文都写不出来。
    """
    if not ctx:
        return msgs
    budget = ctx - _tokens(system) - max(1500, ctx // 3)  # 留三分之一（至少 1500）给输出
    kept = list(msgs)
    while len(kept) > 1 and sum(_tokens(m["content"]) for m in kept) > budget:
        kept.pop(0)
    if kept and kept[0]["role"] != "user":
        kept.insert(0, {"role": "user", "content": "（更早的对话已省略）"})
    last = kept[-1]
    if budget > 200 and _tokens(last["content"]) > budget:  # 单条消息就超了：保留结尾
        kept[-1] = {**last, "content": "（前文过长已省略）…" + last["content"][-budget:]}
    return kept
