# 连接协议

在「模型渠道」里添加渠道时选择协议。接口地址留空则使用该协议的官方地址。

| 协议 | 请求路径 | 鉴权头 | 模型列表 |
| --- | --- | --- | --- |
| OpenAI 兼容 | `{地址}/chat/completions` | `Authorization: Bearer` | `{地址}/models` |
| OpenAI Responses | `{地址}/responses` | `Authorization: Bearer` | `{地址}/models` |
| Anthropic Messages | `{地址}/v1/messages` | `x-api-key` + `anthropic-version` | `{地址}/v1/models` |
| Google Gemini | `{地址}/v1beta/models/{模型}:streamGenerateContent` | `x-goog-api-key` | `{地址}/v1beta/models` |
| Ollama 原生 | `{地址}/api/chat` | 无（可选 Bearer） | `{地址}/api/tags` |

Anthropic 和 Gemini 的地址如果已经带了版本段（`/v1`、`/v1beta`），不会重复追加。

## 地址怎么填

| 服务 | 协议 | 接口地址 |
| --- | --- | --- |
| Ollama | Ollama 原生 | `http://localhost:11434` |
| LM Studio | OpenAI 兼容 | `http://localhost:1234/v1` |
| vLLM / llama.cpp | OpenAI 兼容 | `http://localhost:8000/v1` |
| OpenAI | OpenAI 兼容 或 Responses | `https://api.openai.com/v1` |
| Anthropic | Anthropic Messages | `https://api.anthropic.com` |
| Google Gemini | Google Gemini | `https://generativelanguage.googleapis.com` |
| DeepSeek | OpenAI 兼容 | `https://api.deepseek.com/v1` |
| 通义千问 | OpenAI 兼容 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 智谱 GLM | OpenAI 兼容 | `https://open.bigmodel.cn/api/paas/v4` |
| Moonshot | OpenAI 兼容 | `https://api.moonshot.cn/v1` |
| 硅基流动 | OpenAI 兼容 | `https://api.siliconflow.cn/v1` |
| OpenRouter | OpenAI 兼容 | `https://openrouter.ai/api/v1` |

Ollama 同时提供 OpenAI 兼容（`/v1`）、Responses 和 Anthropic 兼容接口，所以同一个本机 Ollama 可以用四种协议接入。

## 密钥

- 直接填写：保存在本机数据库，不回传浏览器。
- `env:变量名`：例如 `env:OPENAI_API_KEY`。后端在每次请求时从环境变量（或 `.env`）读取，数据库里只有变量名。修改环境变量后需要重启后端。

## 思考过程

支持思考的模型，其思考内容会和正文分开展示：

| 协议 | 思考内容来自 |
| --- | --- |
| OpenAI 兼容 | `delta.reasoning_content` 或 `delta.reasoning` |
| OpenAI Responses | `response.reasoning_summary_text.delta` |
| Anthropic Messages | `thinking_delta` |
| Google Gemini | `thought` 为真的 part |
| Ollama 原生 | `message.thinking` |

思考会占用输出额度。如果给智能体设了较小的「最大输出 Token」，模型可能只输出了思考就被截断，这时界面会提示调大或留空。

## 上下文长度与输出上限

「模型只思考、不出正文」几乎都是长度问题，分两种：

- **上下文窗口太小（Ollama 最常见）**：Ollama 加载模型时默认只给 4096 token 的窗口，和模型本身支持多少无关。多智能体对话的历史加上思考过程很快就会占满。本项目对 Ollama 原生协议默认请求 8192，可在渠道的「上下文长度」里调整；调大更稳但更占内存，改动后模型会重新加载一次。
  经由 Ollama 的 OpenAI 兼容接口（`/v1`）接入时无法逐次指定窗口大小，需要在 Ollama 侧设置环境变量 `OLLAMA_CONTEXT_LENGTH`。所以本机 Ollama 建议用「Ollama 原生」协议。
- **输出上限太小**：智能体的「最大输出 Token」建议留空。思考也算输出，填得太小会在思考阶段就用完。

为了少出这类问题，后端还做了三件事：

1. 知道窗口大小时（Ollama 原生），发送前从最早的消息开始裁剪历史，给输出留出至少三分之一的空间。
2. 一次回复只有思考没有正文时，自动关掉思考、只带最近几条消息重问一次。
3. 识别各协议的截断信号：正文写到一半被截断会提示可以让它继续。

## 验证情况

作者用本机 Ollama 对原生、OpenAI 兼容、Responses、Anthropic 兼容四个接口做过端到端真实验证，也在智谱 GLM（OpenAI 兼容）上日常使用并跑过全部端到端测试（见 `tests/`）。Gemini 适配和其他云端服务按官方文档的格式实现，尚未做端到端验证。添加渠道后请先点「测试连接」。

## 新增一种协议

1. 在 `backend/providers.py` 写一个异步生成器，签名与现有的 `_openai_chat` 相同，产出 `("text" | "think", 文本)`。
2. 登记到 `_STREAMS`、`PROTOCOLS`、`DEFAULT_BASE`，并在 `_headers` 和 `list_models` 里补上分支。
3. 前端 `pages/Providers.jsx` 的 `SHORT` 里加一个短名称。
