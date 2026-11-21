"""备份与恢复：导出的 zip 能原样恢复；恢复前另存当前数据；坏文件和越界路径被拒绝。"""
import io
import os
import zipfile

from fastapi.testclient import TestClient

import config
import main
import store

LOCAL = TestClient(main.app, client=("127.0.0.1", 50000))
REMOTE = TestClient(main.app, client=("192.168.1.23", 50000))


def test_backup_round_trip_and_keeps_current_copy():
    a = store.put_doc("agent", {"name": "备份前的智能体"})
    store.put_doc("memory", {"agent_id": a["id"], "text": "用户的项目代号是青鸟-042"})
    r = LOCAL.get("/api/backup")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "mac.db" in names and "manifest.json" in names

    store.delete_doc("agent", a["id"])  # 之后又改了数据
    store.put_doc("agent", {"name": "备份后新建的"})
    res = LOCAL.post("/api/backup/restore", content=r.content).json()
    agents = [x["name"] for x in store.list_docs("agent")]
    assert "备份前的智能体" in agents and "备份后新建的" not in agents
    assert any(m["text"] == "用户的项目代号是青鸟-042" for m in store.list_docs("memory"))
    assert os.path.exists(os.path.join(store.DATA_DIR, res["saved_current_as"]))  # 恢复前的数据另存了一份


def test_restore_rejects_bad_files_and_remote_devices():
    assert LOCAL.post("/api/backup/restore", content=b"not a zip").status_code == 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mac.db", b"garbage")
    assert LOCAL.post("/api/backup/restore", content=buf.getvalue()).status_code == 400
    assert REMOTE.get("/api/backup").status_code in (403,)


def test_workspace_files_restore_but_never_escape():
    ws = config.LOCAL["workspace"]
    os.makedirs(os.path.join(ws, "会话-a"), exist_ok=True)
    open(os.path.join(ws, "会话-a", "note.txt"), "w", encoding="utf-8").write("你好")
    data = LOCAL.get("/api/backup?workspace=true").content
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as z:
        for n in src.namelist():
            z.writestr(n, src.read(n))
        z.writestr("workspace/../../evil.txt", "x")  # 试图写到工作区外面
    os.remove(os.path.join(ws, "会话-a", "note.txt"))
    res = LOCAL.post("/api/backup/restore", content=buf.getvalue()).json()
    assert open(os.path.join(ws, "会话-a", "note.txt"), encoding="utf-8").read() == "你好"
    assert res["workspace_files"] == 1
    assert not os.path.exists(os.path.join(os.path.dirname(os.path.dirname(ws)), "evil.txt"))
