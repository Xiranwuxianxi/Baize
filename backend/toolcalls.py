"""原生工具调用：把智能体能做的事（本地操作、MCP、读技能、管家的管理操作）声明成各家接口的「工具」，
模型直接返回结构化的调用，成功率比让它在回复里写文本标签高得多。

模型返回的工具调用会被转成和文本标签完全一样的「操作」，后面的审批、执行、把结果交还给它都走同一条路。
不支持工具的协议、或者渠道拒绝了工具参数时，自动退回文本标签（小模型也能用）。
"""
import json
from typing import Any, Dict, List, Optional

import settings
from common import can_operate
from skills import agent_mcps

NATIVE_PROTOCOLS = ("openai", "anthropic")  # 目前接好了原生工具调用的协议


def supported(provider: Optional[Dict[str, Any]]) -> bool:
    return bool(provider) and provider.get("protocol") in NATIVE_PROTOCOLS and provider.get("native_tools") is not False \
        and settings.value("native_tools", True)


def _tool(name: str, description: str, props: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}


def _s(desc: str) -> Dict[str, str]:
    return {"type": "string", "description": desc}


def schemas(agent: Dict[str, Any], has_listed_skills: bool) -> List[Dict[str, Any]]:
    """这个智能体可以调用的工具。只给它真正有权限用的，免得模型去调用会被拒绝的工具，也省 token。"""
    out: List[Dict[str, Any]] = []
    if can_operate(agent):
        out += [
            _tool("run_command", "在本会话的工作文件夹里执行一条命令行命令。会先请用户确认。", {"command": _s("要执行的命令")}, ["command"]),
            _tool("read_file", "读取一个文件的内容。", {"path": _s("文件路径，相对于工作文件夹")}, ["path"]),
            _tool("write_file", "写入（覆盖）一个文件的完整内容。会先请用户确认。",
                  {"path": _s("文件路径，相对于工作文件夹"), "content": _s("文件的完整内容")}, ["path", "content"]),
        ]
    servers = agent_mcps(agent)
    if servers:
        names = ["%s/%s" % (m["name"], t["name"]) for m in servers for t in m["tools"][:40]]
        out.append(_tool("call_mcp", "调用一个 MCP 工具。可用的有：" + "、".join(names[:60]),
                         {"server": _s("MCP 服务名"), "tool": _s("工具名"), "arguments": {"type": "object", "description": "工具参数"}},
                         ["server", "tool"]))
    if has_listed_skills:
        out.append(_tool("read_skill", "读取一个技能的完整说明。", {"name": _s("技能名称")}, ["name"]))
    if agent.get("manager"):
        out += [
            _tool("fetch_url", "读取网页或文件的文字内容。", {"url": _s("网址")}, ["url"]),
            _tool("find_extras", "在已有的技能和 MCP 里搜索。", {"q": _s("关键词")}, ["q"]),
            _tool("add_skill", "添加技能：给网址，或给本机已安装的目录，或直接给名称和内容（三选一）。会先请用户确认。",
                  {"url": _s("SKILL.md 或技能目录的网址"), "path": _s("本机 SKILL.md 或它所在的目录"),
                   "name": _s("技能名称"), "description": _s("一句话说明"), "content": _s("技能内容")}, []),
            _tool("remove_skill", "删除一个技能。会先请用户确认。", {"name": _s("技能名称")}, ["name"]),
            _tool("add_mcp", "添加 MCP 服务。会先请用户确认。",
                  {"config": _s('JSON：{"name":"名称","command":"npx","args":[...]}，远程服务写 {"name":"名称","url":"地址"}，也可以是 mcpServers 配置')}, ["config"]),
            _tool("remove_mcp", "删除一个 MCP 服务。会先请用户确认。", {"name": _s("服务名称")}, ["name"]),
        ]
    return out


def _args(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def to_action(name: str, raw_args: Any) -> Optional[Dict[str, Any]]:
    """把一次工具调用转成内部的操作（和解析文本标签得到的一模一样）。认不出的返回 None。"""
    a = _args(raw_args)
    s = lambda k: str(a.get(k) or "").strip()  # noqa: E731
    if name == "run_command" and s("command"):
        return {"kind": "run", "command": s("command")}
    if name == "read_file" and s("path"):
        return {"kind": "read", "path": s("path")}
    if name == "write_file" and s("path"):
        return {"kind": "write", "path": s("path"), "content": str(a.get("content") or "")}
    if name == "call_mcp" and s("server") and s("tool"):
        args = a.get("arguments") if isinstance(a.get("arguments"), dict) else _args(a.get("arguments"))
        return {"kind": "mcp", "server": s("server"), "tool": s("tool"), "args": args, "bad_json": ""}
    if name == "read_skill" and s("name"):
        return {"kind": "skill_read", "name": s("name")}
    if name == "fetch_url" and s("url"):
        return {"kind": "fetch", "url": s("url")}
    if name == "find_extras":
        return {"kind": "skill_find", "q": s("q")}
    if name == "add_skill":
        if s("url"):
            return {"kind": "skill_add", "url": s("url")}
        if s("path"):
            return {"kind": "skill_add", "path": s("path")}
        if s("content"):
            return {"kind": "skill_add", "name": s("name"), "description": s("description"), "instructions": s("content")}
    if name == "remove_skill" and s("name"):
        return {"kind": "skill_remove", "name": s("name")}
    if name == "add_mcp" and s("config"):
        return {"kind": "mcp_add", "raw": s("config")}
    if name == "remove_mcp" and s("name"):
        return {"kind": "mcp_remove", "name": s("name")}
    return None


def is_tools_rejection(error: str) -> bool:
    """渠道不支持工具参数时的报错（各家写法不同）：这时退回文本标签。"""
    e = (error or "").lower()
    return ("tool" in e or "function" in e) and any(k in e for k in ("not support", "unsupported", "invalid", "unknown", "不支持", "非法", "extra"))
