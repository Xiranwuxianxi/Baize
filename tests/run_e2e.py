"""一次跑完全部端到端测试：起一个共享的临时服务器（不碰你的数据），逐个运行 e2e_*.py。

用法：
  python tests/run_e2e.py                 # 全部
  python tests/run_e2e.py e2e_tokens e2e_v9   # 只跑这几个

需要真实模型的测试读取 MAC_TEST_BASE_URL / MAC_TEST_API_KEY / MAC_TEST_MODEL；
需要 Ollama 的测试会检查本机 Ollama。缺什么就跳过什么，不算失败。
"""
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.pop("MAC_TEST_URL", None)  # 一定起临时服务器
import harness  # noqa: E402

# e2e_ops 需要带配置文件启动的服务器，单独运行（见 tests/README.md）
names = sys.argv[1:] or sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(HERE, "e2e*.py")) if not p.endswith("e2e_ops.py"))
env = {**os.environ, "MAC_TEST_URL": harness.BASE, "MAC_TEST_DATA": harness.DATA, "PYTHONIOENCODING": "utf-8"}
results = []
for name in names:
    print("\n==== %s" % name)
    started = time.time()
    proc = subprocess.run([sys.executable, "-u", os.path.join(HERE, name + ".py")], env=env, capture_output=True, text=True, encoding="utf-8")
    out = proc.stdout + proc.stderr
    print(out.rstrip())
    state = "跳过" if "跳过：" in out and proc.returncode == 0 and "ok " not in out else ("通过" if proc.returncode == 0 else "失败")
    results.append((name, state, time.time() - started))

print("\n==== 汇总")
for name, state, secs in results:
    print("  %-14s %s  (%.0fs)" % (name, state, secs))
sys.exit(1 if any(s == "失败" for _, s, _ in results) else 0)
