"""端到端测试的公共部分：默认启动一个临时服务器（独立的数据目录和工作区），测完自动关掉。

这样测试永远不会碰到你正在用的数据。用法：在测试脚本开头

    from harness import API, WS, need_model, need_ollama

环境变量：
  MAC_TEST_URL        已经在跑的服务器地址（如 http://127.0.0.1:18770）。设了就直接用它，不另起服务器。
                      注意：测试会在上面新建并删除自己的数据，不要指向你日常使用的实例。
  MAC_TEST_BASE_URL   测试用模型渠道的接口地址（如 https://open.bigmodel.cn/api/paas/v4）
  MAC_TEST_API_KEY    这个渠道的密钥
  MAC_TEST_MODEL      默认模型（如 glm-5.3-flash）
  MAC_TEST_PROTOCOL   协议，默认 openai（可选 openai_responses / anthropic / gemini / ollama）
  MAC_TEST_STRONG_MODEL  领头人、新建成员等要求较高的测试用的模型，默认同 MAC_TEST_MODEL
  MAC_TEST_ANTHROPIC_URL 同一家服务的 Anthropic 兼容地址（如智谱 https://open.bigmodel.cn/api/anthropic），设了就多测一种协议
  MAC_TEST_OLLAMA=1   允许使用本机 Ollama（默认不用）
  OLLAMA_URL          本机 Ollama 地址，默认 http://127.0.0.1:11434
  OLLAMA_MODEL        需要 Ollama 的测试用哪个模型，默认用本机最小的那个
  MAC_TEST_LAN=1      让临时服务器监听局域网（用于局域网开关的测试）
"""
import atexit
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
_proc = None
DATA = ""  # 临时服务器的数据目录（用 MAC_TEST_URL 指向已有服务器时为空）


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start() -> str:
    """起一个只给本次测试用的服务器：临时数据目录、临时工作区、只监听本机。"""
    global _proc, DATA
    tmp = tempfile.mkdtemp(prefix="mac-test-")
    DATA = os.path.join(tmp, "data")
    port = _free_port()
    env = {**os.environ, "MAC_DATA_DIR": os.path.join(tmp, "data"), "MAC_WORKSPACE": os.path.join(tmp, "workspace"),
           "MAC_PORT": str(port), "MAC_HOST": "0.0.0.0" if os.environ.get("MAC_TEST_LAN") == "1" else "127.0.0.1",
           "MAC_CONFIG": os.path.join(tmp, "none.yaml"),
           "PYTHONIOENCODING": "utf-8"}
    env.pop("MAC_TOKEN", None)
    log = open(os.path.join(tmp, "server.log"), "w", encoding="utf-8")
    _proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "backend", "main.py")], cwd=os.path.join(ROOT, "backend"),
                             env=env, stdout=log, stderr=subprocess.STDOUT)
    atexit.register(_stop)
    base = "http://127.0.0.1:%d" % port
    for _ in range(100):
        if _proc.poll() is not None:
            sys.exit("测试服务器没能启动，日志：" + os.path.join(tmp, "server.log"))
        try:
            if httpx.get(base + "/api/state", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        sys.exit("测试服务器 20 秒内没有就绪，日志：" + os.path.join(tmp, "server.log"))
    _add_test_provider(base)
    print("  （临时测试服务器：%s，数据在 %s）" % (base, tmp))
    return base


def _stop() -> None:
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(10)
        except subprocess.TimeoutExpired:
            _proc.kill()


def _add_test_provider(base: str) -> None:
    url, model = os.environ.get("MAC_TEST_BASE_URL"), os.environ.get("MAC_TEST_MODEL")
    if not (url and model):
        return
    httpx.post(base + "/api/providers", json={
        "name": "测试渠道", "protocol": os.environ.get("MAC_TEST_PROTOCOL", "openai"), "base_url": url,
        "api_key": os.environ.get("MAC_TEST_API_KEY", ""), "default_model": model}, timeout=10).raise_for_status()


if os.environ.get("MAC_TEST_URL"):
    DATA = os.environ.get("MAC_TEST_DATA", "")  # run_e2e.py 起的共享临时服务器会告诉我们它的数据目录
BASE = (os.environ.get("MAC_TEST_URL") or "").rstrip("/") or _start()
API = BASE + "/api"
WS = BASE.replace("http", "ws", 1) + "/ws"


def skip(reason: str) -> None:
    print("  跳过：" + reason)
    sys.exit(0)


def need_model() -> dict:
    """返回一个设置了默认模型的渠道；没有就跳过这个测试。"""
    for p in httpx.get(API + "/state", timeout=10).json()["providers"]:
        if p.get("default_model"):
            return p
    skip("没有可用的模型渠道。设置 MAC_TEST_BASE_URL、MAC_TEST_API_KEY、MAC_TEST_MODEL 后再运行。")
    return {}


FAST = os.environ.get("MAC_TEST_MODEL", "")                      # 大多数测试用的模型（快、便宜）
STRONG = os.environ.get("MAC_TEST_STRONG_MODEL") or FAST           # 领头人、新建成员这类要求高的测试用的模型


def channels() -> list:
    """要测的模型渠道：MAC_TEST_BASE_URL（OpenAI 兼容），另外设了 MAC_TEST_ANTHROPIC_URL 就再测 Anthropic 协议。
    密钥用 env:MAC_TEST_API_KEY 引用，顺便测试「只引用环境变量」的写法。"""
    out = []
    if os.environ.get("MAC_TEST_BASE_URL") and FAST:
        out.append({"protocol": os.environ.get("MAC_TEST_PROTOCOL", "openai"), "label": "测试渠道",
                    "base_url": os.environ["MAC_TEST_BASE_URL"], "api_key": "env:MAC_TEST_API_KEY", "model": FAST})
    if os.environ.get("MAC_TEST_ANTHROPIC_URL") and FAST:
        out.append({"protocol": "anthropic", "label": "测试渠道（Anthropic 协议）",
                    "base_url": os.environ["MAC_TEST_ANTHROPIC_URL"], "api_key": "env:MAC_TEST_API_KEY", "model": FAST})
    return out


async def make_provider(c, name: str, model: str = "") -> dict:
    """在测试服务器上建一个和测试渠道相同的渠道（测试结束时由各脚本删除）。"""
    ch = (channels() or [None])[0]
    if not ch:
        skip("没有可用的模型渠道。设置 MAC_TEST_BASE_URL、MAC_TEST_API_KEY、MAC_TEST_MODEL 后再运行。")
    return (await c.post(API + "/providers", json={"name": name, "protocol": ch["protocol"], "base_url": ch["base_url"],
                                                    "api_key": ch["api_key"], "default_model": model or ch["model"]})).json()


def need_ollama() -> list:
    """返回本机 Ollama 的模型列表。只在设置了 MAC_TEST_OLLAMA=1 时才用本机 Ollama（轻薄本跑不动，默认不碰）。"""
    if os.environ.get("MAC_TEST_OLLAMA") != "1":
        skip("这个测试需要本机 Ollama，默认不运行（设置 MAC_TEST_OLLAMA=1 开启）。")
    try:
        tags = httpx.get(OLLAMA + "/api/tags", timeout=3).json().get("models") or []
    except (httpx.HTTPError, ValueError):
        tags = []
    if not tags:
        skip("本机没有可用的 Ollama（%s）。这个测试需要它。" % OLLAMA)
    return tags


def ollama_model() -> str:
    """测试用的 Ollama 模型：环境变量 OLLAMA_MODEL 指定，否则用本机最小的那个（最快）。"""
    return os.environ.get("OLLAMA_MODEL") or min(need_ollama(), key=lambda m: m.get("size", 0))["name"]
