"""发布前检查：列出会被发布的文件，确认里面没有你的个人数据。

用法（在项目根目录）：
    python scripts/check_release.py

检查内容：
  - 数据库、data/、workspace/、.env、config.yaml 这类个人文件有没有混进来；
  - 文件内容里有没有像 API Key 的字符串，以及你自己渠道里真实使用的密钥（从你的数据库里只读取出来比对，不打印）；
  - 有没有写死你电脑上的个人路径（例如 C:\\Users\\你的用户名）。
有问题时列出来并以非 0 退出，可以放进发布流程里。只读，不改任何文件。
"""
import getpass
import json
import os
import re
import sqlite3
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "__pycache__", ".pytest_cache", ".claude", ".idea", ".vscode", ".dev-home"}
PERSONAL_NAMES = {".env", "config.yaml"}
PERSONAL_DIRS = {"data", "workspace"}
PERSONAL_EXT = (".db", ".sqlite", ".sqlite3", ".db-journal", ".db-wal")
KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                 # OpenAI / DeepSeek / Moonshot 等
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),             # Anthropic
    re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9]{16}\b"),      # 智谱
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),                 # Google
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),             # GitHub
    re.compile(r"hf_[A-Za-z0-9]{30,}"),                    # Hugging Face
]
TEXT_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".yml", ".yaml", ".toml", ".txt", ".html", ".css",
            ".sh", ".bat", ".cfg", ".ini", ".env", ".example", "Dockerfile", ".lock")


def files_to_publish():
    """用 git 的话按 git 实际会提交的文件（遵守 .gitignore）；还没用 git 就按目录遍历。"""
    if os.path.isdir(os.path.join(ROOT, ".git")):
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode == 0:
            return [l for l in out.stdout.splitlines() if l]
    found = []
    for dirpath, dirnames, names in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for n in names:
            found.append(os.path.relpath(os.path.join(dirpath, n), ROOT).replace("\\", "/"))
    return found


def _home():
    """和 backend/config.py 同样的规则找到你的数据目录（这里不 import config，免得触发数据搬家）。"""
    if os.environ.get("MAC_HOME"):
        return os.path.expanduser(os.environ["MAC_HOME"])
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming"), "Baize")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Baize")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "baize")


def my_secrets():
    """你自己渠道里真正在用的密钥（只读，只用来比对，绝不打印）。"""
    keys = set()
    for db in (os.path.join(_home(), "data", "mac.db"), os.path.join(ROOT, "data", "mac.db")):
        if not os.path.isfile(db):
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
            for (raw,) in con.execute("SELECT data FROM docs WHERE kind IN ('provider', 'settings')"):
                d = json.loads(raw)
                for v in (d.get("api_key"), d.get("token")):
                    if isinstance(v, str) and len(v) >= 12 and not v.startswith("env:"):
                        keys.add(v)
            con.close()
        except sqlite3.Error:
            pass
    return keys


def main():
    files = files_to_publish()
    problems = []
    user = getpass.getuser()
    personal_paths = [p for p in {os.path.expanduser("~"), "C:\\Users\\" + user, "/Users/" + user, "/home/" + user} if len(user) > 2]
    secrets = my_secrets()
    for f in files:
        parts = f.split("/")
        name = parts[-1]
        if name in PERSONAL_NAMES or parts[0] in PERSONAL_DIRS or name.endswith(PERSONAL_EXT):
            problems.append((f, "个人数据文件，不应该发布"))
            continue
        if not (name.endswith(TEXT_EXT) or name in ("Dockerfile", ".gitignore", ".dockerignore", ".editorconfig")):
            continue
        try:
            text = open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        if any(s in text for s in secrets):
            problems.append((f, "包含你渠道里正在使用的真实密钥"))
        for p in KEY_PATTERNS:
            m = p.search(text)
            if m:
                problems.append((f, "疑似 API Key：%s…" % m.group(0)[:8]))
                break
        for p in personal_paths:
            if p and (p in text or p.replace("\\", "/") in text):
                problems.append((f, "写死了你电脑上的个人路径：%s" % p))
                break
    print("会发布 %d 个文件%s。" % (len(files), "（按 git 规则）" if os.path.isdir(os.path.join(ROOT, ".git")) else "（还没用 git，按目录遍历）"))
    print("你的数据目录：%s（不在项目里，不会被发布）" % _home())
    if problems:
        print("\n发现 %d 个问题：" % len(problems))
        for f, why in problems:
            print("  ✗ %s  —  %s" % (f, why))
        print("\n处理完再发布。个人文件请放到你的数据目录里，密钥请用 env:变量名 或放进数据目录下的 .env。")
        sys.exit(1)
    print("没有发现个人数据，可以发布。")


if __name__ == "__main__":
    main()
