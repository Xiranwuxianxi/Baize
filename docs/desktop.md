# 白泽桌面版

桌面版将 Electron 窗口、前端和 Python 后端一起打包。使用者无需另外安装 Node.js 或 Python；模型服务和外部 CLI 仍按各自的使用方式配置。

[返回项目首页](../README.md) · [English](desktop.en.md) · [下载与构建页面](https://github.com/Xiranwuxianxi/Baize/actions/workflows/desktop.yml)

## 下载与安装

1. 登录 GitHub，打开上方构建页面。
2. 选择一次成功完成的运行，滚动到页面底部的 **Artifacts**。
3. 下载符合系统和 CPU 架构的产物 ZIP，先将外层 ZIP 解压，再选择其中的安装文件。

[v0.1.0 已验证的三平台构建](https://github.com/Xiranwuxianxi/Baize/actions/runs/44930292420) 已通过四个架构的启动检查和包内容审计。Artifacts 不是永久下载地址，保留期为 30 天。

| 系统 | Artifacts 名称 | 安装方式 |
| --- | --- | --- |
| Windows x64 | `Baize-windows-x64` | `Baize-*-windows-x64-setup.exe` 是安装版；`*-portable.exe` 可直接运行，二选一即可 |
| macOS，M 系列芯片 | `Baize-macos-arm64` | 打开 DMG，将 Baize 拖到 Applications；也可解压应用 ZIP |
| macOS，Intel 芯片 | `Baize-macos-x64` | 安装方式同上；不要和 Apple Silicon 版混用 |
| Linux x64 | `Baize-linux-x64` | AppImage，解压并赋予执行权限后运行 |

Linux AppImage 示例：

```sh
chmod +x Baize-0.1.0-linux-x86_64.AppImage
./Baize-0.1.0-linux-x86_64.AppImage
```

当前 Windows 包尚未使用发行证书签名，macOS 为临时签名且尚未经过 Apple 公证。系统可能显示来源提示；这些包尚不等同于经过签名、公证和应用商店审核的正式发行包。

## 第一次启动

打开 Baize 后，内置后端会自动启动，窗口关闭或应用退出时按系统行为管理；Windows / Linux 关闭最后一个窗口会退出应用，macOS 可通过应用菜单退出。无需另外运行 `python run.py`，也不用手动启动后台服务。

按界面引导添加模型渠道，再创建智能体和会话。模型 API 密钥来自你自己的服务商；使用本地模型时，需要另行启动 Ollama、LM Studio 等服务。安装包不包含模型权重或调用额度。

本地读写文件、命令执行、外部 CLI 智能体和 MCP 仍遵守项目本来的权限设置。本地操作默认关闭，启用后选择允许使用的工作区与审批方式。外部 CLI、MCP 服务器及运行用户脚本所需的工具，需要按各自要求安装。

桌面版会记住自己的后端端口，从而在正常重启后保留该地址上的登录口令、语言等浏览器端设置。若端口被其他程序占用，会分配新端口；该地址上的浏览器端设置可能需要重新选择。模型渠道、会话和智能体等数据库内容仍保存在用户数据目录。

## 更新、备份与数据位置

更新前先在界面导出备份，再退出旧版。Windows 安装版可运行新版安装程序；免安装版替换程序文件；macOS 替换 Applications 内的应用；Linux 使用对应的新 AppImage。不同版本通常共用同一份用户数据，安装目录不是备份位置。

| 系统 | 后端默认数据目录 | Electron 浏览器资料目录 |
| --- | --- | --- |
| Windows | `%APPDATA%\Baize` | `%APPDATA%\BaizeDesktop` |
| macOS | `~/Library/Application Support/Baize` | `~/Library/Application Support/BaizeDesktop` |
| Linux | `~/.local/share/baize` | `~/.config/BaizeDesktop` |

Linux 设置 `XDG_DATA_HOME` / `XDG_CONFIG_HOME` 时使用相应系统目录。`MAC_HOME` 可覆盖后端数据目录。后端目录中包含数据库、个人配置和工作区；`BaizeDesktop` 则保存浏览器资料和端口记录。更换程序文件不会自动清空这些目录；迁移电脑时应备份后端数据，而不是只复制 EXE / AppImage。

旧的 `MultiAgentsControl` / `multi-agents-control` 数据目录按原有迁移逻辑处理，新位置已有数据时不会覆盖。浏览器资料使用独立目录，避免抢先占用后端迁移位置。

## 一次构建全部桌面平台

在 GitHub 的 **Actions → Desktop packages → Run workflow** 触发一次，即可同时生成：

| 平台 | 架构 | 安装文件 |
| --- | --- | --- |
| Windows | x64 | 安装版 EXE、免安装 EXE |
| Linux | x64 | AppImage |
| macOS | Apple Silicon、Intel | 各自的 DMG、ZIP |

推送 `v*` 标签也会触发构建。最终安装文件保存在该次运行的 Artifacts 中，保留 30 天；不会提交到 Git 源码仓库。macOS 包使用临时签名，尚未经过 Apple 公证；Windows 包尚未使用发行证书签名。

打包配置中还定义了 DEB 目标，但本次已验证并上传的 Linux 产物只有 AppImage；上面的下载表按实际文件列出，不能据此认为 DEB 已完成验证。

## 本机构建

需要 Python 3.12 和 Node.js 22 或更新版本。在项目根目录运行：

```sh
python -m pip install -r desktop/requirements-build.txt
npm ci --prefix desktop
npm run check --prefix desktop
npm run build --prefix desktop
npm run smoke --prefix desktop
```

`build` 自动安装前端依赖、构建前端、冻结后端并生成当前系统的安装文件。`npm run pack --prefix desktop` 只生成可运行的应用目录。指定构建解释器时，设置 `BAIZE_BUILD_PYTHON`。

Node.js 至少需要 22.12。默认输出在项目根目录的 `release/`；可用 `BAIZE_DESKTOP_OUTPUT` 指定其他输出目录。构建结束后可运行 `node desktop/audit.cjs` 检查应用文件名单。

Python 冻结产物依赖目标操作系统，因此完整三平台构建使用 GitHub 的 Windows、Linux 和 macOS 原生构建机，而不是在一台 Windows 机器上交叉冻结所有后端。

## 数据和构建文件

个人数据继续使用原有的用户数据目录。Electron 浏览器缓存单独存放在系统应用目录的 `BaizeDesktop` 文件夹，避免影响旧版数据迁移。安装文件只包含前端构建结果、程序代码、Python 运行库及其依赖；不会读取并打包个人数据库、`.env`、`config.yaml` 或工作区。

| 路径 | 用途 | 是否提交到 Git |
| --- | --- | --- |
| `desktop/` 中的入口、配置、锁文件、测试 | 可复现的构建源代码 | 是 |
| `desktop/node_modules/` | 构建依赖 | 否 |
| `.desktop-build/` | Python 构建环境、冻结缓存和后端产物 | 否 |
| `frontend/dist/` | 前端构建结果 | 否 |
| `release/` | 安装包、解包应用和打包器日志 | 否 |

Electron 的应用文件使用明确的包含名单；GitHub 上传步骤也只匹配最终安装文件。即使项目里有其他大型工具或开发文件，也不会随着桌面包一起发布。

## 常见问题

- **找不到下载按钮或产物过期**：确认已登录 GitHub，并打开成功运行详情页的 Artifacts。仓库维护者可以重新运行工作流；其他用户可从源码构建，或 Fork 后运行自己的工作流。
- **窗口提示启动失败**：检查是否选对架构、应用是否完整解压，确认没有只复制解包目录里的一个 EXE。后端日志文件名是 `desktop-backend.log`；macOS 位于 `~/Library/Logs/Baize/`，Windows / Linux 位于 Electron 浏览器资料目录内的日志目录。
- **启动后没有模型可选**：桌面包不会自带模型。先配置渠道，并检查服务地址、密钥、模型名称和本地服务是否已运行。
- **Docker 和桌面版有什么区别**：桌面版的后端运行在本机；Docker 中的本地操作只作用于容器和挂载目录。需要操作本机文件时，先阅读 [本地操作说明](local-access.md)。
- **手机可以直接安装吗**：当前仅提供三个桌面平台的原生包；移动设备可使用已有 Web 界面，当前没有原生 APK / IPA。
