"""本地操作：让智能体在这台机器上执行命令、读写文件。

智能体在回复里写标签（<run>、<read>、<write>），后端解析后征得用户同意再执行。
用文本标签而不是各家的原生工具调用，是为了让五种协议和本地小模型都能用同一套机制。

每个会话只在自己的文件夹里活动（工作区下的一个子文件夹），用户可以再给它指定几个额外的文件夹。
"""
import json
import locale
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Sequence, Tuple

import config
import manage

_TAG = re.compile(
    r"<run>(?P<run>.*?)</run>"
    r"|<read>(?P<read>.*?)</read>"
    r"|<write\s+path=[\"'](?P<path>[^\"']+)[\"']\s*>(?P<write>.*?)</write>"
    r"|<mcp\s+server=[\"'](?P<server>[^\"']+)[\"']\s+tool=[\"'](?P<tool>[^\"']+)[\"']\s*>(?P<args>.*?)</mcp>",
    re.S,
)
MAX_ACTIONS_PER_REPLY = 4
MAX_OUTPUT = 8000
MAX_READ = 200_000


def system_name() -> str:
    return {"Windows": "Windows", "Darwin": "macOS"}.get(platform.system(), "Linux")


def remote_locked() -> bool:
    """开着本地操作、又没有访问口令时，只信任这台机器上的浏览器。

    服务对局域网开放时，其他设备在此期间只能查看，不能发消息、审批或修改任何东西；
    否则同一网络里的任何人都能借智能体在这台机器上执行命令。设了访问口令就解除。
    """
    return config.LOCAL["enabled"] and not config.TOKEN and not config.LOOPBACK


REMOTE_LOCKED_TEXT = "这个控制台开启了本地操作且没有设置访问口令，为了安全，目前只有运行它的那台电脑可以发消息和修改内容。在那台电脑的「设置」里设置访问口令后，其他设备就可以正常使用。"


def status() -> Dict[str, Any]:
    """本地操作当前是否可用，以及不可用的原因（给界面展示）。"""
    local = config.LOCAL
    reason = ""
    if not local["enabled"]:
        reason = "本地操作没有开启。可以在「设置」里打开。"
    elif config.IN_DOCKER and not config.TOKEN:
        # 容器里看不出谁是“本机”，没法只信任本机浏览器，所以必须有口令
        reason = "程序运行在 Docker 容器里，需要先在「设置」里设置访问口令，本地操作才会生效。"
    return {
        "enabled": local["enabled"],
        "usable": not reason,
        "reason": reason,
        "remote_locked": not reason and remote_locked(),
        "workspace": local["workspace"],
        "approval": local["approval"],
        "in_docker": config.IN_DOCKER,
        "system": system_name(),
        "shell": config.LOCAL.get("shell") or "auto",
        "shell_name": shell()[0],
        "bash_found": bool(find_bash()),
    }


def usable() -> bool:
    return status()["usable"]


def find_bash() -> str:
    """Windows 上找 Git Bash（不用 System32 里的 WSL bash，它跑在另一个系统里）。其他系统直接用 bash。"""
    if platform.system() != "Windows":
        return shutil.which("bash") or ""
    git = shutil.which("git")
    if git:
        for rel in ("..\\bin\\bash.exe", "..\\..\\bin\\bash.exe", "..\\usr\\bin\\bash.exe"):
            cand = os.path.normpath(os.path.join(os.path.dirname(git), rel))
            if os.path.isfile(cand):
                return cand
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), "D:\\Program Files", "C:\\Program Files"):
        cand = os.path.join(base, "Git", "bin", "bash.exe")
        if base and os.path.isfile(cand):
            return cand
    return ""


def skills_dir() -> str:
    """命令行安装技能的统一位置（工作区下，已被 .gitignore 排除）。装到这里的技能会被自动登记。"""
    return os.path.join(config.LOCAL["workspace"], "_skills")


_PY: Dict[str, str] = {}


def find_python() -> str:
    """找一个真正能用的 Python。Windows 上 PATH 里的 python/python3 常常是应用商店的占位程序，一运行就弹商店。"""
    if "path" in _PY:
        return _PY["path"]
    cands = [shutil.which(n) or "" for n in ("python3", "python")]
    if platform.system() == "Windows":
        py = shutil.which("py")
        if py:
            try:
                out = subprocess.run([py, "-c", "import sys;print(sys.executable)"], capture_output=True, timeout=10)
                cands.append(_decode(out.stdout).strip())
            except (OSError, subprocess.SubprocessError):
                pass
    # 兜底：运行本程序的 Python 当初由哪个解释器创建（虚拟环境的上一级，一定是真实安装）
    base = sys.base_prefix
    cands += [os.path.join(base, "python.exe"), os.path.join(base, "bin", "python3"), os.path.join(base, "bin", "python")]
    found = ""
    for c in cands:
        if c and os.path.isfile(c) and "WindowsApps" not in c and os.path.normcase(os.path.dirname(c)) != os.path.normcase(os.path.dirname(sys.executable)):
            try:
                if subprocess.run([c, "--version"], capture_output=True, timeout=10).returncode == 0:
                    found = c
                    break
            except (OSError, subprocess.SubprocessError):
                continue
    _PY["path"] = found
    return found


def _shim_dir() -> str:
    """放 python / python3 小脚本的目录，排在 PATH 最前面，保证命令里写哪个都能用上真正的 Python。"""
    py = find_python()
    if not py:
        return ""
    d = os.path.join(config.LOCAL["workspace"], "_bin")
    try:
        os.makedirs(d, exist_ok=True)
        for name in ("python", "python3"):
            sh = os.path.join(d, name)
            body = '#!/bin/sh\nexec "%s" "$@"\n' % py.replace("\\", "/")
            if not os.path.isfile(sh) or open(sh, encoding="utf-8").read() != body:
                with open(sh, "w", encoding="utf-8", newline="\n") as f:
                    f.write(body)
                os.chmod(sh, 0o755)
            if platform.system() == "Windows":
                with open(os.path.join(d, name + ".cmd"), "w", encoding="utf-8") as f:
                    f.write('@"%s" %%*\r\n' % py)
    except OSError:
        return ""
    return d


def run_env() -> Dict[str, str]:
    """执行命令时的环境：统一 UTF-8 输出（Windows 默认 GBK，打印 ✓ 之类字符会让 Python 程序崩溃）、
    能用的 Python 在最前面、用户级命令目录（~/.local/bin，很多 CLI 装在这里）在 PATH 里。"""
    env = dict(os.environ)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", MAC_SKILLS_DIR=skills_dir())
    paths = [p for p in (_shim_dir(), os.path.expanduser("~/.local/bin")) if p and os.path.isdir(p)]
    env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
    return env


def shell() -> Tuple[str, List[str]]:
    """（给人看的名字，执行前缀）。设置里可选 auto / bash / powershell / cmd，auto 有 bash 就用 bash。"""
    want = config.LOCAL.get("shell") or "auto"
    windows = platform.system() == "Windows"
    if want in ("auto", "bash"):
        bash = find_bash()
        if bash:
            return "bash", [bash, "-lc"]
    if windows and want == "powershell":
        return "PowerShell", ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
    return ("cmd.exe", []) if windows else ("/bin/sh", [])


def note(root: str, extra: Sequence[str] = (), native: bool = False) -> str:
    """附加到系统提示词里的使用说明。尽量短：每次请求都会带上它。native=True 时操作通过原生工具调用，不用写标签。"""
    where = "你在 Docker 容器里，只能操作容器内和下面的文件夹，管不了宿主机。" if config.IN_DOCKER else ""
    shell_name = shell()[0]
    more = "；另外可以读写：" + "、".join(extra) if extra else ""
    if native:
        return (
            "【本地操作】%s系统 %s，命令行 %s。你的工作文件夹：%s（相对路径以它为起点，只能读写这里%s）。"
            "仅当任务确实要查看或改动电脑上的东西时，调用 run_command / read_file / write_file 工具；系统会先让用户确认，被拒绝就换办法或说明情况。不要编造结果。"
            % (where, system_name(), shell_name, root, more)
        )
    return (
        "【本地操作】%s系统 %s，命令行 %s。你的工作文件夹：%s（相对路径以它为起点，只能读写这里%s）。\n"
        "仅当任务确实要查看或改动电脑上的东西时，直接写标签，写完就结束本次回复，结果会在下一条给你：\n"
        "<run>命令</run>\n<read>文件路径</read>\n<write path=\"文件路径\">完整内容</write>\n"
        "每次最多 %d 个。不要口头请示，系统会让用户确认；被拒绝就换办法或说明情况。"
        "不要编造结果。写作、分析、问答等无需操作的任务不要用标签。"
        % (where, system_name(), shell_name, root, more, MAX_ACTIONS_PER_REPLY)
    )


def parse_actions(text: str) -> List[Dict[str, str]]:
    actions: List[Dict[str, str]] = []
    for m in _TAG.finditer(text or ""):
        if m.group("run") is not None and m.group("run").strip():
            actions.append({"kind": "run", "command": m.group("run").strip()})
        elif m.group("read") is not None and m.group("read").strip():
            actions.append({"kind": "read", "path": m.group("read").strip()})
        elif m.group("server"):
            raw = (m.group("args") or "").strip()
            try:
                args = json.loads(raw) if raw else {}
                bad = "" if isinstance(args, dict) else raw
            except ValueError:
                args, bad = {}, raw
            actions.append({"kind": "mcp", "server": m.group("server").strip(), "tool": m.group("tool").strip(),
                            "args": args if isinstance(args, dict) else {}, "bad_json": bad[:300]})
        elif m.group("path"):
            actions.append({"kind": "write", "path": m.group("path").strip(), "content": m.group("write").strip("\n")})
    return actions[:MAX_ACTIONS_PER_REPLY]


def strip_actions(text: str) -> str:
    """去掉回复里的操作标签（界面和摘要里不显示标签本身）。"""
    return _TAG.sub("", text or "").strip()


def describe(action: Dict[str, str]) -> str:
    kind = action.get("kind")
    if kind == "run":
        return "执行命令：" + action["command"]
    if kind == "read":
        return "读取文件：" + action["path"]
    if kind == "write":
        return "写入文件：%s（%d 个字符）" % (action["path"], len(action.get("content", "")))
    if kind == "mcp":
        return "调用 MCP 工具：%s/%s %s" % (action.get("server"), action.get("tool"), json.dumps(action.get("args") or {}, ensure_ascii=False)[:200])
    if kind == "hire":
        return "新建智能体：" + action.get("name", "")
    if kind == "fire":
        return "移除智能体：" + action.get("name", "")
    if kind == "skill_read":
        return "读取技能：" + action.get("name", "")
    return manage.describe(action)


def inside(path: str, roots: Sequence[str]) -> bool:
    full = os.path.normcase(os.path.realpath(path))
    for root in roots:
        base = os.path.normcase(os.path.realpath(root))
        # 不同盘符时 commonpath 会抛错
        if os.path.splitdrive(base)[0] == os.path.splitdrive(full)[0] and os.path.commonpath([base, full]) == base:
            return True
    return False


def _resolve(path: str, root: str, extra: Sequence[str]) -> Tuple[str, str]:
    """返回（绝对路径，错误信息）。只允许落在会话文件夹或用户额外指定的文件夹里。"""
    full = os.path.realpath(os.path.join(root, os.path.expanduser(path)))
    if not inside(full, [root, *extra]) and not config.LOCAL["allow_outside_workspace"]:
        return full, "这个路径不在本会话可以操作的文件夹里，已拒绝：%s（可操作：%s）" % (path, "、".join([root, *extra]))
    return full, ""


def full_path(path: str, root: str, extra: Sequence[str] = ()) -> str:
    """相对路径最终落在哪里（审批前展示给用户）。"""
    return _resolve(path, root, extra)[0]


def _decode(data: bytes) -> str:
    for enc in ("utf-8", locale.getpreferredencoding(False) or "utf-8"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…（输出过长，已截断，共 %d 个字符）" % len(text)


def execute(action: Dict[str, str], root: str, extra: Sequence[str] = ()) -> Dict[str, Any]:
    """同步执行一个操作（由调用方放到线程里）。返回 ok / output / code。"""
    os.makedirs(root, exist_ok=True)
    try:
        if action["kind"] == "run":
            prefix = shell()[1]
            done = subprocess.run(
                prefix + [action["command"]] if prefix else action["command"], shell=not prefix, cwd=root,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=config.LOCAL["timeout"], env=run_env(),
            )
            out = _decode(done.stdout or b"").strip()
            return {"ok": done.returncode == 0, "code": done.returncode, "output": _clip(out) or "（没有输出）"}
        full, err = _resolve(action["path"], root, extra)
        if err:
            return {"ok": False, "code": None, "output": err}
        if action["kind"] == "read":
            with open(full, "rb") as f:
                data = f.read(MAX_READ + 1)
            return {"ok": True, "code": None, "output": _clip(_decode(data[:MAX_READ]), MAX_READ)}
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(action.get("content", ""))
        return {"ok": True, "code": None, "output": "已写入 " + action["path"]}  # 给模型看相对路径即可，省 token
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": None, "output": "命令超过 %d 秒没有结束，已终止" % config.LOCAL["timeout"]}
    except OSError as e:
        return {"ok": False, "code": None, "output": "%s: %s" % (type(e).__name__, e)}
