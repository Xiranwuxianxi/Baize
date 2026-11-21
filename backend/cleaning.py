"""把界面 / 配置传来的数据整理成存库的格式：渠道、智能体、会话。"""
import base64
import os
import re
import secrets
from typing import Any, Dict, Optional

from fastapi import HTTPException

import config
import providers
import store

from common import _num, _s
from files import clean_folders


def clean_provider(d: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    old = old or {}
    proto = _s(d.get("protocol")) or old.get("protocol") or "openai"
    if proto not in providers.DEFAULT_BASE:
        raise HTTPException(400, "不支持的协议")
    headers = d.get("extra_headers", old.get("extra_headers"))
    key = d.get("api_key")
    return {
        "name": _s(d.get("name")) or "未命名渠道",
        "protocol": proto,
        "base_url": _s(d.get("base_url"), 500),
        # 未提交 api_key 字段 = 保持原值；提交空串 = 清除
        "api_key": old.get("api_key", "") if key is None else _s(key, 500),
        "default_model": _s(d.get("default_model")),
        "extra_headers": headers if isinstance(headers, dict) else {},
        "models": old.get("models", []),
        "out_caps": old.get("out_caps", {}),  # 各模型实际允许的最大输出 token（从接口报错里学到的）
        "bad_params": old.get("bad_params", {}),  # 各模型不认的请求参数（从接口报错里学到的）
        "native_tools": old.get("native_tools"),  # 渠道是否已学过「不支持原生工具调用」
        # 仅 Ollama 原生协议使用：加载模型时的上下文窗口。留空用默认值
        "num_ctx": _num(d.get("num_ctx", old.get("num_ctx")), 2048, 1048576, as_int=True),
        # 流式读取超时（秒）：深度思考模型吐字慢可调大，默认 600
        "timeout": _num(d.get("timeout", old.get("timeout")), 30, 3600, as_int=True),
        "managed": bool(old.get("managed")),  # 来自 config.yaml：重启时会按文件内容覆盖
    }


def public_provider(p: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in p.items() if k != "api_key"}
    key = p.get("api_key") or ""
    out["key_set"] = bool(key)
    name = providers.env_ref(key)
    if name:  # 引用的是环境变量名，不是密钥本身，可以回显
        out["key_hint"] = "环境变量 " + name
    else:
        out["key_hint"] = ("…" + key[-4:]) if len(key) >= 8 else ""
    return out


_IMAGE = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$")
MAX_AVATAR_CHARS = 200_000  # 约 150 KB 的图片；前端上传时会先缩到 160 像素，通常只有几 KB


def clean_image(v: Any) -> str:
    """头像图片只接受内嵌的位图 data URL（不收 SVG 和外链），过大或格式不对就丢弃。"""
    v = str(v or "")
    return v if len(v) <= MAX_AVATAR_CHARS and _IMAGE.match(v) else ""


def image_from_file(path: str) -> str:
    """config.yaml 里的 avatar_file：把本地图片读成 data URL。"""
    kind = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".gif": "gif"}.get(os.path.splitext(path)[1].lower())
    full = path if os.path.isabs(path) else os.path.join(os.path.dirname(config.CONFIG_PATH), path)
    if not kind or not os.path.isfile(full) or os.path.getsize(full) > 140_000:
        return ""
    with open(full, "rb") as f:
        return "data:image/%s;base64,%s" % (kind, base64.b64encode(f.read()).decode())


def clean_agent(d: Dict[str, Any], conv_id: str = "", old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    old = old or {}
    return {
        "avatar_image": clean_image(d.get("avatar_image")),  # 上传的头像；有它时优先于图标和首字
        "conv_id": conv_id,  # 空 = 全局智能体；否则只属于这个会话
        "chief": bool(d.get("chief")) and not conv_id,  # 总智能体：默认接管每个新会话
        "external": bool(d.get("external", old.get("external"))),  # driven by an outside agent instead of a model channel
        "ext_kind": _s(d.get("ext_kind", old.get("ext_kind")), 30),
        "ext_mode": "cli" if d.get("ext_mode", old.get("ext_mode")) == "cli" else "poll",  # cli = 每轮直接调用本机命令行
        "ext_cmd": _s(d.get("ext_cmd", old.get("ext_cmd")), 500),
        "ext_timeout": _num(d.get("ext_timeout", old.get("ext_timeout")), 1, 120, as_int=True) or 15,  # 一轮最多等几分钟
        "ext_token": old.get("ext_token") or (secrets.token_urlsafe(18) if d.get("external") else ""),
        "think": bool(d.get("think")),
        "memory": bool(d.get("memory", old.get("memory", True))),  # 自己的长期记忆（外部智能体不用）
        "manager": bool(d.get("manager")),  # can add / find / remove skills and MCP servers  # deep thinking: slower; off by default
        "skills": [str(x) for x in (d.get("skills") or [])][:30],
        "mcps": [str(x) for x in (d.get("mcps") or [])][:30],
        "no_tools": bool(d.get("no_tools")),  # per-agent block: this agent may never request local operations
        "auto_approve": bool(d.get("auto_approve")),  # permanently allowed: its operations run without asking
        "managed": bool(old.get("managed")),
        "name": _s(d.get("name"), 40) or "未命名智能体",
        "avatar": _s(d.get("avatar"), 32),  # 留空 = 用名字首字
        "color": _s(d.get("color"), 20) or "persimmon",
        "description": _s(d.get("description"), 200),
        "system_prompt": _s(d.get("system_prompt"), 20000),
        "provider_id": _s(d.get("provider_id"), 40),
        "model": _s(d.get("model")),
        "temperature": _num(d.get("temperature"), 0, 2),
        "max_tokens": _num(d.get("max_tokens"), 1, 200000, as_int=True),
    }


def clean_conv(d: Dict[str, Any], cid: str = "") -> Dict[str, Any]:
    old = (store.get_doc("conversation", cid) if cid else None) or {}
    # 可选成员 = 全局智能体 + 只属于本会话的智能体
    known = {a["id"] for a in store.list_docs("agent") if not a.get("conv_id") or a.get("conv_id") == cid}
    ids = [i for i in dict.fromkeys(d.get("agent_ids") or []) if i in known]
    mode = d.get("mode") if d.get("mode") in ("parallel", "lead") else "sequential"
    lead = d.get("lead_id") if d.get("lead_id") in ids else (ids[0] if ids else "")
    return {
        "title": _s(d.get("title"), 60) or "新会话",
        "agent_ids": ids,
        "mode": mode,
        "lead_id": lead if mode == "lead" else "",
        "rounds": _num(d.get("rounds"), 1, 6, as_int=True) or 1,
        # 领头统筹时，分派出去的任务：True = 成员同时开工、各自交付（默认）；False = 一个做完下一个再做（后面的能看到前面的结果）
        "lead_parallel": bool(d.get("lead_parallel", old.get("lead_parallel", True))),
        "context_limit": _num(d.get("context_limit"), 2, 400, as_int=True) or 40,
        "pinned": bool(d.get("pinned", old.get("pinned"))),
        "folder": old.get("folder", ""),  # its own folder under the workspace, fixed on first use
        "folders": clean_folders(d.get("folders", old.get("folders"))),  # extra folders the user lets it touch
        "auto_approve": bool(d.get("auto_approve")),  # this conversation never asks
        "approve_left": _num(d.get("approve_left"), 0, 99, as_int=True) or 0,  # pre-approved operations remaining
    }


def set_chief(agent_id: str) -> None:
    """总智能体只能有一个：把其余的取消。"""
    for a in store.list_docs("agent"):
        if a.get("chief") and a["id"] != agent_id:
            a["chief"] = False
            store.put_doc("agent", a, a["id"])
