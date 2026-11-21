"""接口层的离线测试：访问控制（本机 / 局域网 / 外部智能体口令）、常用增删改。"""
from fastapi.testclient import TestClient

import main

LOCAL = TestClient(main.app, client=("127.0.0.1", 50000))
REMOTE = TestClient(main.app, client=("192.168.1.23", 50000))


def test_lan_is_closed_by_default_but_local_works():
    assert LOCAL.get("/api/state").status_code == 200
    r = REMOTE.get("/api/state")
    assert r.status_code == 403 and "局域网访问没有开启" in r.text


def test_remote_cannot_change_permissions():
    assert REMOTE.put("/api/settings", json={"lan": True}).status_code == 403
    assert LOCAL.put("/api/settings", json={"lan": True}).status_code == 200
    try:
        assert REMOTE.put("/api/settings", json={"local": {"enabled": True}}).status_code == 403
    finally:
        LOCAL.put("/api/settings", json={"lan": False})


def test_external_agent_endpoints_need_their_own_token_only():
    agent = LOCAL.post("/api/agents", json={"name": "远程", "external": True, "ext_kind": "其他", "ext_mode": "poll", "no_tools": True}).json()
    token = agent["ext_token"]
    assert len(token) >= 20
    # 局域网访问关着，外部智能体的连接口仍可用（凭它自己的口令），错误口令被拒
    r = REMOTE.get("/join/" + token)
    assert r.status_code == 200 and "192.168.1.23" not in r.text  # 地址来自请求的 Host，不是客户端
    assert REMOTE.get("/api/ext/%s/next?wait=1" % token).json() == {"task_id": None}
    assert REMOTE.get("/join/not-a-real-token").status_code == 404
    assert REMOTE.get("/api/state").status_code == 403


def test_skill_crud_and_delete():
    sk = LOCAL.post("/api/skills", json={"name": "临时", "instructions": "内容"}).json()
    assert sk["origin"] == "custom"
    assert LOCAL.delete("/api/skills/" + sk["id"]).json() == {"ok": True}
    assert all(k["id"] != sk["id"] for k in LOCAL.get("/api/skills").json()["skills"])


def test_lessons_can_be_edited_up_to_500_chars():
    x = LOCAL.post("/api/lessons", json={"text": "报销金额保留两位小数"}).json()
    long = "规则" * 300
    y = LOCAL.put("/api/lessons/" + x["id"], json={**x, "text": long}).json()
    assert len(y["text"]) == 500
    assert LOCAL.post("/api/lessons", json={"text": "  "}).status_code == 400


def test_open_file_endpoints_are_local_only():
    conv = LOCAL.post("/api/conversations", json={"agent_ids": []}).json()
    assert REMOTE.post("/api/files/open", json={"conv": conv["id"], "path": "a.txt"}).status_code == 403
    # 路径跳出会话文件夹也被拒绝（本机也不行）
    assert LOCAL.post("/api/files/open", json={"conv": conv["id"], "path": "../../x.txt"}).status_code == 403


def test_security_headers_are_sent():
    r = LOCAL.get("/api/state")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_retry_deletes_tail_and_reruns():
    """重新生成：这条回复和它之后的消息都被删掉，同一个智能体收到重跑任务；非智能体消息不能重生。"""
    import store
    agent = LOCAL.post("/api/agents", json={"name": "小测", "no_tools": True}).json()
    conv = LOCAL.post("/api/conversations", json={"agent_ids": [agent["id"]]}).json()
    cid = conv["id"]
    store.save_message({"id": "u1", "conv_id": cid, "role": "user", "content": "你好", "created": 1})
    store.save_message({"id": "a1", "conv_id": cid, "role": "agent", "agent_id": agent["id"], "agent_name": "小测", "content": "旧回复", "created": 2})
    with LOCAL.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": ""})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "retry", "conv_id": cid, "message_id": "u1"})
        assert ws.receive_json()["type"] == "error"  # 用户消息不能重新生成
        ws.send_json({"type": "retry", "conv_id": cid, "message_id": "a1"})
        seen = {}
        for _ in range(6):  # removed / running / 重答的消息事件，顺序不定
            ev = ws.receive_json()
            seen.setdefault(ev["type"], ev)
            if "removed" in seen and "running" in seen:
                break
        assert seen["removed"]["ids"] == ["a1"]
    left = {m["id"] for m in store.list_messages(cid)}
    assert "u1" in left and "a1" not in left


def test_token_only_accepted_in_header_and_brute_force_is_limited():
    import config
    old = config.TOKEN
    LOCAL.put("/api/settings", json={"lan": True})
    config.TOKEN = "s3cret-token"
    try:
        assert REMOTE.get("/api/state", headers={"x-access-token": "s3cret-token"}).status_code == 200
        assert REMOTE.get("/api/state?token=s3cret-token").status_code == 401  # 网址里的口令不再认
        for _ in range(main.FAIL_LIMIT - 1):
            assert REMOTE.get("/api/state", headers={"x-access-token": "wrong"}).status_code == 401
        r = REMOTE.get("/api/state", headers={"x-access-token": "s3cret-token"})
        assert r.status_code == 429 and "Retry-After" in r.headers  # 锁住后连正确口令也要等
        assert any(b["ip"] == "192.168.1.23" for b in LOCAL.get("/api/security/blocked", headers={"x-access-token": "s3cret-token"}).json()["blocked"])
        for _ in range(main.FAIL_LIMIT + 2):  # 本机永远不锁
            LOCAL.get("/api/state", headers={"x-access-token": "wrong"})
        assert LOCAL.get("/api/state", headers={"x-access-token": "s3cret-token"}).status_code == 200
        LOCAL.post("/api/security/unblock", json={"ip": "192.168.1.23"}, headers={"x-access-token": "s3cret-token"})
        assert REMOTE.get("/api/state", headers={"x-access-token": "s3cret-token"}).status_code == 200
    finally:
        config.TOKEN = old
        main._blocked.clear()
        main._failures.clear()
        LOCAL.put("/api/settings", json={"lan": False})
        assert LOCAL.get("/api/settings").json()["lan"] is False
