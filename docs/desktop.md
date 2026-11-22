# 白泽桌面版

桌面版将 Electron 窗口、前端和 Python 后端一起打包。使用者无需另外安装 Node.js 或 Python；模型服务和外部 CLI 仍按各自的使用方式配置。

[返回项目首页](../README.md) · [English](desktop.en.md) · [下载安装包](https://github.com/Xiranwuxianxi/Baize/releases)

## 下载与安装

1. 打开 **[Releases 下载页面](https://github.com/Xiranwuxianxi/Baize/releases)**。
2. 找到最新发布版本，展开 **Assets** 文件列表。
3. 根据下表下载符合系统和 CPU 架构的安装文件。

文件名中的 `*` 表示产品名和版本号。**不要选择 `Source code (zip)` / `Source code (tar.gz)`，它们是源码，不是安装包。**

| 系统 | 安装文件 | 安装方式 |
| --- | --- | --- |
| Windows x64 | `*-windows-x64-setup.exe` / `*-windows-x64-portable.exe` | 前者是安装版，后者可直接运行，二选一即可 |
| macOS，M 系列芯片 | `*-macos-arm64.dmg` / `*-macos-arm64.zip` | 打开 DMG，将 Baize 拖到 Applications；也可解压应用 ZIP |
| macOS，Intel 芯片 | `*-macos-x64.dmg` / `*-macos-x64.zip` | 安装方式同上；不要和 Apple Silicon 版混用 |
| Linux x64 | `*-linux-x86_64.AppImage` / `*-linux-amd64.deb` | AppImage / Debian、Ubuntu 安装包 |

Linux AppImage 示例：

```sh
chmod +x Baize-0.1.0-linux-x86_64.AppImage
./Baize-0.1.0-linux-x86_64.AppImage
```

也可采用验证流程中的解包运行方式：`APPIMAGE_EXTRACT_AND_RUN=1 ./Baize-0.1.0-linux-x86_64.AppImage`。

Debian / Ubuntu 可安装 DEB：

```sh
sudo apt install ./Baize-0.1.0-linux-amd64.deb
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

维护者可在 GitHub 的 **[Actions → Desktop packages](https://github.com/Xiranwuxianxi/Baize/actions/workflows/desktop.yml) → Run workflow** 触发一次，即可同时生成：

| 平台 | 架构 | 安装文件 |
| --- | --- | --- |
| Windows | x64 | 安装版 EXE、免安装 EXE |
| Linux | x64 | AppImage / DEB |
| macOS | Apple Silicon、Intel | 各自的 DMG、ZIP |

推送 `v*` 标签也会触发构建。构建产物保存在该次运行的 Artifacts 中，保留 30 天；维护者将验证后的最终安装文件上传到 [Releases](https://github.com/Xiranwuxianxi/Baize/releases)，供用户按平台下载。安装文件不会提交到 Git 源码仓库。macOS 包使用临时签名，尚未经过 Apple 公证；Windows 包尚未使用发行证书签名。

最终安装文件也会在对应系统上运行：Windows 检查安装、卸载、便携版权限和重复启动；两种 macOS 架构检查 DMG 安装、ZIP 解压及签名完整性；Linux 检查 AppImage 解包启动和 DEB 安装、卸载。每次启动都检查界面是否渲染并等待应用退出。

[新图标与命名说明已验证构建](https://github.com/Xiranwuxianxi/Baize/actions/runs/44944848838) 的四个原生平台任务全部通过，提供 8 个最终安装文件。[Linux 沙箱启动复核](https://github.com/Xiranwuxianxi/Baize/actions/runs/44946217621) 另外确认了这批 AppImage 和 DEB 在不传入 `--no-sandbox` 时可以加载界面并正常退出。

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

- **Windows 便携版双击后退出**：部分 Windows 临时目录的权限会让 Electron 沙箱无法读取解压后的程序。新版启动器会在运行前为程序目录补充应用包的读取和执行权限；不修改用户数据目录，不需要关闭沙箱或安全软件。请重新下载最新构建，不要继续使用旧便携包。构建流程会在带有这类继承权限的临时目录中实际启动最终便携 EXE，检查界面是否渲染。

- **找不到安装包**：打开 [Releases](https://github.com/Xiranwuxianxi/Baize/releases)，展开最新发布版本的 **Assets**，根据系统和 CPU 架构选择上表中的安装文件。`Source code` 是源码；如果没有对应平台的安装包，可从源码构建。
- **窗口提示启动失败**：检查是否选对架构、应用是否完整解压，确认没有只复制解包目录里的一个 EXE。后端日志文件名是 `desktop-backend.log`；macOS 位于 `~/Library/Logs/Baize/`，Windows / Linux 位于 Electron 浏览器资料目录内的日志目录。
- **启动后没有模型可选**：桌面包不会自带模型。先配置渠道，并检查服务地址、密钥、模型名称和本地服务是否已运行。
- **Docker 和桌面版有什么区别**：桌面版的后端运行在本机；Docker 中的本地操作只作用于容器和挂载目录。需要操作本机文件时，先阅读 [本地操作说明](local-access.md)。
- **手机可以直接安装吗**：当前仅提供三个桌面平台的原生包；移动设备可使用已有 Web 界面，当前没有原生 APK / IPA。
