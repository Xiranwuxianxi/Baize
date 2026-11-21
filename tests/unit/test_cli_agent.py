"""命令行外部智能体：输出边写边看到；超时、用户停止时连同子进程一起结束。用一个 Python 小脚本假装是外部智能体。"""
import asyncio
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


def test_agent_timeout_setting():
    assert external.ext_timeout({}) == 900
    assert external.ext_timeout({"ext_timeout": 40}) == 2400
