"""消息附件：用户发的图片和文件存进会话自己的文件夹（attachments/ 下），智能体能看到、本地操作也能读到。

省 token 的做法：
- 文本类文件只在最新那条消息里给全文（有上限）；更早的消息只留文件名、路径和开头一小段。
- 图片只随最新一条用户消息发给模型（浏览器上传前已经缩小）；模型不支持看图时自动改成文字说明。
"""
import base64
import mimetypes
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from common import _need
from files import conv_dirs

router = APIRouter()

FOLDER = "attachments"
MAX_BYTES = 20 * 1024 * 1024   # 单个附件上限
MAX_PER_MESSAGE = 10
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 发给模型的单张图片上限（各家接口大多限制在 5 MB 左右）
TEXT_FULL = 12000     # 最新消息里每个文本附件最多给多少字
TEXT_TOTAL = 30000    # 最新消息里所有文本附件合计最多多少字
TEXT_OLD = 300        # 更早消息里的文本附件只留开头多少字
_BINARY = {".zip", ".rar", ".7z", ".exe", ".dll", ".so", ".dylib", ".bin", ".mp3", ".mp4", ".mov", ".wav", ".avi",
           ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf", ".psd", ".iso", ".dmg", ".gz", ".tar"}


def _safe_name(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/"))
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", base).strip(" .")
    return base[:80] or "附件"


def _folder(conv: Dict[str, Any], create: bool = False) -> str:
    root, _ = conv_dirs(conv, create=create)
    path = os.path.join(root, FOLDER)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def read_text(full: str, limit: int) -> Optional[str]:
    """能当文本读就返回内容（最多 limit 字），二进制文件返回 None。"""
    ext = os.path.splitext(full)[1].lower()
    if ext == ".pdf":
        return _pdf_text(full, limit)
    if ext in _BINARY:
        return None
    with open(full, "rb") as f:
        raw = f.read(limit * 4 + 4)
    if b"\x00" in raw[:4096]:
        return None
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)[:limit]
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")[:limit]  # 截断处正好切在多字节字符中间时


def _pdf_text(full: str, limit: int) -> Optional[str]:
    try:
        from pypdf import PdfReader  # 可选依赖：装了就能读 PDF 的文字
    except ImportError:
        return None
    try:
        out = ""
        for page in PdfReader(full).pages:
            out += (page.extract_text() or "") + "\n"
            if len(out) >= limit:
                break
        return out.strip()[:limit] or None
    except Exception:
        return None


def describe(conv: Dict[str, Any], rel: str) -> Optional[Dict[str, Any]]:
    """核对一个附件（只认本会话 attachments/ 下的文件），返回存进消息里的信息。"""
    name = _safe_name(rel)
    if rel.replace("\\", "/") != FOLDER + "/" + name:
        return None
    full = os.path.join(_folder(conv), name)
    if not os.path.isfile(full):
        return None
    mime = mimetypes.guess_type(full)[0] or "application/octet-stream"
    size = os.path.getsize(full)
    if mime in IMAGE_TYPES:
        kind = "image"
    else:
        kind = "text" if read_text(full, 200) is not None else "file"
    return {"name": name, "path": FOLDER + "/" + name, "kind": kind, "mime": mime, "size": size}


def clean(conv: Dict[str, Any], value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        rel = str((item or {}).get("path") or "") if isinstance(item, dict) else str(item or "")
        info = describe(conv, rel)
        if info and all(x["path"] != info["path"] for x in out):
            out.append(info)
    return out[:MAX_PER_MESSAGE]


@router.post("/api/conversations/{cid}/attachments")
async def upload(cid: str, request: Request, name: str = ""):
    conv = _need("conversation", cid)
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise HTTPException(413, "附件不能超过 20 MB")
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "附件不能超过 20 MB")
    if not data:
        raise HTTPException(400, "文件是空的")
    folder = _folder(conv, create=True)
    base, ext = os.path.splitext(_safe_name(name))
    target, n = base + ext, 1
    while os.path.exists(os.path.join(folder, target)):  # 同名不覆盖，依次加编号
        n += 1
        target = "%s-%d%s" % (base, n, ext)
    with open(os.path.join(folder, target), "wb") as f:
        f.write(data)
    return describe(conv, FOLDER + "/" + target)


# ------------------------------------------------------------------ 拼进上下文
def _size(n: int) -> str:
    return "%.1f MB" % (n / 1048576) if n >= 1048576 else "%d KB" % max(1, n // 1024)


def context_text(conv: Dict[str, Any], items: List[Dict[str, Any]], latest: bool) -> str:
    """附件在对话里的文字部分。latest=True 时给文本全文，否则只给开头。"""
    if not items:
        return ""
    folder = _folder(conv)
    parts, budget = [], TEXT_TOTAL
    for a in items:
        head = "[附件：%s（%s，%s）]" % (a["name"], _size(a.get("size") or 0), a["path"])
        full = os.path.join(folder, _safe_name(a["path"]))
        if a.get("kind") == "text" and os.path.isfile(full):
            limit = min(TEXT_FULL, budget) if latest else TEXT_OLD
            text = (read_text(full, limit + 1) or "") if limit > 0 else ""
            budget -= min(len(text), limit)
            cut = len(text) > limit
            text = text[:limit]
            if text:
                note = "…（内容较长，已截断；需要全文可读取 %s）" % a["path"] if cut else ""
                parts.append("%s\n```\n%s\n```%s" % (head, text, note))
                continue
        elif a.get("kind") == "image":
            head = head[:-1] + "，图片" + ("，见下方" if latest else "") + "]"
        parts.append(head)
    return "\n\n".join(parts)


def images(conv: Dict[str, Any], items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    folder = _folder(conv)
    out = []
    for a in items:
        full = os.path.join(folder, _safe_name(a.get("path") or ""))
        if a.get("kind") != "image" or not os.path.isfile(full) or os.path.getsize(full) > MAX_IMAGE_BYTES:
            continue
        with open(full, "rb") as f:
            out.append({"mime": a["mime"], "data": base64.b64encode(f.read()).decode("ascii"), "name": a["name"]})
    return out

