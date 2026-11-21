"""消息附件：上传、只认本会话文件、拼进上下文时省 token、模型不支持看图时自动降级。"""
import asyncio
import base64
import os
import shutil

import pytest
from fastapi.testclient import TestClient

import attachments
import config
import context
import main
import providers
import store

LOCAL = TestClient(main.app, client=("127.0.0.1", 50000))


@pytest.fixture(autouse=True)
def tidy_workspace():
    """测试建的会话文件夹用完就删，别影响其他测试（工作区是临时目录，不是你的）。"""
    ws = config.LOCAL["workspace"]
    before = set(os.listdir(ws)) if os.path.isdir(ws) else set()
    yield
    for name in set(os.listdir(ws)) - before if os.path.isdir(ws) else ():
        shutil.rmtree(os.path.join(ws, name), ignore_errors=True)
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _conv():
    me = store.put_doc("agent", {"name": "甲", "no_tools": True})
    conv = LOCAL.post("/api/conversations", json={"agent_ids": [me["id"]]}).json()
    return me, store.get_doc("conversation", conv["id"])


def _up(cid, name, data):
    return LOCAL.post("/api/conversations/%s/attachments" % cid, params={"name": name}, content=data)


def test_upload_detects_kind_and_never_overwrites():
    _, conv = _conv()
    a = _up(conv["id"], "笔记.md", "# 标题\n内容".encode()).json()
    assert a["kind"] == "text" and a["path"] == "attachments/笔记.md"
    b = _up(conv["id"], "笔记.md", b"second").json()
    assert b["path"] == "attachments/笔记-2.md"
    assert _up(conv["id"], "图.png", PNG).json()["kind"] == "image"
    assert _up(conv["id"], "x.zip", b"PK\x03\x04").json()["kind"] == "file"
    # 名字里带路径也只取文件名，写不出会话文件夹
    assert _up(conv["id"], "../../evil.txt", b"hi").json()["path"] == "attachments/evil.txt"
    assert _up(conv["id"], "empty.txt", b"").status_code == 400


def test_clean_only_accepts_this_conversations_files():
    _, conv = _conv()
    _up(conv["id"], "a.txt", b"hello")
    ok = attachments.clean(conv, [{"path": "attachments/a.txt"}, {"path": "attachments/../../a.txt"}, {"path": "../a.txt"}, "attachments/missing.txt"])
    assert [x["path"] for x in ok] == ["attachments/a.txt"]


def test_latest_message_gets_full_text_and_images_older_only_a_pointer():
    me, conv = _conv()
    doc = _up(conv["id"], "报告.txt", ("正文" * 2000).encode()).json()
    pic = _up(conv["id"], "图.png", PNG).json()
    history = [
        {"role": "user", "content": "先看这个", "attachments": [doc, pic]},
        {"role": "agent", "agent_id": me["id"], "agent_name": "甲", "content": "好的"},
        {"role": "user", "content": "再看一遍", "attachments": [doc]},
    ]
    _, msgs = context.build_context(conv, me, history, thrifty=True)
    assert "images" not in msgs[0]  # 旧消息里的图片不再重复发送
    assert "正文" * 1000 not in msgs[0]["content"] and "attachments/报告.txt" in msgs[0]["content"]
    assert "正文" * 2000 in msgs[-1]["content"]
    _, msgs = context.build_context(conv, me, history[:1], thrifty=True)
    assert msgs[-1]["images"][0]["mime"] == "image/png"


def test_message_with_only_attachments_is_saved():
    me, conv = _conv()
    a = _up(conv["id"], "a.txt", b"hello").json()
    with LOCAL.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": ""})
        ws.receive_json()
        ws.send_json({"type": "send", "conv_id": conv["id"], "content": "", "attachments": [a, {"path": "../../etc/passwd"}]})
        for _ in range(10):
            ev = ws.receive_json()
            if ev.get("type") == "message":
                break
    assert ev["message"]["attachments"] == [a]
    main._stop(conv["id"])


def test_images_fall_back_to_text_when_model_cannot_see():
    seen = []

    async def fake(p, model, system, messages, opts):
        seen.append(messages)
        if providers.has_images(messages):
            raise providers.ProviderError("model does not support image input", 400)
        yield "text", "ok"

    providers._STREAMS["fake"] = fake
    try:
        msgs = [{"role": "user", "content": "看图", "images": [{"mime": "image/png", "data": "x", "name": "图.png"}]}]

        async def run():
            return [c async for c in providers.stream({"protocol": "fake", "id": "p1"}, "m", "", msgs)]

        assert asyncio.run(run()) == [("text", "ok")]
        assert "不支持看图" in seen[-1][0]["content"]
        seen.clear()
        asyncio.run(run())  # 记住了：第二次直接发文字，不再先失败一次
        assert len(seen) == 1
    finally:
        providers._STREAMS.pop("fake")
        providers._NO_VISION.clear()


def test_provider_formats_for_images():
    m = [{"role": "user", "content": "看", "images": [{"mime": "image/png", "data": "QQ==", "name": "a"}]}]
    assert providers._with_images(m, "openai")[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,QQ=="
    assert providers._with_images(m, "anthropic")[0]["content"][0]["source"]["data"] == "QQ=="
    assert providers._with_images(m, "ollama")[0]["images"] == ["QQ=="]
    assert "images" not in providers._with_images([{"role": "user", "content": "x"}], "openai")[0]
