"""启动配置：.env + config.yaml，以及「你的数据放在哪」。

优先级：环境变量（含 .env） > config.yaml > 默认值。
必须在其他模块读取环境变量之前导入。

代码和个人数据分开放：项目文件夹里只有代码；数据库、工作区、你自己的 config.yaml / .env
默认放在系统给每个用户的应用数据目录里（见 _default_home），所以复制、打包、发布项目文件夹
都不会带上你的数据。想放到别处，设置环境变量 MAC_HOME。
"""
import os
import shutil
import sys
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
APP_NAME = "Baize"  # 白泽。曾用名 MultiAgentsControl，旧数据目录启动时自动搬过来（见 _migrate_legacy）
APP_SLUG = "baize"
LEGACY_APP_NAME = "MultiAgentsControl"
LEGACY_APP_SLUG = "multi-agents-control"


def _home_for(name: str, slug: str) -> str:
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming"), name)
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/" + name)
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), slug)


def _default_home() -> str:
    """每个用户自己的数据目录：Windows %APPDATA%\\Baize，
    macOS ~/Library/Application Support/Baize，Linux ~/.local/share/baize。"""
    if os.environ.get("MAC_HOME"):
        return os.path.abspath(os.path.expanduser(os.environ["MAC_HOME"]))
    return _home_for(APP_NAME, APP_SLUG)


HOME = _default_home()
LEGACY_HOME = _home_for(LEGACY_APP_NAME, LEGACY_APP_SLUG)  # 改名前的数据目录
# 旧版本把数据放在项目文件夹里；启动时会自动搬到 HOME（见 _migrate_legacy）
LEGACY_DATA = os.path.join(ROOT, "data")
LEGACY_WORKSPACE = os.path.join(ROOT, "workspace")
MIGRATED: List[str] = []  # 这次启动搬了哪些东西（启动时打印出来）


def load_env(path: str = os.path.join(ROOT, ".env")) -> None:
    """最简单的 KEY=VALUE 解析；已存在的环境变量不会被覆盖。"""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


def _load_yaml(path: str) -> Dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("最外层必须是键值结构")
    return data


def _path(value: Any, default: str) -> str:
    p = os.path.expanduser(str(value)) if value else default
    return os.path.abspath(p if os.path.isabs(p) else os.path.join(ROOT, p))


def _list(value: Any) -> List[Dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _has_files(path: str) -> bool:
    return os.path.isdir(path) and any(os.scandir(path))


def _move(src: str, dst: str, label: str) -> bool:
    """把旧位置的一个文件 / 文件夹搬到新位置。目标已经有东西就不动（不覆盖任何数据）。"""
    if not os.path.exists(src) or (os.path.exists(dst) and (os.path.isfile(dst) or _has_files(dst))):
        return False
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(dst):
            os.rmdir(dst)  # 空的目标文件夹：先删掉，整体搬过去
        shutil.move(src, dst)
        MIGRATED.append("%s：%s → %s" % (label, src, dst))
        return True
    except OSError as e:  # 文件被占用等：这次不搬，继续用旧位置，下次启动再试
        MIGRATED.append("%s 没能搬走（%s），这次继续使用 %s" % (label, e, src))
        return False


def _migrate_legacy() -> None:
    """从旧版本升级：数据还在项目文件夹里、或还在改名前的旧数据目录时，搬到现在的位置。显式指定了位置的不动。"""
    if os.environ.get("MAC_DATA_DIR") or os.environ.get("MAC_IN_DOCKER") == "1" or os.path.exists("/.dockerenv"):
        return
    if os.path.normcase(HOME).startswith(os.path.normcase(ROOT + os.sep)):
        return  # 有人特意把 MAC_HOME 设在项目里：尊重它
    # 产品改名（MultiAgentsControl → 白泽 Baize）：旧数据目录整体搬到新位置，目标已有内容则不动
    if not os.environ.get("MAC_HOME") and os.path.normcase(LEGACY_HOME) != os.path.normcase(HOME) and os.path.isdir(LEGACY_HOME):
        _move(LEGACY_HOME, HOME, "数据目录")
    if os.path.isfile(os.path.join(LEGACY_DATA, "mac.db")):
        _move(LEGACY_DATA, os.path.join(HOME, "data"), "数据库")
    if not os.environ.get("MAC_WORKSPACE") and _has_files(LEGACY_WORKSPACE):
        _move(LEGACY_WORKSPACE, os.path.join(HOME, "workspace"), "工作区")
    for name in ("config.yaml", ".env"):
        _move(os.path.join(ROOT, name), os.path.join(HOME, name), name)


_migrate_legacy()
load_env(os.path.join(HOME, ".env"))  # 你自己的密钥、口令
load_env()                            # 兼容：项目根目录的 .env（开发时用）

_home_config = os.path.join(HOME, "config.yaml")
CONFIG_PATH = _path(os.environ.get("MAC_CONFIG"), _home_config if os.path.isfile(_home_config) or not os.path.isfile(os.path.join(ROOT, "config.yaml")) else os.path.join(ROOT, "config.yaml"))
CONFIG_ERROR = ""
FILE: Dict[str, Any] = {}
if os.path.isfile(CONFIG_PATH):
    try:
        FILE = _load_yaml(CONFIG_PATH)
    except Exception as e:  # 配置写错不应让服务起不来：报出来，按空配置继续
        CONFIG_ERROR = "%s 解析失败：%s" % (os.path.basename(CONFIG_PATH), e)
CONFIG_LOADED = bool(FILE)

_server = FILE.get("server") if isinstance(FILE.get("server"), dict) else {}


def _setting(env: str, key: str, default: str) -> str:
    return os.environ.get(env) or str(_server.get(key) or "") or default


HOST = _setting("MAC_HOST", "host", "0.0.0.0")
PORT = int(_setting("MAC_PORT", "port", "18760"))
TOKEN = _setting("MAC_TOKEN", "token", "")
if _server.get("data_dir"):
    os.environ.setdefault("MAC_DATA_DIR", _path(_server["data_dir"], ""))
# 数据库目录：显式指定的优先；否则在用户数据目录下。旧数据没能搬走时继续用旧位置，免得像丢了数据
_legacy_stuck = os.path.isfile(os.path.join(LEGACY_DATA, "mac.db")) and not os.path.isfile(os.path.join(HOME, "data", "mac.db"))
os.environ.setdefault("MAC_DATA_DIR", LEGACY_DATA if _legacy_stuck else os.path.join(HOME, "data"))
DATA_DIR = os.path.abspath(os.environ["MAC_DATA_DIR"])
_default_workspace = LEGACY_WORKSPACE if _has_files(LEGACY_WORKSPACE) and not os.path.isdir(os.path.join(HOME, "workspace")) \
    else os.path.join(HOME, "workspace")

IN_DOCKER = os.environ.get("MAC_IN_DOCKER") == "1" or os.path.exists("/.dockerenv")
LOOPBACK = HOST in ("127.0.0.1", "localhost", "::1")

_local = FILE.get("local_access") if isinstance(FILE.get("local_access"), dict) else {}
_enabled = os.environ.get("MAC_LOCAL_ACCESS")
LOCAL = {
    "enabled": (_enabled == "1") if _enabled is not None else bool(_local.get("enabled", False)),
    "workspace": _path(os.environ.get("MAC_WORKSPACE") or _local.get("workspace"), _default_workspace),
    "approval": "auto" if _local.get("approval") == "auto" else "ask",
    "timeout": max(5, min(600, int(_local.get("timeout") or 60))),
    "allow_outside_workspace": bool(_local.get("allow_outside_workspace", False)),
    "max_steps": max(1, min(20, int(_local.get("max_steps") or 6))),
}

PROVIDERS = _list(FILE.get("providers"))
AGENTS = _list(FILE.get("agents"))
