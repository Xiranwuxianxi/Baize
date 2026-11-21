"""SQLite 持久化：渠道 / 智能体 / 会话 存为 JSON 文档，消息单独成表。"""
import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import config  # noqa: E402  决定数据放在哪（默认在用户数据目录，不在项目文件夹里）

DATA_DIR = config.DATA_DIR
os.makedirs(DATA_DIR, exist_ok=True)

_lock = threading.Lock()
DB_PATH = os.path.abspath(os.path.join(DATA_DIR, "mac.db"))
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
# WAL：读写互不阻塞，多个智能体并行落库时更稳；忙等待避免偶发 database is locked
_db.execute("PRAGMA journal_mode=WAL")
_db.execute("PRAGMA busy_timeout=5000")
_db.executescript(
    """
    CREATE TABLE IF NOT EXISTS docs (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS docs_kind ON docs(kind, created);
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY, conv_id TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv_id, created);
    """
)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _doc(row: sqlite3.Row) -> Dict[str, Any]:
    d = json.loads(row["data"])
    d["id"] = row["id"]
    d["created"] = row["created"]
    return d


def list_docs(kind: str) -> List[Dict[str, Any]]:
    with _lock:
        rows = _db.execute(
            "SELECT * FROM docs WHERE kind=? ORDER BY created", (kind,)
        ).fetchall()
    return [_doc(r) for r in rows]


def get_doc(kind: str, doc_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        row = _db.execute(
            "SELECT * FROM docs WHERE kind=? AND id=?", (kind, doc_id)
        ).fetchone()
    return _doc(row) if row else None


def put_doc(kind: str, data: Dict[str, Any], doc_id: Optional[str] = None) -> Dict[str, Any]:
    body = {k: v for k, v in data.items() if k not in ("id", "created")}
    with _lock:
        if doc_id:
            _db.execute(
                "UPDATE docs SET data=? WHERE kind=? AND id=?",
                (json.dumps(body, ensure_ascii=False), kind, doc_id),
            )
        else:
            doc_id = new_id()
            _db.execute(
                "INSERT INTO docs(id, kind, data, created) VALUES(?,?,?,?)",
                (doc_id, kind, json.dumps(body, ensure_ascii=False), time.time()),
            )
        _db.commit()
    return get_doc(kind, doc_id)  # type: ignore[return-value]


def set_doc(kind: str, doc_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """按指定 id 写入（不存在则创建，存在则覆盖并保留创建时间）。用于配置文件声明的对象。"""
    body = json.dumps({k: v for k, v in data.items() if k not in ("id", "created")}, ensure_ascii=False)
    with _lock:
        # 只更新同一类的文档；id 撞上别的类会在下面插入时报错，而不是悄悄把那份文档改成这一类
        cur = _db.execute("UPDATE docs SET data=? WHERE id=? AND kind=?", (body, doc_id, kind))
        if cur.rowcount == 0:
            _db.execute("INSERT INTO docs(id, kind, data, created) VALUES(?,?,?,?)", (doc_id, kind, body, time.time()))
        _db.commit()
    return get_doc(kind, doc_id)  # type: ignore[return-value]


def delete_doc(kind: str, doc_id: str) -> None:
    with _lock:
        _db.execute("DELETE FROM docs WHERE kind=? AND id=?", (kind, doc_id))
        _db.commit()


def list_messages(conv_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    with _lock:
        if limit:
            rows = _db.execute(
                # 同一时间戳的多条消息（并行智能体常常同一毫秒写完）按插入顺序兜底，否则顺序不定
                "SELECT data FROM messages WHERE conv_id=? ORDER BY created DESC, rowid DESC LIMIT ?",
                (conv_id, limit),
            ).fetchall()[::-1]
        else:
            rows = _db.execute(
                "SELECT data FROM messages WHERE conv_id=? ORDER BY created, rowid", (conv_id,)
            ).fetchall()
    return [json.loads(r["data"]) for r in rows]


def save_message(msg: Dict[str, Any]) -> None:
    with _lock:
        _db.execute(
            "INSERT OR REPLACE INTO messages(id, conv_id, data, created) VALUES(?,?,?,?)",
            (msg["id"], msg["conv_id"], json.dumps(msg, ensure_ascii=False), msg["created"]),
        )
        _db.commit()


def delete_message(msg_id: str) -> None:
    with _lock:
        _db.execute("DELETE FROM messages WHERE id=?", (msg_id,))
        _db.commit()


def clear_messages(conv_id: str) -> None:
    with _lock:
        _db.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        _db.commit()


def search_messages(q: str, limit: int = 400) -> List[Dict[str, Any]]:
    """内容里包含 q 的消息，新的在前（存的是 JSON，调用方会再核对 content 字段）。"""
    like = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    with _lock:
        rows = _db.execute(
            "SELECT data FROM messages WHERE data LIKE ? ESCAPE '!' ORDER BY created DESC, rowid DESC LIMIT ?", (like, limit)
        ).fetchall()
    return [json.loads(r["data"]) for r in rows]


def message_stats() -> Dict[str, Any]:
    """会话 id -> (消息条数, 占用字节, 最后一条的时间)。"""
    with _lock:
        rows = _db.execute("SELECT conv_id, COUNT(*), SUM(LENGTH(data)), MAX(created) FROM messages GROUP BY conv_id").fetchall()
    return {r[0]: (r[1], r[2] or 0, r[3]) for r in rows}


def db_size() -> int:
    return sum(os.path.getsize(DB_PATH + ext) for ext in ("", "-wal", "-shm") if os.path.exists(DB_PATH + ext))


def vacuum() -> None:
    """删除记录后把腾出的空间还给磁盘，避免数据库文件只增不减。"""
    with _lock:
        _db.commit()
        _db.execute("VACUUM")


def cancel_orphaned_actions() -> int:
    """服务重启后，历史里还停在「等待确认 / 执行中」的操作已经没人执行、也没人确认了：
    标成已取消，免得界面上的卡片永远卡着。返回清理的条数。"""
    n = 0
    with _lock:
        rows = _db.execute(
            "SELECT id, data FROM messages WHERE data LIKE '%\"status\": \"pending\"%' OR data LIKE '%\"status\": \"running\"%'"
        ).fetchall()
        for row in rows:
            msg = json.loads(row["data"])
            if msg.get("role") != "tool" or msg.get("status") not in ("pending", "running"):
                continue
            msg["status"] = "cancelled"
            if not msg.get("output"):
                msg["output"] = "服务重启，这次操作没有执行完成。"
            _db.execute("UPDATE messages SET data=? WHERE id=?", (json.dumps(msg, ensure_ascii=False), row["id"]))
            n += 1
        if n:
            _db.commit()
    return n
