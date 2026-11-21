# 参与贡献

感谢你愿意改进这个项目。下面是让改动顺利合入需要知道的事。

## 第一次参与：从零到提交合并请求

1. **Fork 并克隆**：在 GitHub 上点 Fork，然后
   ```bash
   git clone https://github.com/<你的用户名>/Baize.git
   cd Baize
   git checkout -b fix/简短说明      # 每件事一个分支
   ```
2. **装好开发环境**（Python 3.10+、Node.js 18+）：
   ```bash
   python -m venv backend/.venv
   backend/.venv/bin/pip install -r backend/requirements-dev.txt   # Windows：backend\.venv\Scripts\pip
   npm --prefix frontend install
   ```
3. **用一份单独的开发数据**，别和你日常使用的数据混在一起（见下一节）：
   ```bash
   export MAC_HOME=$PWD/.dev-home     # Windows PowerShell：$env:MAC_HOME="$PWD\.dev-home"
   ```
4. **跑起来**，开两个终端：
   ```bash
   backend/.venv/bin/python backend/main.py   # 后端 18760
   npm --prefix frontend run dev              # 前端 18761，已代理 /api 与 /ws，改代码自动刷新
   ```
5. **改完自检**（下面「提交前请确认」），然后
   ```bash
   python scripts/check_release.py   # 确认没有把数据库、密钥、个人路径带进来
   git add -A && git commit -m "fix: 简短说明"
   git push origin fix/简短说明
   ```
   在 GitHub 上从你的分支发起合并请求，写清改了什么、为什么、怎么验证的。

## 你的数据和代码是分开的

程序默认把数据库、工作区、你自己的 `config.yaml` / `.env` 放在系统的用户应用数据目录（Windows `%APPDATA%\Baize`，macOS `~/Library/Application Support/Baize`，Linux `~/.local/share/baize`），**不在仓库里**。所以：

- 你在仓库里怎么改、怎么切分支、怎么 `git clean`，都不会丢数据；你的数据也不会被误提交。
- 开发时建议用 `MAC_HOME=./.dev-home` 起一份独立的开发数据（`.dev-home/` 已在 `.gitignore` 中）：随便建测试渠道、测试智能体，不影响你日常用的那份；想从头再来，删掉 `.dev-home` 即可。
- 自带的测试从不碰任何真实数据：单元测试用临时库，端到端测试自己起临时服务器（见 [tests/README.md](tests/README.md)）。
- 需要真实模型的端到端测试，从环境变量读渠道（`MAC_TEST_BASE_URL`、`MAC_TEST_API_KEY`、`MAC_TEST_MODEL`），不需要也不应该把密钥写进任何文件。

## 开发环境说明

- Python 3.10+。后端代码暂时保持 3.9 也能运行（用 `Optional[X]`，不要用 `X | None` 和 `match`），给还没升级的用户留过渡期
- Node.js 18+
- 依赖版本锁定在 `backend/requirements.lock`；升级依赖时改 `requirements.txt` 的范围，跑完测试后更新锁定文件。

## 提交前请确认

1. 前端检查和构建都通过：`npm --prefix frontend run check`（ESLint、TypeScript 类型检查、Vitest）和 `npm --prefix frontend run build`。新代码优先写 `.ts` / `.tsx`；界面文字用 `t()`（`src/lib/i18n.ts`），需要英文时在 `src/lib/locales/en.ts` 里加译文。
2. 后端检查和单元测试通过（几秒，不需要模型；CI 也会跑）：

   ```bash
   pip install -r backend/requirements-dev.txt
   python -m pyflakes backend/*.py tests/unit
   python -m pytest tests/unit
   ```

3. 涉及对话、协议或编排的改动，用真实模型跑一遍端到端测试。它们会自己起临时服务器，**不会碰你的数据**；缺少模型渠道或 Ollama 的测试会自动跳过：

   ```bash
   export MAC_TEST_BASE_URL=... MAC_TEST_API_KEY=... MAC_TEST_MODEL=...
   python tests/run_e2e.py
   ```

   端到端测试**只连真实服务，不使用模拟服务**。新增功能请在对应脚本里补上断言，纯逻辑部分在 `tests/unit/` 里补单元测试。详见 [tests/README.md](tests/README.md)。

4. 界面改动请同时检查电脑宽度、手机宽度和深色模式。

## 代码约定

**后端**

- 后端按功能分模块（见 [docs/architecture.md](docs/architecture.md)），依赖只朝一个方向：`common` → `hub` → `files` → `cleaning` → `usage` → `lessons` → `memory` → `skills` → `toolcalls` → `context` → `external` → `orchestra` → `main`。新代码放进对应模块；单个文件尽量不超过 800 行。
- 新增接口：在对应模块的 `router` 上注册（`@router.get(...)`），`main.py` 统一挂载。
- 新增连接协议：在 `backend/providers.py` 里实现一个流式函数并登记到 `_STREAMS`，同时补上 `list_models` 的分支和 `PROTOCOLS`、`DEFAULT_BASE`。流式函数产出 `("text" | "think" | "stop", 文本)`，拿得到用量时再产出 `("usage", {"in", "out", "cached"})`。
- **省 token 是硬要求**：任何会发给模型的新内容（提示词说明、工具描述、上下文）都要想清楚是否每轮都需要；与问题相关才需要的放进 `context.py` 的「本次相关部分」，不要改动每轮固定的系统提示。新的模型调用路径要调用 `usage.record_usage` 记账。
- 上游错误要转成用户能看懂的中文说明，通过 `ProviderError` 抛出。
- API Key 不得出现在任何返回给前端的数据或日志里。

**前端**

- 目录：`src/pages` 放页面，`src/components` 放可复用组件，`src/lib` 放与界面无关的逻辑。
- 样式只用 `src/index.css` 里定义的设计令牌（`bg-surface`、`text-muted`、`border-line` 等），不要写死颜色。
- 图标统一用 Phosphor，经由 `components/ui.jsx` 里的 `Icon` 登记后使用；界面里不使用 emoji。
- 动效只改 `transform` 和 `opacity`，并尊重 `prefers-reduced-motion`。
- 文案：按钮用动词开头说明会发生什么；报错说清原因和下一步。
- 不要使用浏览器原生的 `confirm()` / `prompt()` / `alert()`（部分内嵌浏览器会直接吞掉）；用 `components/Dialog.jsx` 的 `ask()`。

## 提交与合并请求

- 一个合并请求只做一件事，说明改了什么、为什么改、怎么验证的。
- 提交信息用祈使句概括改动，例如 `add gemini thinking support`、`修复清空消息时的竞态`。
- 行为有变化时同步更新 `README.md`、`docs/` 和 `CHANGELOG.md`。

## 报告问题

提 Issue 时请附上：操作系统、Python 与 Node 版本、所用模型服务与协议、复现步骤，以及界面上或终端里的报错原文。**不要贴出 API Key。**

安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。
