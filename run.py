#!/usr/bin/env python3
"""跨平台启动器：Windows / macOS / Linux 通用。

首次运行会创建虚拟环境、安装后端依赖、构建前端，然后启动服务。
只依赖 Python 标准库，可以直接用系统自带的 Python 运行：

    python run.py            # 启动
    python run.py --rebuild  # 强制重新构建前端后启动
    python run.py --setup    # 只安装和构建，不启动
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
WINDOWS = os.name == "nt"
VENV = os.path.join(ROOT, "backend", ".venv")
PY = os.path.join(VENV, "Scripts" if WINDOWS else "bin", "python.exe" if WINDOWS else "python")
FRONT = os.path.join(ROOT, "frontend")
DIST = os.path.join(FRONT, "dist", "index.html")
REQ = os.path.join(ROOT, "backend", "requirements.lock")  # 锁定版本，所有人装到同一套经过测试的依赖
STAMP = os.path.join(VENV, ".requirements-installed")


def step(text):
    print("\n==> " + text, flush=True)


def run(cmd, cwd=ROOT):
    subprocess.check_call(cmd, cwd=cwd)


def fail(text):
    print("\n[!] " + text, file=sys.stderr)
    sys.exit(1)


def newer(a, b):
    return not os.path.exists(b) or os.path.getmtime(a) > os.path.getmtime(b)


def ensure_backend():
    if sys.version_info < (3, 9):
        fail("需要 Python 3.10 或更高版本，当前是 %s" % sys.version.split()[0])
    if sys.version_info < (3, 10):  # 3.9 还能运行，但已停止安全更新
        print("\n  提示：Python %s 已停止安全更新，建议升级到 3.10 或更高版本（https://www.python.org/downloads/）。"
              "\n        升级后删除 backend/.venv 再运行一次 run.py 即可。\n" % sys.version.split()[0], flush=True)
    if not os.path.exists(PY):
        step("创建 Python 虚拟环境")
        run([sys.executable, "-m", "venv", VENV])
    if newer(REQ, STAMP):  # 依赖清单有变化时才重新安装
        step("安装后端依赖")
        run([PY, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", REQ])
        open(STAMP, "w").close()


def frontend_stale():
    if not os.path.exists(DIST):
        return True
    built = os.path.getmtime(DIST)
    for base, dirs, files in os.walk(os.path.join(FRONT, "src")):
        if any(os.path.getmtime(os.path.join(base, f)) > built for f in files):
            return True
    return any(os.path.getmtime(os.path.join(FRONT, f)) > built for f in ("package.json", "index.html", "vite.config.js"))


def ensure_frontend(force):
    if not force and not frontend_stale():
        return
    npm = shutil.which("npm")
    if not npm:
        if os.path.exists(DIST):
            print("[i] 没找到 npm，继续使用已有的前端构建。")
            return
        fail("需要 Node.js 18+（npm）来构建前端。安装后重试，或改用 Docker 部署。")
    if newer(os.path.join(FRONT, "package.json"), os.path.join(FRONT, "node_modules", ".package-lock.json")):
        step("安装前端依赖")
        run([npm, "install", "--no-fund", "--no-audit"], cwd=FRONT)
    step("构建前端")
    run([npm, "run", "build"], cwd=FRONT)


def main():
    args = set(sys.argv[1:])
    ensure_backend()
    ensure_frontend("--rebuild" in args)
    if "--setup" in args:
        print("\n安装完成。运行 python run.py 启动。")
        return
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        sys.exit(subprocess.call([PY, os.path.join(ROOT, "backend", "main.py")], cwd=ROOT, env=env))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        fail("命令执行失败（退出码 %s）：%s" % (e.returncode, " ".join(map(str, e.cmd))))
