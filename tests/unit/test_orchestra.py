"""编排层的离线测试：用假模型（按脚本回复）代替真实接口，覆盖接力、领头分派、新建成员、
本地操作审批、输出上限自动重试、记忆写入、用量记账。CI 里每次都跑，不需要任何模型。"""
import asyncio
import re
import time

import pytest

import orchestra
import providers
import settings
import store


class FakeModel:
    """假的模型接口。script(name, system, msgs, opts) 返回回复文本，或抛出 ProviderError。"""

    def __init__(self, script):
        self.script = script
        self.calls = []

    async def stream(self, provider, model, system, msgs, opts=None):
        name = re.search(r"你的名字是「(.+?)」", system).group(1)
        self.calls.append({"name": name, "system": system, "msgs": msgs, "opts": dict(opts or {})})
        reply = self.script(name, system, msgs, opts or {})
        for i in range(0, len(reply), 7):  # 分几段流式返回
            yield "text", reply[i:i + 7]
        yield "usage", {"in": 100, "out": len(reply), "cached": 40}


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def use(script):
        holder["m"] = FakeModel(script)
        monkeypatch.setattr(providers, "stream", holder["m"].stream)
        return holder["m"]
    return use


def _provider():
    return store.put_doc("provider", {"name": "假渠道", "protocol": "openai", "base_url": "http://fake", "default_model": "fake-1", "models": []})


def _agent(p, name, **kw):
    return store.put_doc("agent", {"name": name, "provider_id": p["id"], "model": "fake-1", "no_tools": True, "memory": True, **kw})


def _conv(agents, **kw):
    return store.put_doc("conversation", {"title": "测试", "agent_ids": [a["id"] for a in agents], "mode": "sequential", "rounds": 1, **kw})


def _say(cid, text):
    store.save_message({"id": store.new_id(), "conv_id": cid, "role": "user", "content": text, "created": time.time()})


def _agent_msgs(cid):
    return [m for m in store.list_messages(cid) if m["role"] == "agent"]


def test_relay_speaks_in_order_and_later_agents_see_earlier_replies(fake):
    model = fake(lambda name, *_: "我是%s的意见" % name)
    p = _provider()
    a, b = _agent(p, "甲"), _agent(p, "乙")
    conv = _conv([a, b], rounds=2)
    _say(conv["id"], "讨论一下")
    asyncio.run(orchestra.run_conversation(conv["id"], []))
    said = _agent_msgs(conv["id"])
    assert [m["agent_name"] for m in said] == ["甲", "乙", "甲", "乙"]
    assert all(not m["error"] and m["content"].startswith("我是") for m in said)
    second = model.calls[1]
    assert any("[甲]: 我是甲的意见" in m["content"] for m in second["msgs"])  # 乙看得到甲刚说的
    assert said[0]["tokens_in"] == 100 and said[0]["tokens_est"] is False  # 用的是接口给的真实用量


def test_lead_assigns_member_then_summarizes(fake):
    def script(name, system, msgs, opts):
        last = msgs[-1]["content"]
        if name == "领头":
            return "最终结论：照产品经理的方案做。" if "成员已完成" in last else "我来安排。\n@产品经理：列出三个核心功能"
        return "1. 记账 2. 统计 3. 预算"
    fake(script)
    p = _provider()
    lead, pm = _agent(p, "领头"), _agent(p, "产品经理", description="梳理需求")
    conv = _conv([lead, pm], mode="lead", lead_id=lead["id"])
    _say(conv["id"], "帮我规划记账 App")
    asyncio.run(orchestra.run_conversation(conv["id"], []))
    said = _agent_msgs(conv["id"])
    assert [m["agent_name"] for m in said] == ["领头", "产品经理", "领头"]
    assert said[0]["assignments"][0]["task"] == "列出三个核心功能"
    assert said[1]["task"] == "列出三个核心功能"
    assert said[2]["content"].startswith("最终结论")


def test_lead_creates_member_when_team_is_auto(fake):
    settings.update({"team": "auto"})
    try:
        def script(name, system, msgs, opts):
            if name == "领头":
                if "成员已完成" in msgs[-1]["content"]:
                    return "俳句已经写好了。"
                return '<agent name="俳句诗人" description="写俳句">你是俳句诗人，只写俳句。</agent>\n@俳句诗人：写一首关于秋天的俳句'
            return "秋风起 / 落叶飘 / 归雁鸣"
        fake(script)
        p = _provider()
        lead = _agent(p, "领头")
        conv = _conv([lead], mode="lead", lead_id=lead["id"])
        _say(conv["id"], "我需要一个写俳句的")
        asyncio.run(orchestra.run_conversation(conv["id"], []))
        hired = [a for a in store.list_docs("agent") if a["name"] == "俳句诗人"]
        assert len(hired) == 1 and hired[0]["conv_id"] == conv["id"] and "俳句诗人" in hired[0]["system_prompt"]
        assert hired[0]["id"] in store.get_doc("conversation", conv["id"])["agent_ids"]
        assert [m["agent_name"] for m in _agent_msgs(conv["id"])][-2:] == ["俳句诗人", "领头"]
    finally:
        settings.update({"team": "ask"})


def test_local_operation_waits_for_approval_and_deny_is_respected(fake, tmp_path):
    settings.update({"local": {"enabled": True, "approval": "ask", "workspace": str(tmp_path)}})
    try:
        def script(name, system, msgs, opts):
            if "用户拒绝了这次操作" in msgs[-1]["content"]:
                return "好的，那我不执行了。"
            return "我来看看。<run>echo hi</run>"
        fake(script)
        p = _provider()
        a = _agent(p, "助手", no_tools=False)
        conv = _conv([a])
        _say(conv["id"], "看看当前目录")

        async def go():
            task = asyncio.ensure_future(orchestra.run_conversation(conv["id"], []))
            for _ in range(100):  # 等它发出审批请求
                if orchestra.approvals:
                    break
                await asyncio.sleep(0.02)
            assert orchestra.approvals, "应该先请用户确认，而不是直接执行"
            next(iter(orchestra.approvals.values())).set_result("deny")
            await asyncio.wait_for(task, 10)
        asyncio.run(go())
        tool = [m for m in store.list_messages(conv["id"]) if m["role"] == "tool"]
        assert tool[0]["status"] == "denied" and tool[0]["output"] == ""  # 拒绝了就没有执行
        assert _agent_msgs(conv["id"])[-1]["content"] == "好的，那我不执行了。"
    finally:
        settings.update({"local": {"enabled": False}})


def test_output_cap_error_is_retried_with_the_limit_and_remembered(fake):
    def script(name, system, msgs, opts):
        if (opts.get("max_tokens") or 0) > 131072:
            raise providers.ProviderError('HTTP 400：{"message":"max_tokens参数非法：限制数值范围[1,131072]"}')
        return "收到"
    model = fake(script)
    p = _provider()
    a = _agent(p, "甲", max_tokens=200000)
    conv = _conv([a])
    _say(conv["id"], "你好")
    asyncio.run(orchestra.run_conversation(conv["id"], []))
    assert _agent_msgs(conv["id"])[-1]["content"] == "收到" and not _agent_msgs(conv["id"])[-1]["error"]
    assert store.get_doc("provider", p["id"])["out_caps"] == {"fake-1": 131072}
    asyncio.run(orchestra.run_conversation(conv["id"], []))  # 下一次直接压到上限，不再先报错
    assert model.calls[-1]["opts"]["max_tokens"] == 131072


def test_memory_and_usage_are_recorded(fake):
    fake(lambda *_: "好的。<remember>用户的项目代号是青鸟-042</remember>")
    p = _provider()
    a = _agent(p, "甲")
    conv = _conv([a])
    _say(conv["id"], "记一下项目代号")
    asyncio.run(orchestra.run_conversation(conv["id"], []))
    m = _agent_msgs(conv["id"])[-1]
    assert m["content"] == "好的。" and m["memories"][0]["text"] == "用户的项目代号是青鸟-042"
    import usage
    today = usage.usage_summary(1)["today"]
    assert today["calls"] >= 1 and today["cached"] >= 40


# ---------------------------------------------------------------- 原生工具调用
class ToolModel(FakeModel):
    """会返回结构化工具调用的假模型：script 返回 (文字, [调用]) 。"""

    async def stream(self, provider, model, system, msgs, opts=None):
        name = re.search(r"你的名字是「(.+?)」", system).group(1)
        self.calls.append({"name": name, "system": system, "msgs": msgs, "opts": dict(opts or {})})
        text, calls = self.script(name, system, msgs, opts or {})
        if text:
            yield "text", text
        if calls:
            yield "tool_calls", calls
        yield "usage", {"in": 50, "out": 5, "cached": 0}


def test_native_tool_call_runs_through_the_same_approval_and_execution(monkeypatch, tmp_path):
    settings.update({"local": {"enabled": True, "approval": "auto", "workspace": str(tmp_path)}})
    try:
        def script(name, system, msgs, opts):
            if "操作结果" in msgs[-1]["content"]:
                return "文件里写着：你好", []
            return "", [{"name": "write_file", "args": '{"path": "a.txt", "content": "你好"}'}]
        model = ToolModel(script)
        monkeypatch.setattr(providers, "stream", model.stream)
        p = _provider()
        a = _agent(p, "助手", no_tools=False)
        conv = _conv([a])
        _say(conv["id"], "写个文件")
        asyncio.run(orchestra.run_conversation(conv["id"], []))
        assert [t["name"] for t in model.calls[0]["opts"]["tools"]] == ["run_command", "read_file", "write_file"]
        assert "<run>" not in model.calls[0]["system"]  # 原生模式下不再教它写文本标签，省 token
        tool = [m for m in store.list_messages(conv["id"]) if m["role"] == "tool"]
        assert tool[0]["action"]["kind"] == "write" and tool[0]["status"] == "done"
        assert (tmp_path / store.get_doc("conversation", conv["id"])["folder"] / "a.txt").read_text(encoding="utf-8") == "你好"
        said = _agent_msgs(conv["id"])
        assert not said[0]["error"]  # 只调用了工具、没写文字，不算空回复
        assert said[-1]["content"] == "文件里写着：你好"
    finally:
        settings.update({"local": {"enabled": False, "approval": "ask"}})


def test_channel_that_rejects_tools_falls_back_to_text_tags(monkeypatch, tmp_path):
    settings.update({"local": {"enabled": True, "approval": "auto", "workspace": str(tmp_path)}})
    try:
        def script(name, system, msgs, opts):
            if opts.get("tools"):
                raise providers.ProviderError("HTTP 400：tools is not supported by this model")
            return ("好的" if "操作结果" in msgs[-1]["content"] else "<run>echo hi</run>"), []
        model = ToolModel(script)
        monkeypatch.setattr(providers, "stream", model.stream)
        p = _provider()
        a = _agent(p, "助手", no_tools=False)
        conv = _conv([a])
        _say(conv["id"], "跑个命令")
        asyncio.run(orchestra.run_conversation(conv["id"], []))
        assert store.get_doc("provider", p["id"])["native_tools"] is False  # 记住了：这个渠道不用工具参数
        assert "<run>" in model.calls[1]["system"]  # 退回文本标签的说明
        assert [m["status"] for m in store.list_messages(conv["id"]) if m["role"] == "tool"] == ["done"]
        assert not [m for m in _agent_msgs(conv["id"]) if m["error"]]
    finally:
        settings.update({"local": {"enabled": False, "approval": "ask"}})


def test_tool_schemas_follow_permissions_and_map_to_actions():
    import toolcalls
    plain = {"name": "甲", "no_tools": True}
    assert toolcalls.schemas(plain, False) == []  # 什么权限都没有，就不发任何工具（省 token）
    boss = {"name": "管家", "no_tools": True, "manager": True}
    assert {"fetch_url", "add_skill", "add_mcp"} <= {t["name"] for t in toolcalls.schemas(boss, False)}
    assert toolcalls.to_action("run_command", '{"command": "ls"}') == {"kind": "run", "command": "ls"}
    assert toolcalls.to_action("add_skill", {"path": "~/s/demo"}) == {"kind": "skill_add", "path": "~/s/demo"}
    assert toolcalls.to_action("call_mcp", '{"server": "fs", "tool": "list", "arguments": {"dir": "."}}')["args"] == {"dir": "."}
    assert toolcalls.to_action("run_command", "not json") is None and toolcalls.to_action("no_such_tool", "{}") is None


# ---------------------------------------------------------------- 领头分派：成员并行
class SlowModel(FakeModel):
    """每次回复要花一点时间，用来区分并行和依次执行。"""

    def __init__(self, script):
        super().__init__(script)
        self.active_members = 0
        self.peak_members = 0

    async def stream(self, provider, model, system, msgs, opts=None):
        member = "分派给你的任务" in msgs[-1]["content"]
        if member:
            self.active_members += 1
            self.peak_members = max(self.peak_members, self.active_members)
        try:
            await asyncio.sleep(0.4 if member else 0)
            async for chunk in super().stream(provider, model, system, msgs, opts):
                yield chunk
        finally:
            if member:
                self.active_members -= 1


def _lead_team(parallel):
    def script(name, system, msgs, opts):
        last = msgs[-1]["content"]
        if name == "领头":
            return "汇总完毕。" if "成员已完成" in last else "@产品：写需求\n@设计：画草图\n@测试：列用例"
        return "%s 交付了" % name
    p = _provider()
    lead = _agent(p, "领头")
    members = [_agent(p, n) for n in ("产品", "设计", "测试")]
    conv = _conv([lead] + members, mode="lead", lead_id=lead["id"], lead_parallel=parallel)
    _say(conv["id"], "开工")
    return script, conv


def test_lead_assignments_run_in_parallel_by_default(monkeypatch):
    script, conv = _lead_team(True)
    model = SlowModel(script)
    monkeypatch.setattr(providers, "stream", model.stream)
    asyncio.run(orchestra.run_conversation(conv["id"], []))
    said = _agent_msgs(conv["id"])
    members = [m for m in said if m.get("task")]
    assert sorted(m["agent_name"] for m in members) == ["产品", "测试", "设计"]
    assert model.peak_members == 3  # Check overlap directly, independent of CI speed.
    assert len({m["batch"] for m in members}) == 1 and members[0]["batch"]  # 同一批，界面并排显示
    member_calls = [c for c in model.calls if c["name"] != "领头"]
    assert all("交付了" not in m["content"] for c in member_calls for m in c["msgs"])  # 成员之间互相看不到
    assert said[-1]["agent_name"] == "领头" and said[-1]["content"] == "汇总完毕。"  # 全部交付后领头人统一审阅
    assert "同时开工" in model.calls[0]["system"]  # 领头人知道成员是并行的


def test_lead_can_run_assignments_one_by_one(monkeypatch):
    script, conv = _lead_team(False)
    model = SlowModel(script)
    monkeypatch.setattr(providers, "stream", model.stream)
    asyncio.run(orchestra.run_conversation(conv["id"], []))
    assert model.peak_members == 1
    members = [m for m in _agent_msgs(conv["id"]) if m.get("task")]
    assert [m["agent_name"] for m in members] == ["产品", "设计", "测试"] and not members[0]["batch"]
    later = [c for c in model.calls if c["name"] == "测试"][0]
    assert any("产品 交付了" in m["content"] for m in later["msgs"])  # 依次做时，后面的能看到前面的结果


# ---------------------------------------------------------------- 单独停止 / 重做某位成员；重启后接着做
def test_stop_one_member_others_continue_then_retry_it(monkeypatch):
    script, conv = _lead_team(True)
    model = SlowModel(script)
    monkeypatch.setattr(providers, "stream", model.stream)
    design = next(a for a in store.list_docs("agent") if a["name"] == "设计")

    async def go():
        task = asyncio.ensure_future(orchestra.run_conversation(conv["id"], []))
        for _ in range(100):
            if design["id"] in (orchestra.member_tasks.get(conv["id"]) or {}):
                break
            await asyncio.sleep(0.02)
        assert orchestra.stop_member(conv["id"], design["id"])
        await task
    asyncio.run(go())
    members = {m["agent_name"]: m for m in _agent_msgs(conv["id"]) if m.get("task")}
    assert members["设计"]["error"] == "已停止"
    assert members["产品"]["content"] == "产品 交付了" and members["测试"]["content"] == "测试 交付了"  # 其他人照常交付
    assert _agent_msgs(conv["id"])[-1]["agent_name"] == "领头"  # 领头人照常审阅

    batch = members["设计"]["batch"]
    asyncio.run(orchestra.retry_member(conv["id"], design["id"], batch))
    redo = [m for m in _agent_msgs(conv["id"]) if m["agent_name"] == "设计"]
    assert redo[-1]["content"] == "设计 交付了" and redo[-1]["batch"] == batch and redo[-1]["task"] == "画草图"


def test_interrupted_run_is_flagged_after_restart_and_cleared_when_continued(fake):
    fake(lambda *_: "接着做完了")
    p = _provider()
    a = _agent(p, "甲")
    conv = _conv([a])
    _say(conv["id"], "做点事")
    store.save_message({"id": store.new_id(), "conv_id": conv["id"], "role": "tool", "agent_id": a["id"], "agent_name": "甲",
                        "action": {"kind": "run", "command": "ls"}, "status": "running", "output": "", "created": time.time()})
    orchestra.mark_run(conv["id"], since=time.time())  # 假装服务在跑到一半时被关掉了
    assert orchestra.recover_interrupted() == [conv["id"]]
    assert orchestra.interrupted_ids() == [conv["id"]]
    msgs = store.list_messages(conv["id"])
    assert [m for m in msgs if m["role"] == "tool"][0]["status"] == "cancelled"
    assert any(m["role"] == "notice" and "被打断" in m["content"] for m in msgs)
    assert orchestra.recover_interrupted() == []  # 再启动一次不会重复提示
    asyncio.run(orchestra.run_conversation(conv["id"], []))  # 用户点「继续」
    assert orchestra.interrupted_ids() == [] and _agent_msgs(conv["id"])[-1]["content"] == "接着做完了"
