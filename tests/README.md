# 测试

两类测试，都**不会碰你正在使用的数据**：

| 类型 | 位置 | 需要什么 | 运行时间 |
|---|---|---|---|
| 单元测试 | `tests/unit/` | 什么都不需要（不连模型、不联网） | 几秒 |
| 端到端测试 | `tests/e2e*.py` | 一个云端模型渠道（如智谱 GLM） | 十几分钟到半小时 |

## 单元测试

```bash
pip install -r backend/requirements-dev.txt
python -m pytest tests/unit
```

CI 每次提交都会跑，另外用 pyflakes 检查未定义的名字和多余的导入。

## 端到端测试

每个脚本默认会启动一个**临时服务器**（临时数据目录和工作区、只监听本机），测完自动关闭。
模型渠道从环境变量读取，缺少就跳过。**默认不使用本机 Ollama**，普通笔记本也能跑：

```bash
export MAC_TEST_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 任意 OpenAI 兼容接口
export MAC_TEST_API_KEY=你的密钥
export MAC_TEST_MODEL=glm-5.3-flash          # 大多数测试用的模型（快、便宜）
export MAC_TEST_STRONG_MODEL=glm-4.7         # 领头人、新建成员等要求高的测试用的模型（可选）
export MAC_TEST_ANTHROPIC_URL=https://open.bigmodel.cn/api/anthropic   # 同一家的 Anthropic 兼容地址，多测一种协议（可选）
python tests/run_e2e.py              # 全部跑一遍
python tests/run_e2e.py e2e_memory   # 只跑一个
```

| 环境变量 | 作用 |
|---|---|
| `MAC_TEST_PROTOCOL` | 测试渠道的协议，默认 `openai`，可选 `openai_responses` / `anthropic` / `gemini` / `ollama` |
| `MAC_TEST_OLLAMA=1` | 允许使用本机 Ollama（默认不用）；`OLLAMA_URL` / `OLLAMA_MODEL` 指定地址和模型 |
| `MAC_TEST_LAN=1` | 让临时服务器监听局域网，才会测局域网开关 |
| `MAC_TEST_URL` | 指向一个已经在跑的服务器，不另起临时服务器。**不要指向你日常使用的实例**：测试会在上面新建和删除数据、修改设置 |

| 脚本 | 测什么 |
|---|---|
| `e2e.py` | 各协议的流式对话、接力 / 点名 / 并行 / 停止、各种错误提示 |
| `e2e_lead.py` / `e2e_hire.py` | 领头人分派任务、新建 / 移除成员 |
| `e2e_memory.py` | 每个智能体自己的记忆：自动记下、跨会话记得、别的智能体不知道、可以关闭 |
| `e2e_tokens.py` | 省 token 的效果、用量统计、技能按需加载 |
| `e2e_v6.py` | 外部智能体接入、会话文件夹、搜索、记录删除、添加渠道时拉取模型 |
| `e2e_v7.py` | 思考开关、技能、MCP（stdio + HTTP）、局域网开关 |
| `e2e_v9.py` | 管家执行 bash 命令、共享经验库 |
| `e2e_v10.py` | 命令行外部智能体（需要本机装了 Claude Code / Kimi CLI，否则跳过对应部分） |
| `e2e_manager.py` | 管家按网址添加技能、添加 MCP（需要能访问 github.com） |
| `e2e_limits.py` | Ollama 的上下文长度与思考截断（只在 `MAC_TEST_OLLAMA=1` 时运行） |
| `e2e_ops.py` | 配置文件声明的渠道和智能体、本地操作。需要单独带配置文件启动服务器，见脚本开头说明 |
