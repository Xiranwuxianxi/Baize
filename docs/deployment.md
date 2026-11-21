# 部署

三种方式，按需选择。

| 方式 | 适合 | 智能体能否管理这台机器 |
| --- | --- | --- |
| 直接运行（Windows / macOS / Linux） | 自己电脑上日常使用 | 能（开启本地操作并逐条同意后） |
| Docker | 放在服务器或 NAS 上、想要隔离环境 | 不能，只能操作容器内和挂载的目录 |
| 手动 | 想自己掌控每一步 | 同直接运行 |

## 直接运行

需要 Python 3.9+ 和 Node.js 18+。

```bash
python run.py
```

Windows 也可以双击 `start.bat`，macOS / Linux 也可以运行 `./start.sh`，它们只是调用 `run.py`。

`run.py` 只用到 Python 标准库，三个系统行为一致：

1. 没有虚拟环境就创建 `backend/.venv`
2. `backend/requirements.txt` 有变化时安装依赖
3. 前端源码比构建产物新时重新构建（没装 Node 但已有构建产物时会跳过）
4. 启动服务

```bash
python run.py --setup     # 只安装和构建，不启动
python run.py --rebuild   # 强制重新构建前端
```

## Docker

```bash
docker compose up -d --build
```

打开 <http://localhost:18760>。

- 数据库和工作区放在 Docker 卷 `mac-data`、`mac-workspace` 里，不在项目文件夹中；想直接在宿主机上看工作区文件，把 compose 里的 `mac-workspace:/workspace` 改成 `/你的目录:/workspace`。需要配置文件时再按注释挂进来。
- 访问宿主机上的 Ollama：渠道地址填 `http://host.docker.internal:11434`（compose 文件已为 Linux 配好这个主机名）。Ollama 需要监听在宿主机可被容器访问的地址上。
- 口令和密钥通过环境变量传入，可以写在与 `docker-compose.yml` 同目录的 `.env` 里：

  ```
  MAC_TOKEN=换成你的口令
  OPENAI_API_KEY=sk-...
  ```

  Docker 里必须有访问口令，本地操作才会生效（容器分辨不出哪台是「本机」）。口令设好后，本地操作开关和工作区照样在「设置」页里调。

- 容器以普通用户（uid 1000）运行。Linux 上如果把宿主机目录挂进去后因为属主不同写不进去，执行 `sudo chown -R 1000:1000 那个目录`。

**容器里的本地操作管不了宿主机。** 智能体执行的命令在容器内运行，能碰到的只有容器自己的文件系统和挂载进去的工作区。界面和给模型的提示词里都会如实说明这一点。想让智能体管理电脑本身，请用「直接运行」。

## 手动

```bash
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt      # Windows: backend\.venv\Scripts\pip
npm --prefix frontend install
npm --prefix frontend run build
backend/.venv/bin/python backend/main.py                       # Windows: backend\.venv\Scripts\python
```

## 配置从哪里来

优先级从高到低：环境变量（含项目根目录的 `.env`） → `config.yaml` → 默认值。

| 用途 | config.yaml | 环境变量 | 默认 |
| --- | --- | --- | --- |
| 监听地址 | `server.host` | `MAC_HOST` | `0.0.0.0` |
| 端口 | `server.port` | `MAC_PORT` | `18760` |
| 访问口令 | `server.token` | `MAC_TOKEN` | 空 |
| 你的数据目录 | — | `MAC_HOME` | 系统的用户应用数据目录（见 README） |
| 数据库目录 | `server.data_dir` | `MAC_DATA_DIR` | `<你的数据目录>/data` |
| 配置文件位置 | — | `MAC_CONFIG` | `./config.yaml` |
| 开启本地操作 | `local_access.enabled` | `MAC_LOCAL_ACCESS=1` | 关闭 |
| 工作目录 | `local_access.workspace` | `MAC_WORKSPACE` | `<你的数据目录>/workspace` |

访问口令、本地操作开关、工作区这几项也可以直接在界面的「设置」页里改，立即生效，并且以设置页为准。上表列的是不想手动点、需要预先配置时的写法。

渠道和智能体也可以写在 `config.yaml` 里，见 [配置文件](config.md)。

## 对外开放前

- 设置访问口令。它是共享口令、经 HTTP 明文传输，需要远程访问时请放在带 TLS 的反向代理或 VPN 之后。
- 反向代理要支持 WebSocket（路径 `/ws`）。
- 详见 [SECURITY.md](../SECURITY.md)。
