"""命令行外部智能体：输出边写边看到；超时、用户停止时连同子进程一起结束。用一个 Python 小脚本假装是外部智能体。"""
import asyncio
import os
import signal
import subprocess
import sys
import time

import pytest

import external
import providers

PY = '"%s"' % sys.executable


def _agent_cmd(script):
    return '%s -c "%s"' % (PY, script)


def test_output_is_streamed_while_the_agent_is_still_working(tmp_path):
    cmd = _agent_cmd("import sys,time; q=sys.stdin.read(); [print('第%d步' % i, flush=True) or time.sleep(0.4) for i in range(3)]; print('题目长度', len(q))")
    seen = []

    async def go():
        async def on_text(t):
            seen.append((time.time(), t))
        return await external.run_cli_agent(cmd, "你好" * 10, str(tmp_path), 30, on_text)

    started = time.time()
    out = asyncio.run(go())
    assert out.splitlines() == ["第0步", "第1步", "第2步", "题目长度 20"]
    assert len(seen) >= 3  # 分几次拿到，而不是最后一次性给
    assert seen[0][0] - started < 0.9  # 第一段在它干完活（约 1.2 秒）之前就到了


def test_timeout_and_stop_kill_the_agent(tmp_path):
    marker = tmp_path / "still-running.txt"
    slow = _agent_cmd("import time,pathlib; time.sleep(3); pathlib.Path(r'%s').write_text('x')" % marker)
    with pytest.raises(providers.ProviderError, match="没有完成"):
        asyncio.run(external.run_cli_agent(slow, "", str(tmp_path), 1))

    async def stop_after_a_moment():
        task = asyncio.ensure_future(external.run_cli_agent(slow, "", str(tmp_path), 30))
        await asyncio.sleep(0.8)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(stop_after_a_moment())
    time.sleep(3.5)
    assert not marker.exists()  # 两次都被真正结束了：3 秒后该写的文件从没出现


def test_failure_reports_stderr(tmp_path):
    bad = _agent_cmd("import sys; sys.stderr.write('model not found'); sys.exit(2)")
    with pytest.raises(providers.ProviderError, match="model not found"):
        asyncio.run(external.run_cli_agent(bad, "", str(tmp_path), 10))


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill fallback")
@pytest.mark.parametrize("failure", ["denied", "missing", "timeout"])
def test_windows_stop_kills_descendants_when_taskkill_fails(tmp_path, monkeypatch, failure):
    import ctypes
    from ctypes import wintypes

    def fail_taskkill(args, **kwargs):
        assert args[0] == "taskkill"
        if failure == "missing":
            raise FileNotFoundError("taskkill")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, 1, b"", b"Access is denied")

    monkeypatch.setattr(external.subprocess, "run", fail_taskkill)
    script = ("import subprocess,sys,time; "
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
              "print(child.pid, flush=True); time.sleep(30)")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    child_pid, child_handle = None, None
    proc = subprocess.Popen([sys.executable, "-c", script], cwd=tmp_path, stdout=subprocess.PIPE)
    try:
        child_pid = int(proc.stdout.readline())
        child_handle = kernel.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
        assert child_handle, ctypes.WinError(ctypes.get_last_error())
        external._kill_tree(proc)
        assert proc.poll() is not None
        assert kernel.WaitForSingleObject(child_handle, 3000) == 0
    finally:
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGTERM)
            except OSError:
                pass
        proc.kill()
        proc.wait()
        proc.stdout.close()
        if child_handle:
            kernel.CloseHandle(child_handle)


def test_agent_timeout_setting():
    assert external.ext_timeout({}) == 900
    assert external.ext_timeout({"ext_timeout": 40}) == 2400
