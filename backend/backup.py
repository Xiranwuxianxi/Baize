"""备份与恢复：把全部数据（渠道、智能体、会话、记忆、经验、用量、设置）打成一个 zip，换电脑或升级前留一份。

导出用 SQLite 的在线备份接口拿到一致的快照（不用停服务）；恢复时先把当前数据库另存一份，
再把备份内容原地拷进正在使用的数据库，不需要重启。
备份里含有渠道密钥，和 data/ 目录一样要当密码文件对待。
"""
import io
import json
import os
import sqlite3
import tempfile
import time
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

import config
import settings
import store
from common import _ADMIN_ONLY, can_admin
from hub import broadcast

router = APIRouter()

MAX_UPLOAD = 500 * 1024 * 1024  # 恢复时最多接受 500 MB 的备份


def _snapshot() -> bytes:
    """当前数据库的一致快照（字节）。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dst = sqlite3.connect(path)
        with store._lock:
            store._db.backup(dst)
        dst.close()
        return open(path, "rb").read()
    finally:
        os.remove(path)


def make_zip(include_workspace: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mac.db", _snapshot())
        version = open(os.path.join(config.ROOT, "VERSION"), encoding="utf-8").read().strip()
        z.writestr("manifest.json", json.dumps({"app": "baize", "version": version, "created": time.time(),
                                                "workspace": include_workspace}, ensure_ascii=False))
        if include_workspace:
            root = config.LOCAL["workspace"]
            for dirpath, dirnames, files in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in ("_bin", "node_modules", ".git", ".venv", "__pycache__")]
                for f in files:
                    full = os.path.join(dirpath, f)
                    z.write(full, "workspace/" + os.path.relpath(full, root).replace("\\", "/"))
    return buf.getvalue()


def restore_zip(data: bytes) -> dict:
    """校验备份，另存当前数据库，再把备份内容拷进正在使用的数据库。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        raw = z.read("mac.db")
        manifest = json.loads(z.read("manifest.json").decode("utf-8")) if "manifest.json" in z.namelist() else {}
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise HTTPException(400, "这不是本程序导出的备份文件（缺少 mac.db）")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(raw)
        src = sqlite3.connect(path)
        try:
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"docs", "messages"} <= tables:
                raise HTTPException(400, "备份里的数据库不完整，没有恢复")
            keep = os.path.join(store.DATA_DIR, "before-restore-%s.db" % time.strftime("%Y%m%d-%H%M%S"))
            dst = sqlite3.connect(keep)
            with store._lock:
                store._db.backup(dst)   # 先把现在的数据另存一份，恢复错了还能找回
                dst.close()
                src.backup(store._db)   # 原地替换：正在用的连接直接看到备份里的数据
        finally:
            src.close()
    except sqlite3.DatabaseError:
        raise HTTPException(400, "备份里的数据库已损坏，没有恢复")
    finally:
        os.remove(path)
    settings.apply()
    files = _restore_workspace(z)
    return {"ok": True, "version": manifest.get("version", ""), "created": manifest.get("created"),
            "saved_current_as": os.path.basename(keep), "workspace_files": files}


def _restore_workspace(z: zipfile.ZipFile) -> int:
    """备份里带了工作区文件就放回去（同名覆盖）；任何跳出工作区的路径一律跳过。"""
    root = os.path.realpath(config.LOCAL["workspace"])
    n = 0
    for name in z.namelist():
        if not name.startswith("workspace/") or name.endswith("/"):
            continue
        target = os.path.realpath(os.path.join(root, name[len("workspace/"):]))
        if not target.startswith(root + os.sep):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(z.read(name))
        n += 1
    return n


@router.get("/api/backup")
def download_backup(request: Request, workspace: bool = False):
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    name = "baize-backup-%s.zip" % time.strftime("%Y%m%d-%H%M%S")
    return Response(make_zip(workspace), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@router.post("/api/backup/restore")
async def restore_backup(request: Request):
    if not can_admin(request):
        raise HTTPException(403, _ADMIN_ONLY)
    data = await request.body()
    if not data:
        raise HTTPException(400, "没有收到备份文件")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "备份文件太大")
    result = restore_zip(data)
    await broadcast({"type": "refresh"})
    return result
