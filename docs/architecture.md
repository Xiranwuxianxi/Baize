# 架构说明

## 总览

```
浏览器 (React)  ── REST /api ──►  FastAPI 后端  ── HTTP 流式 ──►  模型服务（云端 / 本地）
       ▲         ── WebSocket /ws ─►      │
       └──────── 流式事件广播 ◄───────────┘
                                         │
                                     SQLite (data/mac.db)
```

一个进程同时提供接口、WebSocket 和构建好的前端静态文件，所以部署只需要启动 `backend/main.py`。

## 后端

按功能拆成小模块，依赖只朝一个方向（上面的不引用下面的），避免循环导入：

| 文件 | 职责 |
| --- | --- |
| `config.py` | 加载 `.env` 和 `config.yaml`，得到端口、口令、本地操作等启动配置 |
| `store.py` | SQLite 持久化。渠道、智能体、会话、技能、经验、用量等是 JSON 文档（`docs` 表），消息单独成表 |
| `settings.py` | 界面里改的设置，覆盖在启动配置之上 |
| `providers.py` | 连接协议适配层。每种协议一个流式函数，统一产出 `("text" \| "think" \| "stop", 文本)` 和 `("usage", 用量)` |
| `tools.py` | 本地操作：解析操作标签、限定路径、执行命令（统一 UTF-8、可用的 Python） |
| `manage.py` / `mcp.py` | 管家的管理标签、从网址读取技能；MCP 客户端（stdio / Streamable HTTP） |
| `desktop.py` | 用本机应用打开文件、在文件夹中定位，并把窗口切到前台 |
| `common.py` | 输入清洗、按 id 取对象、本机 / 局域网判断、token 估算 |
| `hub.py` | 所有打开的页面（WebSocket）和每个会话正在跑的任务；`broadcast` 推送事件 |
| `files.py` | 会话文件夹，以及查看 / 打开 / 定位文件的接口 |
| `attachments.py` | 消息附件：上传到会话文件夹的 `attachments/`，只认本会话的文件；拼进上下文时最新一条给全文和图片，较早的只留开头 |
| `cleaning.py` | 把界面和配置传来的渠道、智能体、会话整理成存库格式 |
| `usage.py` | 用量统计：按天 × 智能体 × 模型累计，提供统计接口 |
| `lessons.py` | 共享经验库：判断值不值得记、按相关性带进上下文、增删改接口 |
| `memory.py` | 每个智能体自己的记忆：从回复里的 `<remember>` 取出、去重更新、置顶常驻 / 相关才带上、增删改接口；外部智能体不参与 |
| `toolcalls.py` | 原生工具调用：按智能体的权限生成工具声明，把模型返回的调用转成和文本标签相同的操作；渠道拒绝时退回文本标签 |
| `backup.py` | 备份与恢复：SQLite 在线备份打包成 zip；恢复前另存当前数据，原地恢复无需重启 |
| `skills.py` | 技能和 MCP 的管理接口、挑选要带上的技能、管家的管理操作、自动登记新装的技能 |
| `context.py` | 把多方对话整理成某个智能体视角的上下文，并按省 token 规则裁剪 |
| `external.py` | 外部智能体：命令行直接调用，或凭口令轮询领题、提交回复 |
| `orchestra.py` | 编排：发言、本地操作审批与执行、领头人分派、新建 / 移除成员、整场会话的推进 |
| `main.py` | 组装：访问控制中间件、渠道 / 智能体 / 会话 / 设置接口、WebSocket、托管前端 |

### 数据模型

- **渠道 provider**：`name`、`protocol`、`base_url`、`api_key`、`default_model`、`extra_headers`、`models`（缓存的模型列表）。返回给前端时去掉 `api_key`，只带 `key_set` 和 `key_hint`。
- **智能体 agent**：`name`、`avatar`、`color`、`description`、`system_prompt`、`provider_id`、`model`、`temperature`、`max_tokens`、`conv_id`。`conv_id` 为空表示全局智能体，否则只属于那个会话，随会话删除。
- **会话 conversation**：`title`、`agent_ids`（有序，即发言顺序）、`mode`（`sequential` / `parallel` / `lead`）、`lead_id`、`rounds`、`context_limit`。
- **消息 message**：`role`（`user` / `agent`）、`agent_id`、`agent_name`、`model`、`content`、`reasoning`、`error`。领头统筹还会带 `lead`、`assignments`（领头人的分派清单）和 `task`（成员收到的任务）。

### 上下文的拼法

多个智能体共用一份聊天记录，但每次请求都要整理成「以当前智能体为第一人称」的对话，见 `build_context`：

- 用户的消息 → `user`
- 当前智能体自己说过的话 → `assistant`
- 其他智能体的话 → `user`，并加上 `[名字]:` 前缀
- 相邻的同角色消息合并，保证首尾都是 `user`，以满足各协议对角色交替的要求
- 系统提示词 = 名字 + 角色设定 + 多智能体说明（+ 领头人职责、本地操作说明、技能清单、团队经验、它自己置顶的记忆），**每轮保持不变**，各家接口才能缓存这段开头
- 和这次问题相关的技能全文、团队经验、它自己的记忆，附在最后一条消息里，用完就不再重复发送

省 token 模式下还会：最近两条完整、稍早几条保留主体、更早的只留开头；历史总量超过预算（约 3000 token）就从最早的开始省略；被领头人派活的成员只看最近几条。

### WebSocket 事件

客户端发送：

| type | 字段 | 含义 |
| --- | --- | --- |
| `auth` | `token` | 握手，必须是第一条 |
| `send` | `conv_id`、`content`、`targets` | 发消息。`content` 为空表示不发言、让智能体继续；`targets` 非空表示点名 |
| `stop` | `conv_id` | 停止该会话的生成 |

服务端广播给所有已连接的客户端（因此多台设备实时同步）：

| type | 含义 |
| --- | --- |
| `ready` / `unauthorized` | 握手结果 |
| `message` | 一条完整消息的新增或更新，按 `id` 覆盖。`streaming: true` 表示还在生成 |
| `delta` | 流式增量，`kind` 为 `text` 或 `think` |
| `running` | 某个会话开始或结束生成 |
| `conversation` | 会话信息变化（例如自动命名） |
| `error` | 需要提示用户的错误 |

生成任务挂在会话上而不是连接上：浏览器断开后任务继续执行，结果照常落库。

## 前端

Vite + React + Tailwind CSS v4，构建产物输出到 `frontend/dist`，由后端托管。

```
src/
  App.jsx            外壳：侧栏、WebSocket、全局状态
  pages/             Chat、Agents、Providers、Skills、Mcp、Settings、Welcome
  pages/chat/        会话页的组成部分：Message（消息）、cards（审批 / 分派 / 记忆卡片）、Composer（输入区与 @ 补全）、Members（成员面板）
  components/        ui（图标、头像、按钮、弹窗）、Dialog（应用内确认框）、AgentModal、ConvModal、
                     ExternalModal、ManagerBox（就地安装小窗）、Lessons、Usage、Markdown
  lib/api.ts         接口封装（口令只走请求头）与 WebSocket 地址
  lib/i18n.ts        界面多语言：t(中文原文)，译文在 lib/locales/en.ts
  index.css          设计令牌与 Markdown 样式
```

- 状态集中在 `App.jsx`：`data`（渠道、智能体、会话）、`msgs`（按会话缓存的消息）、`running`。
- Markdown 用自写的轻量渲染器直接生成 React 节点，不拼 HTML，模型输出里的 HTML 不会被执行。
- WebSocket 地址按当前访问的域名和端口动态拼出，手机经局域网 IP 访问时无需额外配置。
