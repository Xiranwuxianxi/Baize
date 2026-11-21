"""可以在界面里修改的设置。

保存在数据库里，覆盖 config.yaml / 环境变量给出的默认值：用户在「设置」页改过的项以界面为准，
没改过的项仍然跟随配置文件。改动立即生效，不需要重启。
"""
import os
from typing import Any, Dict, List

import config
import store

_DEFAULT_LOCAL = dict(config.LOCAL)  # 配置文件 / 环境变量给出的默认值
_DEFAULT_TOKEN = config.TOKEN
_DOC = "main"


class SettingsError(ValueError):
    pass


def _doc() -> Dict[str, Any]:
    return store.get_doc("settings", _DOC) or {}


def apply() -> None:
    """把数据库里的设置叠加到运行中的配置上。启动时和每次修改后调用。"""
    doc = _doc()
    stored = (doc.get("local") or {}).get("workspace")
    if stored and os.path.normcase(os.path.abspath(stored)) == os.path.normcase(config.LEGACY_WORKSPACE) \
            and not os.path.isdir(stored) and not os.environ.get("MAC_WORKSPACE"):
        # 以前存的是项目文件夹里的工作区，已经随升级搬走了：改成新位置
        doc["local"]["workspace"] = _DEFAULT_LOCAL["workspace"]
        store.set_doc("settings", _DOC, doc)
    config.LOCAL.clear()
    config.LOCAL.update(_DEFAULT_LOCAL)
    config.LOCAL.update(doc.get("local") or {})
    config.TOKEN = doc["token"] if "token" in doc else _DEFAULT_TOKEN


def _workspace(value: Any) -> str:
    raw = os.path.expanduser(str(value or "").strip().strip('"'))
    if not raw:
        raise SettingsError("工作区路径不能为空")
    full = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(config.ROOT, raw))
    try:
        os.makedirs(full, exist_ok=True)
        probe = os.path.join(full, ".mac-write-test")
        with open(probe, "w"):
            pass
        os.remove(probe)
    except OSError as e:
        raise SettingsError("这个位置不能用作工作区（无法创建或写入）：%s" % e)
    return full


def update(patch: Dict[str, Any]) -> None:
    doc = _doc()
    local = dict(doc.get("local") or {})
    incoming = patch.get("local") if isinstance(patch.get("local"), dict) else {}
    for key in ("enabled", "allow_outside_workspace"):
        if key in incoming:
            local[key] = bool(incoming[key])
    if "shell" in incoming:
        local["shell"] = incoming["shell"] if incoming["shell"] in ("auto", "bash", "powershell", "cmd") else "auto"
    if "approval" in incoming:
        local["approval"] = "auto" if incoming["approval"] == "auto" else "ask"
    if "workspace" in incoming:
        local["workspace"] = _workspace(incoming["workspace"])
    for key, lo, hi in (("timeout", 5, 600), ("max_steps", 1, 20)):
        if key in incoming:
            try:
                local[key] = max(lo, min(hi, int(incoming[key])))
            except (TypeError, ValueError):
                raise SettingsError("%s 需要是数字" % key)
    doc["local"] = local
    if "thrifty" in patch:  # 省 token：压缩较早的消息、成员只看最近上下文
        doc["thrifty"] = bool(patch["thrifty"])
    if "lessons" in patch:  # shared lessons on / off
        doc["lessons"] = bool(patch["lessons"])
    if "native_tools" in patch:  # 原生工具调用 开 / 关（关掉则一律用文本标签）
        doc["native_tools"] = bool(patch["native_tools"])
    if "memory" in patch:  # 每个智能体自己的记忆 开 / 关
        doc["memory"] = bool(patch["memory"])
    if "lessons_review" in patch:  # new lessons wait for the user's ok before they reach the models
        doc["lessons_review"] = bool(patch["lessons_review"])
    if "lan" in patch:
        doc["lan"] = bool(patch["lan"])
    if "public_url" in patch:  # 别的网络里的智能体用的地址（Tailscale、frp、内网穿透等），给外部智能体生成连接指令时用
        url = str(patch["public_url"] or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = "http://" + url
        doc["public_url"] = url[:300]
    if "team" in patch:  # may the lead agent add / remove agents without asking
        doc["team"] = "auto" if patch["team"] == "auto" else "ask"
    if "token" in patch:
        token = str(patch["token"] or "").strip()
        if len(token) > 200:
            raise SettingsError("访问口令太长了")
        doc["token"] = token
    store.set_doc("settings", _DOC, doc)
    apply()


def value(key: str, default: Any = None) -> Any:
    return _doc().get(key, default)


def list_files(limit: int = 200) -> List[Dict[str, Any]]:
    """工作区里的文件（最近修改的在前），给设置页展示。"""
    root = config.LOCAL["workspace"]
    found: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return found
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        if base[len(root):].count(os.sep) >= 4:
            dirs[:] = []
        for name in files:
            full = os.path.join(base, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            found.append({"path": os.path.relpath(full, root).replace(os.sep, "/"), "full": full, "size": st.st_size, "at": st.st_mtime})
            if len(found) >= 2000:
                break
    found.sort(key=lambda f: -f["at"])
    return found[:limit]


def open_folder(path: str) -> None:
    """在这台机器的文件管理器里打开一个文件夹。"""
    os.makedirs(path, exist_ok=True)
    import desktop  # 打开后把窗口切到最前面，不在后台默默打开
    desktop.reveal(path)


def open_workspace() -> None:
    open_folder(config.LOCAL["workspace"])


apply()
