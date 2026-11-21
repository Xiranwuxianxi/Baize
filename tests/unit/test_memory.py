"""每个智能体自己的记忆：写入、去重、外部智能体不参与、按相关性带进上下文、随智能体删除。"""
from fastapi.testclient import TestClient

import context
import main
import memory
import store

LOCAL = TestClient(main.app, client=("127.0.0.1", 50000))


def _agent(**kw):
    return store.put_doc("agent", {"name": "甲", "no_tools": True, **kw})


def test_remember_tag_is_saved_and_stripped():
    a = _agent()
    msg = {"conv_id": "c1", "created": 1, "content": "好的，按月汇总。\n<remember>用户的记账周期按自然月统计，每月 1 号出报表</remember>"}
    saved = memory.take_memories(msg, a)
    assert [m["text"] for m in saved] == ["用户的记账周期按自然月统计，每月 1 号出报表"]
    assert "<remember>" not in msg["content"] and msg["content"] == "好的，按月汇总。"
    assert [m["agent_id"] for m in memory.agent_memories(a["id"])] == [a["id"]]


def test_similar_memory_updates_instead_of_duplicating():
    a = _agent()
    memory.take_memories({"content": "ok<remember>用户的项目代号是青鸟-042</remember>", "created": 1}, a)
    saved = memory.take_memories({"content": "ok<remember>用户的项目代号是青鸟-042，下个月上线</remember>", "created": 2}, a)
    mems = memory.agent_memories(a["id"])
    assert len(mems) == 1 and "下个月上线" in mems[0]["text"] and saved[0]["updated"]


def test_memories_are_private_to_each_agent():
    a, b = _agent(name="甲"), _agent(name="乙")
    memory.take_memories({"content": "ok<remember>用户喜欢用表格列出对比结果</remember>"}, a)
    conv = {"id": "c1", "agent_ids": [a["id"], b["id"]]}
    sa, _ = context.build_context(conv, a, [{"role": "user", "content": "你好"}], thrifty=True)
    sb, _ = context.build_context(conv, b, [{"role": "user", "content": "你好"}], thrifty=True)
    assert "用户喜欢用表格" in sa and "用户喜欢用表格" not in sb


def test_external_agents_and_disabled_memory_are_skipped():
    ext = _agent(external=True)
    off = _agent(memory=False)
    for ag in (ext, off):
        msg = {"content": "ok<remember>用户住在杭州，周末常出差</remember>"}
        assert memory.take_memories(msg, ag) == [] and "<remember>" not in msg["content"]
        assert memory.memory_note(ag, "杭州") == ("", "")


def test_many_memories_only_relevant_ones_are_sent():
    a = _agent()
    for i in range(30):
        store.put_doc("memory", {"agent_id": a["id"], "text": "第%d条：关于项目 %d 的一些背景说明，比较长的一段话" % (i, i), "updated": i})
    store.put_doc("memory", {"agent_id": a["id"], "text": "用户的发票抬头是杭州青鸟科技有限公司", "updated": 99})
    store.put_doc("memory", {"agent_id": a["id"], "text": "回答一律先给结论再给理由", "pinned": True, "updated": 0})
    stable, dynamic = memory.memory_note(a, "帮我开一张发票，抬头写什么", thrifty=True)
    assert "先给结论" in stable and "发票抬头" not in stable  # 置顶的常驻；其余不进固定部分
    assert "发票抬头" in dynamic and "第3条" not in dynamic   # 只带相关的
    s1, _ = memory.memory_note(a, "今天天气", thrifty=True)
    assert s1 == stable  # 固定部分不随问题变化，接口才能缓存


def test_memory_api_and_cleanup_on_agent_delete():
    a = LOCAL.post("/api/agents", json={"name": "丙", "no_tools": True}).json()
    assert a["memory"] is True
    m = LOCAL.post("/api/agents/%s/memories" % a["id"], json={"text": "用户偏好简洁的回答"}).json()
    LOCAL.put("/api/memories/" + m["id"], json={"text": "用户偏好简洁、带编号的回答", "pinned": True})
    got = LOCAL.get("/api/agents/%s/memories" % a["id"]).json()["memories"]
    assert got[0]["text"] == "用户偏好简洁、带编号的回答" and got[0]["pinned"]
    ext = LOCAL.post("/api/agents", json={"name": "外援", "external": True, "no_tools": True}).json()
    assert LOCAL.post("/api/agents/%s/memories" % ext["id"], json={"text": "x" * 10}).status_code == 400
    LOCAL.delete("/api/agents/" + a["id"])
    assert memory.agent_memories(a["id"]) == []
