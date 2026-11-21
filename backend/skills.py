"""技能与 MCP：技能的解析和管理、MCP 服务的连接、按问题挑选要带上的技能、管家的管理操作。"""
import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException, Request

import manage
import mcp
import store
import tools

from common import _ADMIN_ONLY, _need, _s, _tokens, can_admin
from hub import broadcast

router = APIRouter()

# 常见的技能安装位置：命令装到这里的新技能会被自动登记
SKILL_HOMES = ["~/.teamai/team-repo/skills", "~/.skillhub/skills", "~/.claude/skills", "~/.agents/skills", "~/.codex/skills", "~/skills"]
_PATHISH = re.compile(r"(?:[A-Za-z]:[\\/]|~[\\/]|/)[^\s\"'<>|]+")


def adopt_new_skills(since: float, cwd: str, text: str) -> List[str]:
    """找出 since 之后新出现的 SKILL.md 并登记进技能库。返回登记的技能名。"""
    roots = {os.path.expanduser(p) for p in SKILL_HOMES} | {cwd, tools.skills_dir()}
    for raw in _PATHISH.findall(text or "")[:40]:  # 命令和输出里提到的目录（如 --dir 参数、“已安装到 …”）
        p = os.path.expanduser(raw.rstrip(".,;:，。）)"))
        roots.add(p if os.path.isdir(p) else os.path.dirname(p))
    hits, seen = [], 0
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, files in os.walk(root):
            seen += 1
            if seen > 4000:
                break
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "__pycache__", ".venv")]
            if dirpath.count(os.sep) - base >= 4:
                dirnames[:] = []
            if "SKILL.md" in files:
                f = os.path.join(dirpath, "SKILL.md")
                st = os.stat(f)
                if max(st.st_mtime, st.st_ctime) >= since - 2:  # 解压出来的文件可能保留旧的修改时间，创建时间才是新的
                    hits.append(f)
    names = []
    known = {k.get("source"): k for k in store.list_docs("skill")}
    for f in dict.fromkeys(hits):
        try:
            src = manage.read_local_skill(f)
        except ValueError:
            continue
        doc = _skill_meta(clean_skill(src), src["source"], src["raw"])
        old = known.get(src["source"])
        sk = store.put_doc("skill", doc, old["id"] if old else None)
        names.append(sk["name"])
    return names


# ------------------------------------------------------------------ 技能（Skill）
def parse_skill(text: str) -> Dict[str, str]:
    """读取 SKILL.md 格式：开头的 --- 块里取 name / description，其余是正文。"""
    text = (text or "").replace("\r\n", "\n").strip()
    meta: Dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip().lower()] = v.strip().strip("\"'")
            text = text[end + 4:].strip()
    return {"name": meta.get("name", ""), "description": meta.get("description", ""), "instructions": text}


def clean_skill(d: Dict[str, Any]) -> Dict[str, Any]:
    if d.get("raw"):
        d = {**parse_skill(str(d["raw"])), **{k: v for k, v in d.items() if v and k != "raw"}}
    if not _s(d.get("instructions"), 50000):
        raise HTTPException(400, "技能内容不能为空")
    return {
        "name": _s(d.get("name"), 60) or "未命名技能",
        "description": _s(d.get("description"), 300),
        "instructions": _s(d.get("instructions"), 50000),
    }


@router.get("/api/skills")
def list_skills():
    return {"skills": store.list_docs("skill")}


@router.post("/api/skills")
def create_skill(d: Dict[str, Any] = Body(...)):
    return store.put_doc("skill", _skill_meta(clean_skill(d), "", ""))


def _skill_meta(doc: Dict[str, Any], source: str, raw: str) -> Dict[str, Any]:
    doc["source"] = source
    doc["origin"] = "external" if source else "custom"   # 外部安装 / 自己写的
    doc["hash"] = hashlib.sha1(raw.encode("utf-8")).hexdigest() if source else ""
    doc["update_available"] = False
    return doc


@router.put("/api/skills/{sid}")
def update_skill(sid: str, d: Dict[str, Any] = Body(...)):
    old = _need("skill", sid)
    doc = clean_skill(d)
    for k in ("source", "origin", "hash", "update_available", "checked"):  # 编辑内容不改变来源
        if k in old:
            doc[k] = old[k]
    return store.put_doc("skill", doc, sid)


@router.post("/api/skills/check-updates")
async def check_skill_updates(force: bool = False):
    """有来源网址的技能：重新读取一次，内容变了就标记「可升级」。6 小时内不重复检查。"""
    now, found = time.time(), 0
    for sk in store.list_docs("skill"):
        if not sk.get("source") or (not force and now - (sk.get("checked") or 0) < 6 * 3600):
            continue
        try:
            raw = (await asyncio.to_thread(manage.load_skill, sk["source"]))["raw"]
            sk["update_available"] = hashlib.sha1(raw.encode("utf-8")).hexdigest() != sk.get("hash")
        except Exception:
            pass  # 网络问题：下次再查
        sk["checked"] = now
        found += bool(sk.get("update_available"))
        store.put_doc("skill", sk, sk["id"])
    return {"updates": found}


@router.post("/api/skills/{sid}/upgrade")
async def upgrade_skill(sid: str):
    sk = _need("skill", sid)
    if not sk.get("source"):
        raise HTTPException(400, "这个技能是自己写的，没有来源可以升级")
    try:
        src = await asyncio.to_thread(manage.load_skill, sk["source"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    doc = _skill_meta(clean_skill(src), sk["source"], src["raw"])
    doc["checked"] = time.time()
    return store.put_doc("skill", doc, sid)


@router.delete("/api/skills/{sid}")
def delete_skill(sid: str):
    store.delete_doc("skill", sid)
    return {"ok": True}


# ------------------------------------------------------------------ MCP 服务
def clean_mcp(d: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    old = old or {}
    transport = "http" if d.get("transport") == "http" or (d.get("url") and not d.get("command")) else "stdio"
    args = d.get("args")
    if isinstance(args, str):
        args = args.split()
    env = d.get("env") if isinstance(d.get("env"), dict) else {}
    headers = d.get("headers") if isinstance(d.get("headers"), dict) else {}
    return {
        "name": re.sub(r"[^\w\-]+", "-", _s(d.get("name"), 40)).strip("-") or "mcp",
        "transport": transport,
        "command": _s(d.get("command"), 300),
        "args": [str(a) for a in (args or [])][:40],
        "env": {str(k): str(v) for k, v in env.items()},
        "cwd": _s(d.get("cwd"), 500),
        "url": _s(d.get("url"), 500),
        "headers": {str(k): str(v) for k, v in headers.items()},
        "enabled": bool(d.get("enabled", old.get("enabled", True))),
        "tools": old.get("tools", []),
        "error": old.get("error", ""),
    }


def public_mcp(m: Dict[str, Any]) -> Dict[str, Any]:
    """环境变量和请求头里可能有密钥：只回传键名。"""
    return {**m, "env": {k: "" for k in m.get("env") or {}}, "headers": {k: "" for k in m.get("headers") or {}},
            "env_keys": list(m.get("env") or {}), "header_keys": list(m.get("headers") or {})}


def _keep_secrets(d: Dict[str, Any], old: Dict[str, Any]) -> Dict[str, Any]:
    """编辑时没重新填写的环境变量 / 请求头沿用原值。"""
    for key in ("env", "headers"):
        if isinstance(d.get(key), dict):
            d[key] = {k: (v if v else (old.get(key) or {}).get(k, "")) for k, v in d[key].items()}
    return d


async def refresh_mcp(mid: str) -> Dict[str, Any]:
    doc = _need("mcp", mid)
    try:
        doc["tools"] = await asyncio.to_thread(mcp.list_tools, doc)
        doc["error"] = ""
    except Exception as e:
        doc["tools"], doc["error"] = [], str(e)
    return store.put_doc("mcp", doc, mid)


@router.get("/api/mcp")
def list_mcp():
    return {"servers": [public_mcp(m) for m in store.list_docs("mcp")]}


@router.post("/api/mcp")
async def create_mcp(request: Request, d: Dict[str, Any] = Body(...)):
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    doc = store.put_doc("mcp", clean_mcp(d))
    return public_mcp(await refresh_mcp(doc["id"]))


@router.post("/api/mcp/import")
async def import_mcp(request: Request, d: Dict[str, Any] = Body(...)):
    """导入其他客户端的配置：{"mcpServers": {"名字": {"command":..., "args":[...]} 或 {"url":...}}}"""
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    try:
        data = json.loads(d.get("json") or "{}")
    except ValueError as e:
        raise HTTPException(400, "不是合法的 JSON：%s" % e)
    servers = data.get("mcpServers") or data.get("servers") or data
    if not isinstance(servers, dict) or not servers:
        raise HTTPException(400, "没有找到 mcpServers")
    added = []
    for name, cfg in list(servers.items())[:30]:
        if isinstance(cfg, dict):
            doc = store.put_doc("mcp", clean_mcp({**cfg, "name": name, "transport": "http" if cfg.get("url") else "stdio"}))
            added.append(public_mcp(await refresh_mcp(doc["id"])))
    return {"servers": added}


@router.put("/api/mcp/{mid}")
async def update_mcp(mid: str, request: Request, d: Dict[str, Any] = Body(...)):
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    old = _need("mcp", mid)
    mcp.drop(mid)
    store.put_doc("mcp", clean_mcp(_keep_secrets(d, old), old), mid)
    return public_mcp(await refresh_mcp(mid))


@router.post("/api/mcp/{mid}/refresh")
async def refresh_mcp_api(mid: str):
    mcp.drop(mid)
    return public_mcp(await refresh_mcp(mid))


@router.delete("/api/mcp/{mid}")
def delete_mcp(mid: str, request: Request):
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    mcp.drop(mid)
    store.delete_doc("mcp", mid)
    return {"ok": True}


def agent_mcps(agent: Dict[str, Any]) -> List[Dict[str, Any]]:
    ids = set(agent.get("mcps") or [])
    return [m for m in store.list_docs("mcp") if m["id"] in ids and m.get("enabled") and m.get("tools")]


SKILL_READ = re.compile(r"<skill_read\s+name=[\"']([^\"'<>]{1,60})[\"']\s*/?>(?:\s*</skill_read>)?")


def _relevant(skill: Dict[str, Any], text: str) -> bool:
    """技能和当前问题是否相关：名称出现在问题里，或说明和问题有足够多的共同字词。"""
    text = (text or "").lower()
    if not text:
        return False
    if skill["name"].lower() in text:
        return True
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)}  # noqa: E731
    b = grams(text)
    name = grams(skill["name"].lower())
    if name and len(name & b) >= min(2, len(name)):  # 名称里的词出现在问题里（如「发票核对」↔「核对发票」）
        return True
    return len(grams((skill["name"] + skill.get("description", "")).lower()) & b) >= 3


def extras_note(agent: Dict[str, Any], hint: str = "", thrifty: bool = True, native: bool = False) -> Tuple[str, str]:
    """技能 + 可用 MCP 工具的紧凑清单（只给选了它们的智能体）。返回（固定部分，本次问题相关部分）。

    省 token：短技能给全文；长技能只列名称和一句说明，和当前问题相关时把全文放进本次消息，其余需要时用 <skill_read> 取。
    """
    parts, dynamic, listed = [], [], []
    ids = set(agent.get("skills") or [])
    for sk in store.list_docs("skill"):
        if sk["id"] not in ids:
            continue
        if not thrifty or _tokens(sk["instructions"]) <= 200:
            parts.append("【技能：%s】\n%s" % (sk["name"], sk["instructions"]))
            continue
        listed.append("- %s：%s" % (sk["name"], (sk.get("description") or sk["instructions"][:60]).replace("\n", " ")[:120]))
        if _relevant(sk, hint):
            dynamic.append("【这次用得上的技能：%s】（全文已附在下面，直接照做，不要再写 skill_read 读取它）\n%s" % (sk["name"], sk["instructions"]))
    if listed:
        how = "调用 read_skill 工具获取它的全文" if native else "先写 <skill_read name=\"名称\"/> 获取它的全文，写完就结束本次回复"
        parts.append("【可用技能】需要用到某个技能时，" + how + "：\n" + "\n".join(listed))
    servers = agent_mcps(agent)
    if servers:
        lines = ["【MCP 工具】需要时调用 call_mcp 工具；会先请用户确认。参数名带 * 为必填。" if native else
                 "【MCP 工具】需要时写 <mcp server=\"服务\" tool=\"工具\">JSON 参数</mcp>，写完结束本次回复，结果下一条给你；会先请用户确认。参数名带 * 为必填。"]
        for m in servers:
            for t in m["tools"][:40]:
                lines.append("- %s/%s(%s)：%s" % (m["name"], t["name"], ",".join(t["params"]), t["description"][:80]))
        parts.append("\n".join(lines))
    return "\n\n".join(parts), "\n\n".join(dynamic)


# ------------------------------------------------------------------ 管家：由智能体管理技能和 MCP
def find_extras(q: str) -> str:
    words = [w.lower() for w in re.split(r"\s+", q or "") if w]
    def hit(*fields: str) -> bool:
        blob = " ".join(fields).lower()
        return all(w in blob for w in words) if words else True
    lines = ["技能 · %s：%s" % (k["name"], k.get("description") or k["instructions"][:60].replace("\n", " "))
             for k in store.list_docs("skill") if hit(k["name"], k.get("description", ""), k["instructions"][:400])]
    lines += ["MCP · %s：%d 个工具%s" % (m["name"], len(m.get("tools") or []), "（连接失败）" if m.get("error") else "")
              for m in store.list_docs("mcp") if hit(m["name"], " ".join(t["name"] + " " + t["description"] for t in m.get("tools") or []))]
    return "\n".join(lines[:30]) or "没有找到匹配「%s」的技能或 MCP 服务" % q


async def run_manage(action: Dict[str, Any]) -> Dict[str, Any]:
    kind = action["kind"]
    try:
        if kind == "fetch":
            text, _ = await asyncio.to_thread(manage.fetch, action["url"])
            return {"ok": True, "output": text or "（没有文字内容）"}
        if kind == "skill_find":
            return {"ok": True, "output": find_extras(action.get("q", ""))}
        if kind == "skill_add":
            if action.get("url"):
                src = await asyncio.to_thread(manage.fetch_skill, action["url"])
            elif action.get("path"):
                src = manage.read_local_skill(action["path"])
            else:
                src = action
            doc = _skill_meta(clean_skill(src), src.get("source", ""), src.get("raw", ""))
            same = next((k for k in store.list_docs("skill") if doc["source"] and k.get("source") == doc["source"]), None)
            sk = store.put_doc("skill", doc, same["id"] if same else None)  # 同一网址再装一次 = 更新
            return {"ok": True, "output": "已添加技能「%s」（%d 字）。在智能体设置里勾选后即可使用。" % (sk["name"], len(sk["instructions"]))}
        if kind == "skill_remove":
            sk = next((k for k in store.list_docs("skill") if k["name"] == action["name"]), None)
            if not sk:
                return {"ok": False, "output": "没有叫「%s」的技能" % action["name"]}
            store.delete_doc("skill", sk["id"])
            return {"ok": True, "output": "已删除技能「%s」" % sk["name"]}
        if kind == "mcp_add":
            lines = []
            for cfg in manage.parse_mcp_json(action["raw"])[:10]:
                doc = store.put_doc("mcp", clean_mcp({**cfg, "transport": "http" if cfg.get("url") else "stdio"}))
                doc = await refresh_mcp(doc["id"])
                lines.append("「%s」%s" % (doc["name"], "连接失败：" + doc["error"] if doc["error"] else "已连接，%d 个工具：%s" % (
                    len(doc["tools"]), "、".join(t["name"] for t in doc["tools"][:12]))))
            return {"ok": all("连接失败" not in l for l in lines), "output": "\n".join(lines) or "配置里没有服务"}
        if kind == "mcp_remove":
            m = next((x for x in store.list_docs("mcp") if x["name"] == action["name"]), None)
            if not m:
                return {"ok": False, "output": "没有叫「%s」的 MCP 服务" % action["name"]}
            mcp.drop(m["id"])
            store.delete_doc("mcp", m["id"])
            return {"ok": True, "output": "已删除 MCP 服务「%s」" % m["name"]}
    except HTTPException as e:
        return {"ok": False, "output": str(e.detail)}
    except Exception as e:
        return {"ok": False, "output": "%s: %s" % (type(e).__name__, e)}
    finally:
        if kind not in manage.READ_ONLY:
            await broadcast({"type": "refresh"})
    return {"ok": False, "output": "未知操作"}


@router.post("/api/skills/from-url")
async def skill_from_url(d: Dict[str, Any] = Body(...)):
    try:
        src = await asyncio.to_thread(manage.fetch_skill, _s(d.get("url"), 1000))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return store.put_doc("skill", _skill_meta(clean_skill(src), _s(d.get("url"), 1000), src["raw"]))
