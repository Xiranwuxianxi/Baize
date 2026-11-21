"""会话文件夹：每个会话的工作目录，以及在浏览器里查看 / 用本机应用打开 / 在文件夹中显示。"""
import mimetypes
import os
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse

import config
import desktop
import store
import tools

from common import _need, _s, is_local

router = APIRouter()

# ------------------------------------------------------------------ 会话文件夹
def clean_folders(value: Any) -> List[str]:
    """会话额外可以操作的文件夹：只保留确实存在的绝对路径。"""
    out: List[str] = []
    for item in value if isinstance(value, list) else []:
        path = os.path.abspath(os.path.expanduser(str(item or "").strip().strip('"')))
        if os.path.isdir(path) and path not in out:
            out.append(path)
    return out[:20]


def conv_dirs(conv: Dict[str, Any], create: bool = False):
    """（这个会话自己的文件夹，[用户额外允许的文件夹]）。

    每个会话在工作区下有一个专属文件夹，名字在第一次用到时定下来，之后改标题也不变。
    """
    folder = conv.get("folder")
    if not folder:
        title = re.sub(r'[\\/:*?"<>|\s.]+', "-", conv.get("title") or "").strip("-")[:24]
        folder = ((title + "-") if title and title != "新会话" else "会话-") + conv["id"][:4]
        if create:
            fresh = store.get_doc("conversation", conv["id"])
            if fresh is not None:
                fresh["folder"] = folder
                store.put_doc("conversation", fresh, conv["id"])
            conv["folder"] = folder
    root = os.path.join(config.LOCAL["workspace"], folder)
    if create:
        os.makedirs(root, exist_ok=True)
    return root, [p for p in conv.get("folders") or [] if os.path.isdir(p)]


@router.get("/api/files")
def open_file(conv: str, path: str):
    """在浏览器里打开会话文件夹（或额外允许的文件夹）里的文件。"""
    doc = _need("conversation", conv)
    root, extra = conv_dirs(doc)
    full = tools.full_path(path, root, extra)
    if not tools.inside(full, [root, *extra]):
        raise HTTPException(403, "这个文件不在本会话可以操作的文件夹里")
    if not os.path.isfile(full):
        raise HTTPException(404, "文件不存在，可能已被移动或删除：%s" % full)
    kind = mimetypes.guess_type(full)[0] or ""
    # 网页类文件按纯文本显示，避免智能体写出的脚本在控制台的页面里执行
    if kind.startswith("text/") or kind in ("application/json", "application/javascript", "application/xml") or not kind:
        kind = "text/plain; charset=utf-8"
    elif kind == "image/svg+xml":
        kind = "text/plain; charset=utf-8"
    return FileResponse(full, media_type=kind, headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"})


def _local_target(request: Request, d: Dict[str, Any]) -> str:
    """要在这台电脑上打开的文件：只限本机浏览器发起、只限本会话可操作的文件夹。"""
    if config.IN_DOCKER or not is_local(request):
        raise HTTPException(403, "只能在运行本程序的这台电脑上打开")
    doc = _need("conversation", _s(d.get("conv"), 40))
    root, extra = conv_dirs(doc, create=True)
    full = tools.full_path(str(d.get("path") or "."), root, extra)
    if not tools.inside(full, [root, *extra]):
        raise HTTPException(403, "这个位置不在本会话可以操作的文件夹里")
    if not os.path.exists(full):
        raise HTTPException(404, "文件不存在，可能已被移动或删除：%s" % full)
    return full


@router.post("/api/files/reveal")
def reveal_file(request: Request, d: Dict[str, Any] = Body(...)):
    """在这台电脑的文件管理器里打开所在文件夹并选中这个文件，窗口切到最前面。"""
    full = _local_target(request, d)
    try:
        return {"ok": True, "path": full, "message": desktop.reveal(full)}
    except Exception as e:
        raise HTTPException(500, "打不开文件夹：%s" % e)


@router.post("/api/files/open")
def open_local_file(request: Request, d: Dict[str, Any] = Body(...)):
    """用这台电脑上对应的应用打开文件（Word、Excel、图片查看器……），窗口切到最前面。"""
    full = _local_target(request, d)
    try:
        return {"ok": True, "path": full, "message": desktop.open_file(full)}
    except Exception as e:
        raise HTTPException(500, "打不开文件：%s" % e)
