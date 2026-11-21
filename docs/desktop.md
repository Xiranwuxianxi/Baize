# 白泽桌面版

桌面版将 Electron 窗口、前端和 Python 后端一起打包。使用者无需另外安装 Node.js 或 Python；模型服务和外部 CLI 仍按各自的使用方式配置。

## 一次构建全部桌面平台

在 GitHub 的 **Actions → Desktop packages → Run workflow** 触发一次，即可同时生成：

| 平台 | 架构 | 安装文件 |
| --- | --- | --- |
| Windows | x64 | 安装版 EXE、免安装 EXE |
| Linux | x64 | AppImage、DEB |
| macOS | Apple Silicon、Intel | 各自的 DMG、ZIP |

推送 `v*` 标签也会触发构建。最终安装文件保存在该次运行的 Artifacts 中，保留 30 天；不会提交到 Git 源码仓库。macOS 包使用临时签名，尚未经过 Apple 公证；Windows 包尚未使用发行证书签名。

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

Python 冻结产物依赖目标操作系统，因此完整三平台构建使用 GitHub 的 Windows、Linux 和 macOS 原生构建机，而不是在一台 Windows 机器上交叉冻结所有后端。

## 数据和构建文件

个人数据继续使用原有的用户数据目录。安装文件只包含前端构建结果、程序代码、Python 运行库及其依赖；不会读取并打包个人数据库、`.env`、`config.yaml` 或工作区。

| 路径 | 用途 | 是否提交到 Git |
| --- | --- | --- |
| `desktop/` 中的入口、配置、锁文件、测试 | 可复现的构建源代码 | 是 |
| `desktop/node_modules/` | 构建依赖 | 否 |
| `.desktop-build/` | Python 构建环境、冻结缓存和后端产物 | 否 |
| `frontend/dist/` | 前端构建结果 | 否 |
| `release/` | 安装包、解包应用和打包器日志 | 否 |

Electron 的应用文件使用明确的包含名单；GitHub 上传步骤也只匹配最终安装文件。即使项目里有其他大型工具或开发文件，也不会随着桌面包一起发布。
