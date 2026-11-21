"""存储层的离线测试：WAL、同时间戳消息的排序、重启后孤儿操作的清理。"""
import store


def test_wal_mode_and_busy_timeout_are_enabled():
    assert store._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store._db.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_messages_with_same_timestamp_keep_insert_order():
    ts = 1700000000.0  # 并行智能体常常同一毫秒写完，created 完全相同
    for i in range(3):
        store.save_message({"id": "m%d" % i, "conv_id": "c1", "role": "agent",
                            "content": "第%d条" % i, "created": ts})
    got = [m["content"] for m in store.list_messages("c1")]
    assert got == ["第0条", "第1条", "第2条"]
    got = [m["content"] for m in store.list_messages("c1", limit=2)]
    assert got == ["第1条", "第2条"]  # 限量取最新时同样稳定


def test_orphaned_pending_actions_are_cancelled():
    base = {"conv_id": "c1", "role": "tool", "action": {"kind": "run", "command": "ls"}, "output": ""}
    store.save_message({**base, "id": "t1", "status": "pending", "created": 1})
    store.save_message({**base, "id": "t2", "status": "running", "created": 2})
    store.save_message({**base, "id": "t3", "status": "done", "output": "ok", "created": 3})
    store.save_message({"id": "a1", "conv_id": "c1", "role": "agent", "content": "正常消息", "created": 4})
    assert store.cancel_orphaned_actions() == 2
    msgs = {m["id"]: m for m in store.list_messages("c1")}
    assert msgs["t1"]["status"] == "cancelled" and "重启" in msgs["t1"]["output"]
    assert msgs["t2"]["status"] == "cancelled"
    assert msgs["t3"]["status"] == "done" and msgs["t3"]["output"] == "ok"
    assert msgs["a1"]["content"] == "正常消息"
    assert store.cancel_orphaned_actions() == 0  # 再跑一次没有可清理的
