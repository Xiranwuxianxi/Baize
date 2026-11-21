# Baize desktop app

[Project home](../README.en.md) · [中文](desktop.md) · [Downloads and builds](https://github.com/Xiranwuxianxi/Baize/actions/workflows/desktop.yml)

The desktop packages include Electron, the built frontend, the Python backend and its runtime. End users do not need Node.js or Python to launch Baize. Model weights, API credits, external CLI agents and MCP servers are not included.

## Download and install

Sign in to GitHub, open the **Desktop packages** workflow, choose a successful run and find **Artifacts** at the bottom. Download and extract the outer artifact ZIP, then use the installer inside.

| Platform | Artifact | Contents |
| --- | --- | --- |
| Windows x64 | `Baize-windows-x64` | Setup EXE and portable EXE; choose one |
| macOS Apple Silicon | `Baize-macos-arm64` | DMG and application ZIP |
| macOS Intel | `Baize-macos-x64` | DMG and application ZIP |
| Linux x64 | `Baize-linux-x64` | AppImage |

[Verified v0.1.0 build](https://github.com/Xiranwuxianxi/Baize/actions/runs/44930292420). Artifacts are retained for **30 days**. Maintainers can regenerate them through **Run workflow**; other users can build locally or run the workflow in a fork.

On Windows, run the setup installer or the portable executable. On macOS, open the DMG and drag Baize into Applications, or extract the application ZIP. On Linux, make the AppImage executable:

```sh
chmod +x Baize-0.1.0-linux-x86_64.AppImage
./Baize-0.1.0-linux-x86_64.AppImage
```

Windows release signing is not configured. macOS apps are ad-hoc signed and are not notarized. The operating system may display a source-verification prompt.

## First launch

Open Baize; its backend starts automatically. Add a model channel, create agents and start a conversation. Cloud providers require your own credentials; local model services such as Ollama or LM Studio must run separately. Local operations are off by default and retain the workspace and approval controls of the Web app.

The desktop app remembers its backend port, preserving browser-side preferences at the same origin across normal restarts. If the port is occupied, it allocates another; browser-side settings may need to be selected again. Channels, conversations and other database contents remain in the user data directory.

Closing the last window exits the app on Windows and Linux. On macOS, use the application menu to quit. You do not need to start a separate `python run.py` process.

## Data, updates and backups

| System | Backend data | Electron profile |
| --- | --- | --- |
| Windows | `%APPDATA%\Baize` | `%APPDATA%\BaizeDesktop` |
| macOS | `~/Library/Application Support/Baize` | `~/Library/Application Support/BaizeDesktop` |
| Linux | `~/.local/share/baize` | `~/.config/BaizeDesktop` |

Linux follows `XDG_DATA_HOME` / `XDG_CONFIG_HOME` when configured. Set `MAC_HOME` to override the backend data location. The backend folder stores the database, private configuration and workspace; the Electron profile stores browser data and the desktop port record. Keeping these separate also preserves legacy data migration.

Export a backup from the UI before updating. Quit the old app, then install the new Windows setup, replace the portable executable or macOS application, or use the updated AppImage. Replacing program files does not itself erase user data. When moving to another computer, back up the data folder rather than copying only the executable.

Legacy `MultiAgentsControl` / `multi-agents-control` data is migrated without overwriting existing destination data.

## Build all desktop platforms

Use **Actions → Desktop packages → Run workflow** once to start Windows x64, Linux x64, macOS Apple Silicon and macOS Intel jobs. A `v*` tag also triggers the workflow. Each target uses a native runner because the frozen Python backend is OS-specific.

Each job builds installers, launches the unpacked app for a smoke test, audits package contents and checks that generated files did not enter the Git checkout. Only final EXE, DMG, ZIP, AppImage and DEB files are uploaded as artifacts.

The build configuration also defines a DEB target, but the verified Linux artifact currently contains only the AppImage. The download table reflects the actual uploaded files; DEB output is not yet verified.

## Build on the current platform

Requires Python 3.12 and Node.js 22.12 or newer:

```sh
python -m pip install -r desktop/requirements-build.txt
npm ci --prefix desktop
npm run check --prefix desktop
npm run build --prefix desktop
npm run smoke --prefix desktop
node desktop/audit.cjs
```

`build` installs frontend dependencies, builds the frontend, freezes the backend and packages the current platform. `npm run pack --prefix desktop` builds only the runnable application directory. Set `BAIZE_BUILD_PYTHON` to choose the build interpreter, or `BAIZE_DESKTOP_OUTPUT` to override the default `release/` output directory.

| Path | Purpose | Tracked by Git |
| --- | --- | --- |
| `desktop/` runtime sources, build configuration, tests and lockfile | Reproducible build inputs | Yes |
| `desktop/node_modules/` | Build dependencies | No |
| `.desktop-build/` | Build environment, caches and frozen backend | No |
| `frontend/dist/` | Built Web interface | No |
| `release/` | Installers, unpacked apps and builder logs | No |

The runtime uses an explicit file inclusion list. Private databases, `.env`, `config.yaml` and user workspaces are not collected into the installer.

## Troubleshooting

- **No artifacts or expired download:** sign in to GitHub and open a successful run. Regenerate the packages as a maintainer, build locally, or build in a fork.
- **Startup error:** check the CPU architecture and fully extract the package. Do not copy only one executable out of an unpacked application directory. The backend log is `desktop-backend.log`; on macOS it is under `~/Library/Logs/Baize/`, and on Windows/Linux it is inside the Electron profile's log directory.
- **No models:** configure a provider and check its endpoint, key and model name, or start the local model server.
- **Desktop versus Docker:** desktop tools run on the host; Docker tools act on the container and mounted folders. Read [local operations](local-access.md) before enabling commands or file access.
- **Mobile installation:** native APK/IPA packages are not provided. Mobile devices can use the Web interface.
