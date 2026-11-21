"""离线单元测试：不连任何模型，不碰你的数据（数据目录、工作区都是临时的）。

运行：pip install -r backend/requirements-dev.txt && pytest tests/unit
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="mac-unit-")
os.environ["MAC_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["MAC_WORKSPACE"] = os.path.join(_TMP, "workspace")
os.environ["MAC_CONFIG"] = os.path.join(_TMP, "none.yaml")
os.environ.pop("MAC_TOKEN", None)
os.environ.pop("MAC_LOCAL_ACCESS", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend"))

import pytest  # noqa: E402

import store  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前清空临时库里的数据。"""
    with store._lock:
        store._db.execute("DELETE FROM docs")
        store._db.execute("DELETE FROM messages")
        store._db.commit()
    yield
