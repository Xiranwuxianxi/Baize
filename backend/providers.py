"""多协议模型渠道适配层。

每个协议实现两件事：流式对话 stream() 与 拉取模型列表 list_models()。
stream() 统一产出 (kind, text)，kind 为 "text"（正文）或 "think"（思考过程）。
"""
import asyncio
import json
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

PROTOCOLS = [
    {"id": "openai", "name": "OpenAI 兼容 (Chat Completions)",
     "hint": "绝大多数云厂商与本地推理服务：DeepSeek、通义、智谱、LM Studio、vLLM、llama.cpp 等"},
    {"id": "openai_responses", "name": "OpenAI Responses API", "hint": "OpenAI 新版 /responses 接口"},
    {"id": "anthropic", "name": "Anthropic Messages API", "hint": "Claude 系列及兼容该协议的网关"},
    {"id": "gemini", "name": "Google Gemini API", "hint": "generateContent 原生协议"},
    {"id": "ollama", "name": "Ollama 原生 API", "hint": "本机 Ollama 的 /api/chat 接口"},
]

PRESETS = [
    {"name": "Ollama（本地）", "protocol": "ollama", "base_url": "http://localhost:11434", "local": True},
    {"name": "LM Studio（本地）", "protocol": "openai", "base_url": "http://localhost:1234/v1", "local": True},
    {"name": "vLLM / llama.cpp（本地）", "protocol": "openai", "base_url": "http://localhost:8000/v1", "local": True},
    {"name": "OpenAI", "protocol": "openai", "base_url": "https://api.openai.com/v1"},
    {"name": "OpenAI Responses", "protocol": "openai_responses", "base_url": "https://api.openai.com/v1"},
    {"name": "Anthropic Claude", "protocol": "anthropic", "base_url": "https://api.anthropic.com"},
    {"name": "Google Gemini", "protocol": "gemini", "base_url": "https://generativelanguage.googleapis.com"},
    {"name": "DeepSeek", "protocol": "openai", "base_url": "https://api.deepseek.com/v1"},
    {"name": "通义千问", "protocol": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    {"name": "智谱 GLM", "protocol": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    {"name": "Moonshot Kimi", "protocol": "openai", "base_url": "https://api.moonshot.cn/v1"},
    {"name": "硅基流动", "protocol": "openai", "base_url": "https://api.siliconflow.cn/v1"},
    {"name": "OpenRouter", "protocol": "openai", "base_url": "https://openrouter.ai/api/v1"},
]

DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "openai_responses": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "ollama": "http://localhost:11434",
}

DEFAULT_MAX_TOKENS = 8192      # used only where the protocol requires a value (Anthropic)
OLLAMA_DEFAULT_CTX = 8192      # Ollama loads models with 4096 unless told otherwise, which multi-agent chats overflow


def context_length(p: Dict[str, Any]) -> int:
    """Context window we ask Ollama for (0 for protocols where the server decides)."""
    if p.get("protocol") != "ollama":
        return 0
    try:
        return max(2048, min(1048576, int(p.get("num_ctx") or OLLAMA_DEFAULT_CTX)))
    except (TypeError, ValueError):
        return OLLAMA_DEFAULT_CTX


Msg = Dict[str, str]
Chunk = Tuple[str, Any]  # ("text"|"think"|"stop", str) 或 ("usage", {"in","out","cached"})


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status  # HTTP 状态码（0 表示不是 HTTP 层的错误），供重试判断


def _base(p: Dict[str, Any]) -> str:
    base = (p.get("base_url") or DEFAULT_BASE.get(p.get("protocol", ""), "")).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ProviderError("接口地址必须以 http:// 或 https:// 开头")
    return base


def _versioned(base: str, version: str) -> str:
    """接口地址已带版本段（/v1、/v1beta）则原样使用，否则补上。"""
    return base if base.rsplit("/", 1)[-1].startswith("v1") else base + "/" + version


def env_ref(key: str) -> str:
    """密钥写成 env:变量名 时，返回变量名；否则返回空串。"""
    key = (key or "").strip()
    return key[4:].strip() if key.lower().startswith("env:") else ""


def _resolve_key(p: Dict[str, Any]) -> str:
    key = (p.get("api_key") or "").strip()
    name = env_ref(key)
    if not name:
        return key
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProviderError("环境变量 %s 未设置或为空（设置后需重启后端）" % name)
    return value


def _headers(p: Dict[str, Any]) -> Dict[str, str]:
    key = _resolve_key(p)
    proto = p.get("protocol")
    h: Dict[str, str] = {}
    if proto == "anthropic":
        h["anthropic-version"] = "2023-06-01"
        if key:
            h["x-api-key"] = key
    elif proto == "gemini":
        if key:
            h["x-goog-api-key"] = key
    elif key:
        h["Authorization"] = "Bearer " + key
    extra = p.get("extra_headers")
    if isinstance(extra, dict):
        h.update({str(k): str(v) for k, v in extra.items()})
    return h


def _client(read_timeout: float = 600) -> httpx.AsyncClient:
    # 深度思考模型单次思考可能几分钟不吐字，默认读超时要放宽；渠道配置里可用 timeout 覆盖
    return httpx.AsyncClient(timeout=httpx.Timeout(read_timeout, connect=15))


def _timeout(p: Dict[str, Any]) -> float:
    try:
        return max(30.0, float(p.get("timeout") or 600))
    except (TypeError, ValueError):
        return 600.0


async def _check(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        body = (await resp.aread()).decode("utf-8", "replace").strip()[:600]
        raise ProviderError("HTTP %s：%s" % (resp.status_code, body or resp.reason_phrase), status=resp.status_code)


def _err_text(err: Any) -> str:
    if isinstance(err, dict):
        return str(err.get("message") or err)
    return str(err)


async def _sse(resp: httpx.Response) -> AsyncIterator[Dict[str, Any]]:
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            obj = json.loads(data)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


_CAP_HINT = re.compile(r"max[_ ]?(output[_ ]?)?tokens|maxOutputTokens|num_predict|输出.{0,6}(长度|token)|output tokens", re.I)

_UNSUPPORTED_HINT = re.compile(r"unsupport|not supported|does not support|unknown (?:field|parameter|param)|unrecognized|not allowed|不支持|未知参数", re.I)
_PARAM_NAME = re.compile(r"temperature|top_p|top_k|presence_penalty|frequency_penalty|logprobs", re.I)


def unsupported_param(error: str) -> str:
    """报错是「这个模型不认某个请求参数」时，返回参数名（如 temperature），否则空串。

    新版 OpenAI 模型只收默认 temperature、一些本地服务不认 top_p，都是这一类。
    输出上限类的 max_tokens 报错由 output_cap 处理，这里刻意不含它。
    """
    if not error or not _UNSUPPORTED_HINT.search(error):
        return ""
    m = _PARAM_NAME.search(error)
    return m.group(0).lower() if m else ""


def output_cap(error: str, requested: Optional[int]) -> int:
    """接口因为「最大输出 token」超出范围而报错时，从报错里读出允许的上限。读不出就返回 0。

    各家写法不同：智谱「限制数值范围[1,131072]」、Anthropic「max_tokens: 200000 > 64000」、
    OpenAI「must be less than or equal to 16384」。规则：报错提到输出 token，取其中小于请求值的最大数字。
    """
    if not requested or not _CAP_HINT.search(error or ""):
        return 0
    nums = [int(n) for n in re.findall(r"\d{3,7}", error.replace(",", " ")) if 256 <= int(n) < requested]
    return max(nums) if nums else 0


def _usage(tin: Any, tout: Any, cached: Any) -> Dict[str, int]:
    """统一的用量：输入、输出、其中命中缓存的输入（各家都比正常输入便宜很多）。"""
    return {"in": int(tin or 0), "out": int(tout or 0), "cached": int(cached or 0)}



# ---------------------------------------------------------------- 图片（多模态）
# 上下文里的消息是 {"role", "content", "images": [{"mime", "data"(base64), "name"}]}，各家格式在这里转换
def _with_images(messages: List[Msg], style: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in messages:
        imgs = m.get("images") or []
        if not imgs:
            out.append({"role": m["role"], "content": m["content"]})
        elif style == "openai":
            out.append({"role": m["role"], "content": [{"type": "text", "text": m["content"]}] + [
                {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (i["mime"], i["data"])}} for i in imgs]})
        elif style == "responses":
            out.append({"role": m["role"], "content": [{"type": "input_text", "text": m["content"]}] + [
                {"type": "input_image", "image_url": "data:%s;base64,%s" % (i["mime"], i["data"])} for i in imgs]})
        elif style == "anthropic":
            out.append({"role": m["role"], "content": [
                {"type": "image", "source": {"type": "base64", "media_type": i["mime"], "data": i["data"]}} for i in imgs
            ] + [{"type": "text", "text": m["content"]}]})
        else:  # ollama
            out.append({"role": m["role"], "content": m["content"], "images": [i["data"] for i in imgs]})
    return out


def _without_images(messages: List[Msg]) -> List[Msg]:
    """模型不支持看图时：图片换成一句说明，让它如实告诉用户。"""
    out = []
    for m in messages:
        if m.get("images"):
            names = "、".join(i.get("name") or "图片" for i in m["images"])
            m = {"role": m["role"], "content": m["content"] + "\n\n（系统说明：用户附了图片 %s，但当前模型不支持看图，请如实告诉用户，可以建议换一个支持图片的模型。）" % names}
        out.append(m)
    return out


_NO_VISION: set = set()  # 试过不支持图片的（渠道, 模型），之后直接改成文字说明，不再白白失败一次


def has_images(messages: List[Msg]) -> bool:
    return any(m.get("images") for m in messages)


# ---------------------------------------------------------------- OpenAI 兼容
async def _openai_chat(p, model, system, messages, opts) -> AsyncIterator[Chunk]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else []) + _with_images(messages, "openai"),
        "stream": True,
    }
    if "api.openai.com" in _base(p):  # 官方接口要显式要求才返回用量；兼容接口大多默认就带
        body["stream_options"] = {"include_usage": True}
    if opts.get("temperature") is not None:
        body["temperature"] = opts["temperature"]
    if opts.get("max_tokens"):
        body["max_tokens"] = opts["max_tokens"]
    if opts.get("tools"):  # 原生工具调用（OpenAI function calling 格式，智谱等兼容接口同样支持）
        body["tools"] = [{"type": "function", "function": t} for t in opts["tools"]]
        body["tool_choice"] = "auto"
    calls: Dict[int, Dict[str, str]] = {}  # 流式返回的工具调用是一段段拼起来的
    async with _client(_timeout(p)) as c:
        async with c.stream("POST", _base(p) + "/chat/completions", headers=_headers(p), json=body) as r:
            await _check(r)
            async for ev in _sse(r):
                if ev.get("error"):
                    raise ProviderError(_err_text(ev["error"]))
                u = ev.get("usage")
                if isinstance(u, dict) and u.get("prompt_tokens"):
                    yield "usage", _usage(u.get("prompt_tokens"), u.get("completion_tokens"),
                                          (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("prompt_cache_hit_tokens"))
                for choice in ev.get("choices") or []:
                    delta = choice.get("delta") or {}
                    think = delta.get("reasoning_content") or delta.get("reasoning")
                    if isinstance(think, str) and think:
                        yield "think", think
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        yield "text", text
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(int(tc.get("index") or 0), {"name": "", "args": ""})
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["args"] += fn.get("arguments") or ""
                    if choice.get("finish_reason") == "length":
                        yield "stop", "length"
    if calls:
        yield "tool_calls", [calls[i] for i in sorted(calls) if calls[i]["name"]]


async def _openai_responses(p, model, system, messages, opts) -> AsyncIterator[Chunk]:
    body: Dict[str, Any] = {"model": model, "input": _with_images(messages, "responses"), "stream": True}
    if system:
        body["instructions"] = system
    if opts.get("temperature") is not None:
        body["temperature"] = opts["temperature"]
    if opts.get("max_tokens"):
        body["max_output_tokens"] = opts["max_tokens"]
    async with _client(_timeout(p)) as c:
        async with c.stream("POST", _base(p) + "/responses", headers=_headers(p), json=body) as r:
            await _check(r)
            async for ev in _sse(r):
                t = ev.get("type", "")
                if t == "response.output_text.delta":
                    if ev.get("delta"):
                        yield "text", ev["delta"]
                elif t in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
                    if ev.get("delta"):
                        yield "think", ev["delta"]
                elif t == "error":
                    raise ProviderError(_err_text(ev.get("error") or ev.get("message") or ev))
                elif t in ("response.completed", "response.incomplete"):
                    u = (ev.get("response") or {}).get("usage") or {}
                    if u.get("input_tokens"):
                        yield "usage", _usage(u["input_tokens"], u.get("output_tokens"), (u.get("input_tokens_details") or {}).get("cached_tokens"))
                    if t == "response.incomplete":
                        yield "stop", "length"
                elif t == "response.failed":
                    raise ProviderError(_err_text((ev.get("response") or {}).get("error") or "请求失败"))


# ---------------------------------------------------------------- Anthropic
async def _anthropic(p, model, system, messages, opts) -> AsyncIterator[Chunk]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": _with_images(messages, "anthropic"),
        "max_tokens": opts.get("max_tokens") or DEFAULT_MAX_TOKENS,
        "stream": True,
    }
    if system:
        body["system"] = system
    if opts.get("temperature") is not None:
        body["temperature"] = opts["temperature"]
    if opts.get("tools"):  # 原生工具调用（Anthropic tool use 格式）
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in opts["tools"]]
    url = _versioned(_base(p), "v1") + "/messages"
    calls: Dict[int, Dict[str, str]] = {}  # 每个 tool_use 块的名字和一段段流式返回的 JSON 参数
    async with _client(_timeout(p)) as c:
        async with c.stream("POST", url, headers=_headers(p), json=body) as r:
            await _check(r)
            got: Dict[str, int] = {}
            async for ev in _sse(r):
                t = ev.get("type")
                if t == "message_start":
                    u = (ev.get("message") or {}).get("usage") or {}
                    got = {"in": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0),
                           "cached": u.get("cache_read_input_tokens") or 0}
                if t == "message_delta" and (ev.get("usage") or {}).get("output_tokens") and got:
                    yield "usage", _usage(got["in"], ev["usage"]["output_tokens"], got["cached"])
                if t == "content_block_start" and (ev.get("content_block") or {}).get("type") == "tool_use":
                    block = ev["content_block"]
                    calls[int(ev.get("index") or 0)] = {"name": block.get("name") or "", "args": json.dumps(block["input"]) if block.get("input") else ""}
                if t == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield "text", delta["text"]
                    elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                        yield "think", delta["thinking"]
                    elif delta.get("type") == "input_json_delta" and int(ev.get("index") or 0) in calls:
                        slot = calls[int(ev.get("index") or 0)]
                        slot["args"] = ("" if slot["args"] == "{}" else slot["args"]) + (delta.get("partial_json") or "")
                elif t == "message_delta" and (ev.get("delta") or {}).get("stop_reason") == "max_tokens":
                    yield "stop", "length"
                elif t == "error":
                    raise ProviderError(_err_text(ev.get("error")))
    if calls:
        yield "tool_calls", [calls[i] for i in sorted(calls) if calls[i]["name"]]


# ---------------------------------------------------------------- Gemini
async def _gemini(p, model, system, messages, opts) -> AsyncIterator[Chunk]:
    body: Dict[str, Any] = {
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user",
             "parts": [{"inline_data": {"mime_type": i["mime"], "data": i["data"]}} for i in m.get("images") or []] + [{"text": m["content"]}]}
            for m in messages
        ]
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    cfg: Dict[str, Any] = {}
    if opts.get("temperature") is not None:
        cfg["temperature"] = opts["temperature"]
    if opts.get("max_tokens"):
        cfg["maxOutputTokens"] = opts["max_tokens"]
    if cfg:
        body["generationConfig"] = cfg
    name = model if model.startswith("models/") else "models/" + model
    url = "%s/%s:streamGenerateContent?alt=sse" % (_versioned(_base(p), "v1beta"), name)
    async with _client(_timeout(p)) as c:
        async with c.stream("POST", url, headers=_headers(p), json=body) as r:
            await _check(r)
            async for ev in _sse(r):
                if ev.get("error"):
                    raise ProviderError(_err_text(ev["error"]))
                u = ev.get("usageMetadata") or {}
                if u.get("promptTokenCount") and (ev.get("candidates") or [{}])[0].get("finishReason"):
                    yield "usage", _usage(u["promptTokenCount"], (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0), u.get("cachedContentTokenCount"))
                for cand in ev.get("candidates") or []:
                    for part in (cand.get("content") or {}).get("parts") or []:
                        if part.get("text"):
                            yield ("think" if part.get("thought") else "text"), part["text"]
                    if cand.get("finishReason") == "MAX_TOKENS":
                        yield "stop", "length"


# ---------------------------------------------------------------- Ollama 原生
async def _ollama(p, model, system, messages, opts) -> AsyncIterator[Chunk]:
    body: Dict[str, Any] = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else []) + _with_images(messages, "ollama"),
        "stream": True,
    }
    options: Dict[str, Any] = {"num_ctx": context_length(p)}
    if opts.get("temperature") is not None:
        options["temperature"] = opts["temperature"]
    if opts.get("max_tokens"):
        options["num_predict"] = opts["max_tokens"]
    body["options"] = options
    body["keep_alive"] = "30m"  # 默认 5 分钟不用就卸载，下次要重新加载几十秒
    if opts.get("think") is False:
        body["think"] = False
    async with _client(_timeout(p)) as c:
        async with c.stream("POST", _base(p) + "/api/chat", headers=_headers(p), json=body) as r:
            await _check(r)
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("error"):
                    raise ProviderError(_err_text(ev["error"]))
                msg = ev.get("message") or {}
                if msg.get("thinking"):
                    yield "think", msg["thinking"]
                if msg.get("content"):
                    yield "text", msg["content"]
                if ev.get("done") and ev.get("prompt_eval_count"):
                    yield "usage", _usage(ev["prompt_eval_count"], ev.get("eval_count"), 0)
                if ev.get("done") and ev.get("done_reason") == "length":
                    yield "stop", "length"


_STREAMS = {
    "openai": _openai_chat,
    "openai_responses": _openai_responses,
    "anthropic": _anthropic,
    "gemini": _gemini,
    "ollama": _ollama,
}


def _friendly(e: Exception, p: Dict[str, Any]) -> ProviderError:
    if isinstance(e, ProviderError):
        return e
    if isinstance(e, httpx.ConnectError):
        return ProviderError("无法连接到 %s，请确认地址正确、服务已启动" % (p.get("base_url") or "接口"))
    if isinstance(e, httpx.TimeoutException):
        return ProviderError("请求超时")
    return ProviderError("%s: %s" % (type(e).__name__, e))


_TRANSIENT_STATUS = (429, 500, 502, 503, 504)  # 限流和服务端抖动：还没产出内容时值得重试
_BACKOFF = (1.0, 2.0)  # 第 1、2 次重试前等几秒（最多试 3 次）


async def stream(
    p: Dict[str, Any], model: str, system: str, messages: List[Msg], opts: Optional[Dict[str, Any]] = None
) -> AsyncIterator[Chunk]:
    fn = _STREAMS.get(p.get("protocol", ""))
    if not fn:
        raise ProviderError("不支持的协议：%s" % p.get("protocol"))
    if not model:
        raise ProviderError("未指定模型")
    vision_key = (p.get("id") or p.get("base_url") or "", model)
    if has_images(messages) and vision_key in _NO_VISION:
        messages = _without_images(messages)
    for attempt in range(1 + len(_BACKOFF)):
        produced = False  # 一旦吐过内容就不再重试：重发会重复计费、重复输出
        try:
            async for chunk in fn(p, model, system, messages, opts or {}):
                produced = True
                yield chunk
            return
        except ProviderError as e:
            if not produced and has_images(messages) and e.status in (0, 400, 404, 415, 422):
                # 带图请求被拒（多半是模型不支持看图）：记下来，改成文字说明再发一次
                _NO_VISION.add(vision_key)
                messages = _without_images(messages)
                continue
            if produced or e.status not in _TRANSIENT_STATUS or attempt >= len(_BACKOFF):
                raise
        except (httpx.HTTPError, ValueError) as e:
            # 连接失败、超时、对端断开等：还没收到一个字时的网络抖动，退避后重试
            if produced or attempt >= len(_BACKOFF):
                raise _friendly(e, p)
        await asyncio.sleep(_BACKOFF[attempt])


async def list_models(p: Dict[str, Any]) -> List[str]:
    proto = p.get("protocol")
    try:
        base = _base(p)
        async with _client(30) as c:
            if proto == "ollama":
                r = await c.get(base + "/api/tags", headers=_headers(p))
                await _check(r)
                names = [m.get("name") for m in r.json().get("models") or []]
            elif proto == "gemini":
                r = await c.get(_versioned(base, "v1beta") + "/models?pageSize=200", headers=_headers(p))
                await _check(r)
                names = [
                    (m.get("name") or "").replace("models/", "", 1)
                    for m in r.json().get("models") or []
                    if "generateContent" in (m.get("supportedGenerationMethods") or ["generateContent"])
                ]
            else:
                url = (_versioned(base, "v1") if proto == "anthropic" else base) + "/models"
                r = await c.get(url, headers=_headers(p))
                await _check(r)
                data = r.json()
                items = data.get("data") if isinstance(data, dict) else data
                names = [m.get("id") for m in items or [] if isinstance(m, dict)]
    except (httpx.HTTPError, ValueError) as e:
        raise _friendly(e, p)
    return sorted({n for n in names if n})
