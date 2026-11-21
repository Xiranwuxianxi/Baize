"""编排：智能体发言、执行本地操作、领头人分派任务、新建 / 移除成员、整场会话的推进。"""
import asyncio
import json
import re
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional



import config
import manage
import mcp
import providers
import settings
import store
import tools

from common import _tokens, can_operate
from hub import broadcast, member_tasks, tasks
from files import conv_dirs
from cleaning import clean_agent
from usage import record_usage
from lessons import take_lessons
from memory import take_memories
from skills import SKILL_READ, adopt_new_skills, agent_mcps, run_manage
import toolcalls
from context import MEMBER_CONTEXT, build_context, fit_context
from external import ask_external


# 当前在跑的「并行分派批次」：领头人一次分派给多人时，这批消息和操作都带同一个批次号，界面把它们并排显示
BATCH: ContextVar[str] = ContextVar("batch", default="")


async def speak(conv: Dict[str, Any], agent: Dict[str, Any], history: Optional[List[Dict[str, Any]]],
                note: str = "", ask: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cid = conv["id"]
    provider = store.get_doc("provider", agent.get("provider_id") or "")
    model = agent.get("model") or (provider or {}).get("default_model") or ""
    msg: Dict[str, Any] = {
        "id": store.new_id(), "conv_id": cid, "role": "agent", "agent_id": agent["id"],
        "agent_name": agent["name"], "model": model, "content": "", "reasoning": "",
        "error": "", "created": time.time(), "streaming": True, "batch": BATCH.get(),
    }
    msg.update(extra or {})
    await broadcast({"type": "message", "message": msg})
    try:
        if agent.get("external"):
            msg["model"] = agent.get("ext_kind") or "external"
            await ask_external(conv, agent, msg, history, note, ask)
            return msg
        if not provider:
            raise providers.ProviderError("该智能体尚未绑定模型渠道")
        if history is None:
            history = store.list_messages(cid, conv.get("context_limit") or 40)
        ctx = providers.context_length(provider)
        opts = {"temperature": agent.get("temperature"), "max_tokens": agent.get("max_tokens"), "think": bool(agent.get("think"))}
        cap = (provider.get("out_caps") or {}).get(model)  # 这个模型之前报过的输出上限
        if cap and opts["max_tokens"] and opts["max_tokens"] > cap:
            opts["max_tokens"] = cap
        for bad in (provider.get("bad_params") or {}).get(model) or []:
            opts.pop(bad, None)  # 这个模型之前报过不认这些参数（如只收默认 temperature），别再发
        # 原生工具调用：渠道支持就把它能做的事声明成工具；不支持或被拒绝时退回文本标签
        native_tools = toolcalls.schemas(agent, bool(agent.get("skills"))) if toolcalls.supported(provider) else []
        if native_tools:
            opts["tools"] = native_tools
        cut = False

        async def generate(hist: List[Dict[str, Any]], extra_ask: str, options: Dict[str, Any]) -> None:
            nonlocal cut
            cut = False
            full_ask = (ask + "\n" + extra_ask).strip()
            native = bool(options.get("tools"))
            system, msgs = build_context(conv, agent, hist, note, full_ask, native=native)
            msgs = fit_context(system, msgs, ctx)
            sent = _tokens(system) + sum(_tokens(m["content"]) for m in msgs)
            if native:  # 工具声明也算输入
                sent += _tokens(json.dumps(options["tools"], ensure_ascii=False))
            saved = 0
            if settings.value("thrifty", True):  # 不省的话要发多少：只在本地估算，不发请求
                s2, m2 = build_context(conv, agent, hist, note, full_ask, thrifty=False, native=native)
                saved = max(0, _tokens(s2) + sum(_tokens(m["content"]) for m in fit_context(s2, m2, ctx)) - sent)
            got: Dict[str, int] = {}
            out_before = msg["content"] + msg["reasoning"]
            try:
                async for kind, text in providers.stream(provider, model, system, msgs, options):
                    if kind == "usage":
                        got = text
                        continue
                    if kind == "tool_calls":  # 模型直接给出的结构化调用 → 和文本标签一样的操作
                        for call in text:
                            action = toolcalls.to_action(call["name"], call["args"])
                            if action:
                                msg.setdefault("native_actions", []).append(action)
                        continue
                    if kind == "stop":
                        cut = True
                        continue
                    msg["reasoning" if kind == "think" else "content"] += text
                    await broadcast({"type": "delta", "conv_id": cid, "id": msg["id"], "kind": kind, "text": text})
            finally:
                # 用量：接口返回了就用真实数字，否则按字数估算
                written = (msg["content"] + msg["reasoning"])[len(out_before):]
                use = {"in": got.get("in") or sent, "out": got.get("out") or (_tokens(written) if written else 0),
                       "cached": got.get("cached", 0), "saved": saved, "est": not got}
                for k, v in (("tokens_in", use["in"]), ("tokens_out", use["out"]), ("tokens_cached", use["cached"]), ("tokens_saved", saved)):
                    msg[k] = msg.get(k, 0) + v
                msg["tokens_est"] = msg.get("tokens_est", False) or use["est"]
                record_usage(agent, model, cid, use)

        try:
            await generate(history, "", opts)
        except providers.ProviderError as e:
            if opts.get("tools") and not msg["content"] and toolcalls.is_tools_rejection(str(e)):
                # 渠道不支持工具参数：记住，以后这个渠道一律用文本标签，这次直接重试
                fresh = store.get_doc("provider", provider["id"]) or provider
                fresh["native_tools"] = False
                store.put_doc("provider", fresh, provider["id"])
                opts.pop("tools", None)
                await generate(history, "", opts)
                e = None
            if e and not msg["content"]:
                # 这个模型不认某个请求参数（新版 OpenAI 模型只收默认 temperature 之类）：记住，去掉后重试
                param = providers.unsupported_param(str(e))
                if param and param in opts:
                    fresh = store.get_doc("provider", provider["id"]) or provider
                    known = set((fresh.get("bad_params") or {}).get(model) or [])
                    fresh.setdefault("bad_params", {})[model] = sorted(known | {param})
                    store.put_doc("provider", fresh, provider["id"])
                    opts.pop(param, None)
                    try:
                        await generate(history, "", opts)
                        e = None
                    except providers.ProviderError as e2:
                        e = e2
            # 「最大输出 Token」超出这个模型的上限：按报错里的上限重试一次，并记住，以后自动压到上限以内
            limit = providers.output_cap(str(e), opts.get("max_tokens")) if e else 0
            if e and (not limit or msg["content"]):
                raise
        else:
            limit = 0
        if limit:
            fresh = store.get_doc("provider", provider["id"]) or provider
            fresh.setdefault("out_caps", {})[model] = limit
            store.put_doc("provider", fresh, provider["id"])
            opts["max_tokens"] = limit
            msg["reasoning"] = ""
            await generate(history, "", opts)
        if not msg["content"] and not msg.get("native_actions") and (msg["reasoning"] or cut):
            # 思考把额度或上下文占满了、没来得及写正文：关掉思考、只带最近几条消息，自动再问一次
            await generate(history[-6:], "（请直接给出最终答复，不要展开思考过程。）", {**opts, "think": False})
        learned = take_lessons(msg, agent)
        if learned:
            msg["lessons"] = learned
        remembered = take_memories(msg, agent)
        if remembered:
            msg["memories"] = remembered
        if not msg["content"] and not msg.get("native_actions"):  # 只调用了工具、没写文字：正常
            if msg["reasoning"] or cut:
                where = (
                    "到「渠道」里把这个 Ollama 渠道的上下文长度调大（当前 %d），或在会话设置里减少「上下文消息数」" % ctx
                    if ctx else "到智能体设置里把「最大输出 Token」调大或留空，或在会话设置里减少「上下文消息数」"
                )
                msg["error"] = "模型只输出了思考过程，没来得及写正文就被长度上限截断了，自动重试一次后仍然如此。可以%s。" % where
            else:
                msg["error"] = "模型返回了空内容，可以再试一次"
        elif cut:
            msg["truncated"] = True  # 正文写到一半被长度上限截断：界面上提示可以让它继续
    except providers.ProviderError as e:
        msg["error"] = str(e)
    except asyncio.CancelledError:
        msg["error"] = "" if msg["content"] else "已停止"
        raise
    except Exception as e:  # 单个智能体出错不应中断整场对话
        msg["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        msg["streaming"] = False
        if store.get_doc("conversation", cid):
            store.save_message(msg)
        await asyncio.shield(broadcast({"type": "message", "message": msg}))
    return msg


# ---- 本地操作：智能体在回复里写操作标签，逐条征得用户同意后执行，结果再交还给它 ----
approvals: Dict[str, "asyncio.Future[str]"] = {}  # 等待用户决定的操作：消息 id -> 决定
_AFTER_ACTIONS = "（以上是操作结果。请据此继续完成任务；如果已经完成或无法继续，直接给出结论，不要重复同样的操作。你之前已经写出的分派仍然有效，不必重复，也不要假装别人已经回复。）"


async def notice(cid: str, text: str) -> None:
    """会话里居中显示的一行提示（谁加入了、权限变化等），不进模型上下文。"""
    msg = {"id": store.new_id(), "conv_id": cid, "role": "notice", "content": text, "created": time.time()}
    store.save_message(msg)
    await broadcast({"type": "message", "message": msg})


async def perform(conv: Dict[str, Any], agent: Dict[str, Any], action: Dict[str, str]) -> None:
    """一次操作：请求许可 → 执行 → 记录结果。整个过程是会话里的一条 tool 消息。"""
    cid = conv["id"]
    dirs = conv_dirs(store.get_doc("conversation", cid) or conv, create=True)
    msg: Dict[str, Any] = {
        "id": store.new_id(), "conv_id": cid, "role": "tool", "agent_id": agent["id"], "agent_name": agent["name"],
        "action": action, "status": "pending", "output": "", "code": None, "created": time.time(), "batch": BATCH.get(),
        # 让用户看清到底动的是哪里：读写文件给出完整路径，命令给出执行时所在的目录
        "path": tools.full_path(action["path"], *dirs) if action["kind"] in ("read", "write") else "",
        "cwd": dirs[0] if action["kind"] == "run" else "",
        "granted": "",
    }

    async def publish() -> None:
        store.save_message(msg)
        await broadcast({"type": "message", "message": msg})

    async def save_conv(doc: Dict[str, Any]) -> None:
        await broadcast({"type": "conversation", "conversation": store.put_doc("conversation", doc, cid)})

    try:
        # 已有的授权：全局自动、这个智能体被永久允许、本会话不再询问、本会话还剩几次
        fresh = store.get_doc("conversation", cid) or conv
        who = store.get_doc("agent", agent["id"]) or agent
        decision = ""
        if action["kind"] in manage.READ_ONLY or action["kind"] == "skill_read":
            decision, msg["granted"] = "once", "只读操作，无需确认"
        elif config.LOCAL["approval"] == "auto":
            decision, msg["granted"] = "once", "设置为自动允许"
        elif who.get("auto_approve"):
            decision, msg["granted"] = "once", "已永久允许%s" % who["name"]
        elif fresh.get("auto_approve"):
            decision, msg["granted"] = "once", "本会话不再询问"
        elif (fresh.get("approve_left") or 0) > 0:
            fresh["approve_left"] -= 1
            await save_conv(fresh)
            decision, msg["granted"] = "once", "预先允许，还剩 %d 次" % fresh["approve_left"]
        if not decision:
            await publish()
            fut: "asyncio.Future[str]" = asyncio.get_event_loop().create_future()
            approvals[msg["id"]] = fut
            try:
                decision = await fut
            finally:
                approvals.pop(msg["id"], None)
            if decision == "five":  # 这一次加上之后的四次
                fresh = store.get_doc("conversation", cid) or conv
                fresh["approve_left"] = 4
                await save_conv(fresh)
                msg["granted"] = "允许五次，还剩 4 次"
            elif decision == "forever":
                who = store.get_doc("agent", agent["id"])
                if who:
                    who["auto_approve"] = True
                    store.put_doc("agent", who, who["id"])
                    await broadcast({"type": "refresh"})
                msg["granted"] = "永久允许"
                await notice(cid, "已永久允许%s进行本地操作，可以在「设置」里撤销" % agent["name"])
            elif decision == "always":  # 旧版本的「本会话都允许」
                fresh = store.get_doc("conversation", cid) or conv
                fresh["auto_approve"] = True
                await save_conv(fresh)
                msg["granted"] = "本会话不再询问"
            elif decision == "once":
                msg["granted"] = "允许一次"
        if decision == "deny":
            msg["status"] = "denied"
            return msg
        msg["status"] = "running"
        await publish()
        if action["kind"] == "skill_read":
            sk = next((k for k in store.list_docs("skill") if k["name"] == action["name"]), None)
            result = {"code": None, "ok": bool(sk), "output": sk["instructions"] if sk else "没有叫「%s」的技能" % action["name"]}
        elif action["kind"] in manage.KINDS:
            result = {"code": None, **await run_manage(action)}
        elif action["kind"] == "mcp":
            server = next((m for m in store.list_docs("mcp") if m["name"] == action["server"]), None)
            if not server:
                result = {"ok": False, "code": None, "output": "MCP 服务「%s」不存在" % action["server"]}
            elif action.get("bad_json"):
                result = {"ok": False, "code": None, "output": "参数不是合法的 JSON：" + action["bad_json"]}
            else:
                result = {"code": None, **await asyncio.to_thread(mcp.call_tool, server, action["tool"], action["args"])}
        else:
            started = time.time()
            result = await asyncio.to_thread(tools.execute, action, *dirs)
            if action["kind"] == "run":
                # 命令装了技能（SkillHub、git clone、解压……）：自动登记到技能面板，不用再提醒谁
                found = await asyncio.to_thread(adopt_new_skills, started, dirs[0], action.get("command", "") + "\n" + (result.get("output") or ""))
                if found:
                    result["output"] = (result.get("output") or "").rstrip() + "\n\n[已自动登记到技能面板：%s]" % "、".join(found)
                    await broadcast({"type": "refresh"})
        msg.update(status="done" if result["ok"] else "failed", output=result["output"], code=result["code"])
    except asyncio.CancelledError:
        if msg["status"] in ("pending", "running"):
            msg["status"] = "cancelled"
        raise
    finally:
        if store.get_doc("conversation", cid):
            store.save_message(msg)
        await asyncio.shield(broadcast({"type": "message", "message": msg}))
    return msg


_MCP_NUDGE = (
    "（系统检查：你刚才执行了和 MCP 有关的安装命令，但还没有用 <mcp_add> 登记。不登记的话它不会出现在 MCP 面板，智能体也用不了。"
    "如果装的是 MCP 服务，现在就写 <mcp_add> 登记（不确定启动命令就先 fetch 说明）；如果不是，用一句话说明即可。）"
)
_SKILL_NUDGE = (
    "（系统检查：你刚才执行了安装技能的命令，但没有找到新装的 SKILL.md，技能面板里还看不到它。"
    "请确认装到了哪个目录，然后写 <skill_add path=\"那个目录\"/> 登记；如果安装失败了，直接说明。）"
)


async def act(conv: Dict[str, Any], agent: Dict[str, Any], history: Optional[List[Dict[str, Any]]],
              note: str = "", ask: str = "", extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """发言；如果它请求了本地操作，就执行并让它接着说，直到不再请求或达到步数上限。"""
    return (await act_all(conv, agent, history, note, ask, extra))[0]


async def act_all(conv: Dict[str, Any], agent: Dict[str, Any], history: Optional[List[Dict[str, Any]]],
                  note: str = "", ask: str = "", extra: Optional[Dict[str, Any]] = None):
    """同 act，但额外返回这一轮里它说过的全部文字（中间穿插了操作时会有好几条消息）。"""
    msg = await speak(conv, agent, history, note, ask, extra)
    said = [msg["content"]]
    local_ok, servers = can_operate(agent), {m["name"]: m for m in agent_mcps(agent)}
    boss = bool(agent.get("manager"))
    has_skills = bool(agent.get("skills"))
    if local_ok or servers or boss or has_skills:
        installed = {"mcp": False, "skill": False}  # 管家用命令装了东西，却没登记到面板
        nudged = False
        for _ in range(config.LOCAL["max_steps"]):
            actions = [] if msg["error"] else [
                a for a in tools.parse_actions(msg["content"])
                if (a["kind"] == "mcp" and a["server"] in servers) or (a["kind"] != "mcp" and local_ok)
            ] + (manage.parse(msg["content"]) if boss else []) + (
                [{"kind": "skill_read", "name": n.strip()} for n in SKILL_READ.findall(msg["content"])] if has_skills else [])
            # 原生工具调用得到的操作：和文本标签走同样的权限检查
            if not msg["error"]:
                for a in msg.get("native_actions") or []:
                    k = a["kind"]
                    if (k in ("run", "read", "write") and local_ok) or (k == "mcp" and a["server"] in servers) \
                            or (k == "skill_read" and has_skills) or (k in manage.KINDS and boss):
                        actions.append(a)
                actions = actions[:tools.MAX_ACTIONS_PER_REPLY + 4]
            ask_next = _AFTER_ACTIONS
            if not actions:
                todo = [k for k, v in installed.items() if v]
                if not boss or nudged or not todo or msg["error"]:
                    break
                nudged = True  # 只追问一次
                ask_next = _MCP_NUDGE if todo[0] == "mcp" else _SKILL_NUDGE
            for action in actions:
                done = await perform(conv, agent, action)
                ok = done and done.get("status") == "done"
                if action["kind"] == "run" and ok:
                    cmd = (action.get("command") or "").lower()
                    if "mcp" in cmd and re.search(r"install|add|npx|uvx|pip|npm|clone", cmd):
                        installed["mcp"] = True
                    if "skill" in cmd and re.search(r"install|add|clone|download|curl|wget", cmd) and "已自动登记到技能面板" not in (done.get("output") or ""):
                        installed["skill"] = True
                elif action["kind"] == "mcp_add" and ok:
                    installed["mcp"] = False
                elif action["kind"] == "skill_add" and ok:
                    installed["skill"] = False
            msg = await speak(conv, agent, None, note, ask_next, extra)
            said.append(msg["content"])
    return msg, "\n".join(said)


# ---- 领头统筹：用户只和领头人对话，领头人用「@名字：任务」分派，成员完成后由它审阅并答复 ----
_LEAD_NOTE = (
    "【你是本会话的领头人】用户只和你对话，由你统筹。%s\n"
    "要别人做事：在回复末尾另起行写「@名字：具体任务」，每行一条，名字一字不差。只有这样对方才会收到；口头安排无效。"
    "例如：@%s：（具体事情）。对方做完你会看到结果，再由你审阅并答复用户。简单问题直接回答。不要替别人作答或编造别人的回复。\n"
    "没有合适人选时可以新建：<agent name=\"名字\" description=\"一句话职责\">你是……（身份、专长、做事方式）</agent>，"
    "建好即入会，可在同一条回复里接着 @ 它；一次最多 %d 个，已有合适的就直接用。"
    "不再需要某个成员时：<remove name=\"名字\"/>。新建和移除都会先请用户确认。%s"
)
_PARALLEL_HINT = "\n同一条回复里分派的任务会同时开工，成员之间看不到彼此的结果；有先后依赖的工作分两轮安排（这轮做前置，看到结果后再派后续）。"
_REVIEW_ASK = "（成员已完成你分派的任务。请审阅他们的结果：如果还需要协作，继续用「@名字：具体任务」分派；否则直接给用户最终答复。）"
_FORMAT_ASK = (
    "（系统提示：你提到了其他智能体，但没有按格式分派，对方没有收到任何任务。如果需要他们协作，请现在只输出分派行，"
    "每行一条，格式为「@名字：具体任务」；如果不需要协作，请直接给出你对用户的答复。）"
)
_FINAL_ASK = "（成员已完成你分派的任务。请汇总他们的结果，直接给用户最终答复，不要再分派任务。）"
_LINE_PREFIX = re.compile(r"^[\s>*\-+•·\d.、)）(（#]*")


def parse_assignments(text: str, members: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """从领头人的回复里取出「@成员：任务」。容忍列表符号、加粗、全角 @ 和多行任务。"""
    by_len = sorted(members, key=lambda a: -len(a["name"]))
    found: Dict[str, Dict[str, str]] = {}
    current: Optional[Dict[str, str]] = None
    for raw in (text or "").splitlines():
        line = _LINE_PREFIX.sub("", raw).replace("＠", "@").lstrip("*_` ")
        hit = None
        if line.startswith("@"):
            body = line[1:].lstrip("*_` ")
            hit = next((a for a in by_len if body.startswith(a["name"])), None)
        if hit:
            task = re.sub(r"^[\s*_`」』]*[:：,，]?\s*", "", body[len(hit["name"]):]).strip().strip("*_`").strip()
            current = found.get(hit["id"])
            if current:  # 同一成员被多次点到：合并成一项任务
                current["task"] = (current["task"] + "\n" + task).strip()
            else:
                current = found[hit["id"]] = {"agent_id": hit["id"], "name": hit["name"], "task": task}
        elif current is not None and raw.strip() and not line.startswith("@"):
            current["task"] = (current["task"] + "\n" + raw.strip()).strip()
        else:
            current = None
    for item in found.values():
        item["task"] = item["task"][:4000] or "按上文的要求完成你负责的部分"
    return list(found.values())


def pending_assignments(history: List[Dict[str, Any]], lead: Dict[str, Any], by_id: Dict[str, Any]) -> List[Dict[str, str]]:
    """用户最近一次发言之后，领头人已分派但成员还没交出结果的任务。"""
    for i in range(len(history) - 1, -1, -1):
        m = history[i]
        if m.get("role") == "user":
            return []
        if m.get("agent_id") == lead["id"] and m.get("assignments"):
            answered = {x.get("agent_id") for x in history[i + 1:] if x.get("role") == "agent" and x.get("content")}
            return [a for a in m["assignments"] if a["agent_id"] in by_id and a["agent_id"] not in answered]
    return []


def _roster(title: str, agents: List[Dict[str, Any]]) -> str:
    return title + "\n" + "\n".join("- %s：%s" % (a["name"], a.get("description") or "（暂无简介）") for a in agents)


_AGENT_TAG = re.compile(
    r"<agent\s+name=[\"']([^\"'<>]{1,40})[\"'](?:\s+description=[\"']([^\"'<>]{0,200})[\"'])?\s*>(.*?)</agent>", re.S
)
_REMOVE_TAG = re.compile(r"<remove\s+name=[\"']([^\"'<>]{1,40})[\"']\s*/?>(?:\s*</remove>)?")
MAX_HIRES_PER_REPLY = 3
_PROMPT_LABEL = re.compile(r"^\s*(它的)?角色设定\s*[:：]\s*")  # 模型有时会把说明里的标签照抄进来
MAX_LOCAL_AGENTS = 8  # 一个会话里由智能体新建的成员上限，防止模型没完没了地造人
_HIRE_COLORS = ["slate", "pine", "rose", "amber", "plum", "olive", "persimmon", "teal"]


def strip_agent_tags(text: str) -> str:
    return _REMOVE_TAG.sub("", _AGENT_TAG.sub("", text or ""))


async def confirm_team(conv: Dict[str, Any], lead: Dict[str, Any], action: Dict[str, str]) -> bool:
    """领头人想新建或移除智能体：先问用户（设置里放开完全权限则直接通过）。会话里显示为一张确认卡片。"""
    cid = conv["id"]
    msg: Dict[str, Any] = {
        "id": store.new_id(), "conv_id": cid, "role": "tool", "agent_id": lead["id"], "agent_name": lead["name"],
        "action": action, "status": "pending", "output": "", "code": None, "created": time.time(), "granted": "",
    }
    try:
        if settings.value("team", "ask") == "auto":
            msg["status"], msg["granted"] = "done", "设置为自动允许"
            return True
        store.save_message(msg)
        await broadcast({"type": "message", "message": msg})
        fut: "asyncio.Future[str]" = asyncio.get_event_loop().create_future()
        approvals[msg["id"]] = fut
        try:
            decision = await fut
        finally:
            approvals.pop(msg["id"], None)
        msg["status"] = "denied" if decision == "deny" else "done"
        return decision != "deny"
    except asyncio.CancelledError:
        msg["status"] = "cancelled"
        raise
    finally:
        if store.get_doc("conversation", cid):
            store.save_message(msg)
        await asyncio.shield(broadcast({"type": "message", "message": msg}))


async def hire(conv: Dict[str, Any], lead: Dict[str, Any], said: str, known: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """领头人在回复里用 <agent> 自己定义的新智能体：经用户确认后建出来、放进会话。返回新建的智能体。

    新智能体只属于这个会话，沿用领头人的渠道和模型；用户之后可以编辑它，或把它加入全局。
    """
    cid = conv["id"]
    taken = {a["name"] for a in known} | {lead["name"]}
    made: List[Dict[str, Any]] = []
    for name, desc, prompt in _AGENT_TAG.findall(said or "")[:MAX_HIRES_PER_REPLY]:
        name = name.strip()
        if not name or name in taken:
            continue  # 重名：直接用已有的那个
        local = [a for a in store.list_docs("agent") if a.get("conv_id") == cid]
        if len(local) >= MAX_LOCAL_AGENTS:
            await notice(cid, "这个会话里新建的智能体已达上限（%d 个），没有再新建「%s」" % (MAX_LOCAL_AGENTS, name))
            break
        prompt = _PROMPT_LABEL.sub("", prompt.strip())
        if not await confirm_team(conv, lead, {"kind": "hire", "name": name, "description": (desc or "").strip(), "prompt": prompt}):
            await notice(cid, "你没有同意新建「%s」" % name)
            continue
        agent = store.put_doc("agent", clean_agent({
            "name": name, "description": (desc or "").strip(), "system_prompt": prompt,
            "provider_id": lead.get("provider_id"), "model": lead.get("model"),
            "no_tools": bool(lead.get("no_tools")),  # 受限的领头人不能造出一个不受限的帮手
            "color": _HIRE_COLORS[len(local) % len(_HIRE_COLORS)],
        }, cid))
        fresh = store.get_doc("conversation", cid) or conv
        fresh["agent_ids"] = fresh["agent_ids"] + [agent["id"]]
        fresh = store.put_doc("conversation", fresh, cid)
        conv["agent_ids"] = fresh["agent_ids"]
        taken.add(name)
        made.append(agent)
        await broadcast({"type": "refresh"})  # 让各端拿到新智能体的资料
        await broadcast({"type": "conversation", "conversation": fresh})
        await notice(cid, "%s 新建了智能体「%s」并拉进会话" % (lead["name"], name))
    return made


async def fire(conv: Dict[str, Any], lead: Dict[str, Any], said: str, members: List[Dict[str, Any]], reachable: List[Dict[str, Any]]) -> None:
    """领头人用 <remove> 请走的成员：经用户确认后移出会话；只属于这个会话的智能体同时删除。"""
    cid = conv["id"]
    for name in dict.fromkeys(n.strip() for n in _REMOVE_TAG.findall(said or "")):
        who = next((a for a in members if a["name"] == name), None)
        if not who:
            continue
        if not await confirm_team(conv, lead, {"kind": "fire", "name": name, "local": bool(who.get("conv_id"))}):
            await notice(cid, "你没有同意移除「%s」" % name)
            continue
        fresh = store.get_doc("conversation", cid) or conv
        fresh["agent_ids"] = [i for i in fresh["agent_ids"] if i != who["id"]]
        fresh = store.put_doc("conversation", fresh, cid)
        conv["agent_ids"] = fresh["agent_ids"]
        if who.get("conv_id") == cid:
            store.delete_doc("agent", who["id"])
        members[:] = [a for a in members if a["id"] != who["id"]]
        reachable[:] = [a for a in reachable if a["id"] != who["id"] or not who.get("conv_id")]
        await broadcast({"type": "refresh"})
        await broadcast({"type": "conversation", "conversation": fresh})
        await notice(cid, "%s 把「%s」移出了会话" % (lead["name"], name))


async def run_lead(conv: Dict[str, Any], lead: Dict[str, Any]) -> None:
    cid = conv["id"]
    everyone = {a["id"]: a for a in store.list_docs("agent")}
    members = [everyone[i] for i in conv["agent_ids"] if i in everyone and i != lead["id"]]
    # 还没进会话的全局智能体：领头人点到谁，谁就被拉进来
    outside = [a for a in everyone.values() if not a.get("conv_id") and a["id"] != lead["id"] and a["id"] not in conv["agent_ids"]]
    reachable = members + outside
    max_rounds = conv.get("rounds") or 1  # 领头人最多分派几轮，之后必须给出最终答复

    def lead_note() -> str:
        parts = []
        if members:
            parts.append(_roster("已在会话里的成员：", members))
        if outside:
            parts.append(_roster("可以随时拉进来的专业智能体（分派给他就会自动加入会话）：", outside))
        roster = "\n\n".join(parts) or "目前还没有其他智能体可以调度。"
        parallel = (store.get_doc("conversation", cid) or conv).get("lead_parallel", True)
        return _LEAD_NOTE % (roster, reachable[0]["name"] if reachable else "名字", MAX_HIRES_PER_REPLY, _PARALLEL_HINT if parallel else "")

    async def delegate(todo: List[Dict[str, str]]) -> None:
        # 先把还不在会话里的成员拉进来
        for item in todo:
            who = everyone[item["agent_id"]]
            fresh = store.get_doc("conversation", cid) or conv
            if who["id"] not in fresh["agent_ids"]:
                fresh["agent_ids"] = fresh["agent_ids"] + [who["id"]]
                fresh = store.put_doc("conversation", fresh, cid)
                conv["agent_ids"] = fresh["agent_ids"]
                await broadcast({"type": "conversation", "conversation": fresh})
                await notice(cid, "%s 把 %s 拉进了会话" % (lead["name"], who["name"]))
        limit = MEMBER_CONTEXT if settings.value("thrifty", True) else (conv.get("context_limit") or 40)

        async def work(item: Dict[str, str], history: Optional[List[Dict[str, Any]]], batch: str) -> None:
            BATCH.set(batch)  # 这一轮分派的消息和操作都带上同一个批次号，界面据此并排显示
            await act(
                conv, everyone[item["agent_id"]], history if history is not None else store.list_messages(cid, limit),
                ask="（领头人「%s」分派给你的任务）%s\n请只完成这项任务并给出结果，不要分派任务给别人。" % (lead["name"], item["task"]),
                extra={"task": item["task"]},
            )

        if (store.get_doc("conversation", cid) or conv).get("lead_parallel", True) and len(todo) > 1:
            # 并行：所有成员同时开工，基于同一份上下文（用户的需求 + 领头人的分派），各自交付，全部完成后领头人统一审阅
            batch, snapshot = store.new_id(), store.list_messages(cid, limit)
            handles = {item["agent_id"]: asyncio.ensure_future(work(item, snapshot, batch)) for item in todo}
            member_tasks[cid] = handles  # 界面上可以单独停止某一位成员，其他人照常
            try:
                await asyncio.gather(*handles.values(), return_exceptions=True)
            finally:
                member_tasks.pop(cid, None)
        else:
            for item in todo:  # 依次进行：后面的成员能看到前面成员的结果
                await work(item, None, "")

    ask, start = "", 0
    # 上一轮分派若被中途停止，先把没做完的补上，再请领头人审阅；否则它只会空等成员
    unfinished = pending_assignments(store.list_messages(cid, conv.get("context_limit") or 40), lead, everyone)
    if unfinished:
        await delegate(unfinished)
        ask, start = _REVIEW_ASK, 1
    for r in range(start, max_rounds + 1):
        final = r == max_rounds
        # 分派可能写在操作之前的那条回复里，所以要看它这一轮说过的全部内容
        msg, said = await act_all(conv, lead, None, note=lead_note(), ask=_FINAL_ASK if final and r else ask, extra={"lead": True})
        if final or msg["error"]:
            return
        hired = await hire(conv, lead, said, reachable)  # 它自己定义的新智能体，先建出来再看分派
        for agent in hired:
            everyone[agent["id"]] = agent
            members.append(agent)
            reachable.append(agent)
        await fire(conv, lead, said, members, reachable)
        said = strip_agent_tags(said)
        todo = parse_assignments(said, reachable)
        if not todo and r == 0 and (hired or any(a["name"] in said for a in reachable)):
            # 模型有时用口语安排（“小王，请你……”）而不按格式写，或者建了人却忘了派活：追问一次让它补上
            msg = await speak(conv, lead, None, note=lead_note(), ask=_FORMAT_ASK, extra={"lead": True})
            if msg["error"]:
                return
            todo = parse_assignments(strip_agent_tags(msg["content"]), reachable)
        if hired:
            msg["hired"] = [{"agent_id": a["id"], "name": a["name"], "description": a.get("description") or ""} for a in hired]
        if hired or todo:
            if todo:
                msg["assignments"] = todo
            store.save_message(msg)
            await broadcast({"type": "message", "message": msg})
        if not todo:
            return  # 没有分派 = 这就是给用户的答复
        await delegate(todo)
        ask = _REVIEW_ASK


# ---- 重启后接着做：正在跑的会话记一笔，服务被停掉时这笔还在，下次启动就知道哪些被打断了 ----
SHUTTING_DOWN = {"now": False}  # 服务正在关闭：这时被取消的会话算「被打断」，不是用户主动停止


def _run_id(cid: str) -> str:
    return "run:" + cid  # 单独的 id：不能和会话本身的 id 相同，否则会覆盖会话


def mark_run(cid: str, **data: Any) -> None:
    store.set_doc("runstate", _run_id(cid), {"conv_id": cid, **data})


def clear_run(cid: str) -> None:
    store.delete_doc("runstate", _run_id(cid))


def recover_interrupted() -> List[str]:
    """启动时调用：上次没跑完的会话标记为「被打断」，没做完的操作标记为已取消，会话里留一条提示。"""
    hit = []
    for run in store.list_docs("runstate"):
        cid = run.get("conv_id") or ""
        if run.get("interrupted") or not store.get_doc("conversation", cid):
            if not store.get_doc("conversation", cid):
                store.delete_doc("runstate", run["id"])
            continue
        for m in store.list_messages(cid, 30):
            if m.get("role") == "tool" and m.get("status") in ("pending", "running"):
                m["status"], m["output"] = "cancelled", (m.get("output") or "") + "（服务重启，这一步没有完成）"
                store.save_message(m)
        store.save_message({"id": store.new_id(), "conv_id": cid, "role": "notice", "created": time.time(),
                            "content": "上次服务停止时，这里的回复还没完成，已被打断。点「继续」可以接着做。"})
        mark_run(cid, interrupted=True, since=run.get("since", 0))
        hit.append(cid)
    return hit


def interrupted_ids() -> List[str]:
    return [r.get("conv_id", "") for r in store.list_docs("runstate") if r.get("interrupted")]


def stop_member(cid: str, agent_id: str) -> bool:
    """并行分派进行中：只停止某一位成员，其他人继续，全部结束后领头人照常审阅。"""
    task = (member_tasks.get(cid) or {}).get(agent_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


async def retry_member(cid: str, agent_id: str, batch: str) -> None:
    """重做某位成员在某一批并行分派里的任务（它出错了或被停止了），结果放回同一个看板。"""
    mark_run(cid, since=time.time())
    try:
        conv = store.get_doc("conversation", cid)
        agent = store.get_doc("agent", agent_id)
        mine = [m for m in store.list_messages(cid) if m.get("batch") == batch and m.get("agent_id") == agent_id and m.get("task")]
        if not conv or not agent or not mine:
            return
        lead = store.get_doc("agent", conv.get("lead_id") or "") or {"name": "领头人"}
        task = mine[-1]["task"]
        history = [m for m in store.list_messages(cid) if not m.get("batch")][-MEMBER_CONTEXT:]
        BATCH.set(batch)
        await act(conv, agent, history,
                  ask="（领头人「%s」分派给你的任务）%s\n请只完成这项任务并给出结果，不要分派任务给别人。" % (lead["name"], task),
                  extra={"task": task})
    except asyncio.CancelledError:
        pass
    finally:
        tasks.pop(cid, None)
        if not SHUTTING_DOWN["now"]:
            clear_run(cid)
        await asyncio.shield(broadcast({"type": "running", "conv_id": cid, "running": False}))


async def run_conversation(cid: str, targets: List[str]) -> None:
    mark_run(cid, since=time.time())  # 开始跑：记一笔（也清掉之前的「被打断」标记）
    try:
        conv = store.get_doc("conversation", cid)
        if not conv:
            return
        by_id = {a["id"]: a for a in store.list_docs("agent")}
        order = [by_id[i] for i in (targets or conv["agent_ids"]) if i in by_id]
        lead = by_id.get(conv.get("lead_id") or "")
        if conv.get("mode") == "lead" and not targets and lead:
            await run_lead(conv, lead)
            return
        rounds = 1 if targets else conv.get("rounds") or 1
        for _ in range(rounds):
            if conv.get("mode") == "parallel" and len(order) > 1:
                snapshot = store.list_messages(cid, conv.get("context_limit") or 40)
                await asyncio.gather(*[act(conv, a, snapshot) for a in order])
            else:
                for a in order:
                    await act(conv, a, None)
    except asyncio.CancelledError:
        pass
    finally:
        tasks.pop(cid, None)
        if not SHUTTING_DOWN["now"]:  # 正常结束或用户主动停止：这笔记录用不着了；服务关闭时留着，下次启动提示「被打断」
            clear_run(cid)
        await asyncio.shield(broadcast({"type": "running", "conv_id": cid, "running": False}))
