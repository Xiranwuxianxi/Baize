# Baize desktop app

[Project home](../README.en.md) · [中文](desktop.md) · [Download installers](https://github.com/Xiranwuxianxi/Baize/releases)

The desktop packages include Electron, the built frontend, the Python backend and its runtime. End users do not need Node.js or Python to launch Baize. Model weights, API credits, external CLI agents and MCP servers are not included.

## Download and install

Open the **[Releases download page](https://github.com/Xiranwuxianxi/Baize/releases)**, expand **Assets** under the latest release and download a package for your operating system and CPU architecture.

The `*` in the filenames below stands for the product name and version. **`Source code (zip)` / `Source code (tar.gz)` are source archives, not installers.**

| Platform | Package filename | Installation |
| --- | --- | --- |
| Windows x64 | `*-windows-x64-setup.exe` / `*-windows-x64-portable.exe` | Setup installer or portable executable; choose one |
| macOS Apple Silicon (M series) | `*-macos-arm64.dmg` / `*-macos-arm64.zip` | Open the DMG and drag Baize into Applications, or extract the application ZIP |
| macOS Intel | `*-macos-x64.dmg` / `*-macos-x64.zip` | Install as above; choose the Intel version |
| Linux x64 | `*-linux-x86_64.AppImage` / `*-linux-amd64.deb` | AppImage or Debian/Ubuntu package |

On Windows, run the setup installer or the portable executable. On macOS, open the DMG and drag Baize into Applications, or extract the application ZIP. On Linux, make the AppImage executable:

```sh
chmod +x Baize-0.1.0-linux-x86_64.AppImage
./Baize-0.1.0-linux-x86_64.AppImage
```

The tested extract-and-run alternative is `APPIMAGE_EXTRACT_AND_RUN=1 ./Baize-0.1.0-linux-x86_64.AppImage`.

On Debian/Ubuntu, install the DEB with:

```sh
sudo apt install ./Baize-0.1.0-linux-amd64.deb
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

In **[Actions → Desktop packages](https://github.com/Xiranwuxianxi/Baize/actions/workflows/desktop.yml) → Run workflow**, enter the previous packaging version and choose `small` or `big`. That choice starts one batch across Windows x64, Linux x64, macOS Apple Silicon and macOS Intel. Each target uses a native runner because the frozen Python backend is OS-specific. Tag pushes do not trigger builds automatically.

Each job builds every expected distribution format, launches the unpacked application and each final package, audits package contents and checks that generated files did not enter Git. Missing output files or failed package checks fail the build. Only final EXE, DMG, ZIP, AppImage and DEB files are uploaded.

Build artifact names include the selected version and build time in Beijing time (UTC+8). Artifacts are retained for 30 days. **The user uploads the final installers to [Releases](https://github.com/Xiranwuxianxi/Baize/releases) manually; the workflow does not publish a release.** For a retry, reuse that batch's previous version; for a new batch, enter the version produced by the preceding batch.

Final packages are tested on their native systems: Windows setup installation/uninstallation and portable permission/concurrent-launch checks; DMG installation, ZIP extraction and signature integrity on both Mac architectures; AppImage extract-and-run and DEB installation/uninstallation on Linux. Every launch checks that the interface renders and waits for the app to exit.

[Verified build with the new logo and naming story](https://github.com/Xiranwuxianxi/Baize/actions/runs/44944848838): all four native jobs passed, producing eight final distribution files. An additional [Linux sandbox check](https://github.com/Xiranwuxianxi/Baize/actions/runs/44946217621) confirmed that both Linux packages render and exit without `--no-sandbox`.

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

`build` installs frontend dependencies, builds the frontend, freezes the backend and packages the current platform. `npm run pack --prefix desktop` builds only the runnable application directory. Set `BAIZE_BUILD_PYTHON` to choose the build interpreter.

Both commands first ask whether this is a small or big update, showing the current and proposed version. Enter `q` to cancel. The baseline is aligned with the published version, `1.0.1`.

| Choice | Rule | Example |
| --- | --- | --- |
| `small` | Increment the last number; after 9 reset it to 0 and increment the middle number | `1.2.8 → 1.2.9 → 1.3.0` |
| `big` | Increment the first number and reset both other numbers | `1.3.4 → 2.0.0` |

The middle number has no single-digit limit: `1.9.9 → 1.10.0`. A successful local build updates `VERSION`, both package manifests and their lockfiles. Installer filenames and bundled application versions use the same selected version.

An assistant must ask the user first, then pass the confirmed choice, for example `npm run build --prefix desktop -- --update small`. Non-interactive builds without a choice stop instead of assuming an update type.

Each batch uses a new directory such as `release/Baize-1.0.2_2026-11-22_17-35-40/`. Times use Beijing time (`Asia/Shanghai`, UTC+8) down to seconds. Older batches are preserved; a numeric suffix avoids collisions within the same second. `BAIZE_DESKTOP_OUTPUT` overrides the parent directory while retaining the timestamped subdirectory. `BUILD.json` records the batch version and time. Subsequent smoke tests, package installation checks and audits resolve the most recent successful batch automatically.

| Path | Purpose | Tracked by Git |
| --- | --- | --- |
| `desktop/` runtime sources, build configuration, tests and lockfile | Reproducible build inputs | Yes |
| `desktop/node_modules/` | Build dependencies | No |
| `.desktop-build/` | Build environment, caches and frozen backend | No |
| `frontend/dist/` | Built Web interface | No |
| `release/` | Installers, unpacked apps and builder logs | No |

The runtime uses an explicit file inclusion list. Private databases, `.env`, `config.yaml` and user workspaces are not collected into the installer.

## Troubleshooting

- **Windows portable exits immediately:** inherited permissions on some Windows temporary folders can prevent Electron's sandbox from reading the extracted application. The launcher grants application packages read/execute access to the program directory before launch. It leaves user data permissions unchanged and keeps the sandbox enabled. Download a new build instead of reusing the old portable executable. CI launches the final portable EXE under a temporary directory with inherited package permissions and checks that the interface renders.

- **Cannot find an installer:** open [Releases](https://github.com/Xiranwuxianxi/Baize/releases), expand **Assets** under the latest release and choose a package from the table above. `Source code` downloads are source archives. If your platform has no package, build from source.
- **Startup error:** check the CPU architecture and fully extract the package. Do not copy only one executable out of an unpacked application directory. The backend log is `desktop-backend.log`; on macOS it is under `~/Library/Logs/Baize/`, and on Windows/Linux it is inside the Electron profile's log directory.
- **No models:** configure a provider and check its endpoint, key and model name, or start the local model server.
- **Desktop versus Docker:** desktop tools run on the host; Docker tools act on the container and mounted folders. Read [local operations](local-access.md) before enabling commands or file access.
- **Mobile installation:** native APK/IPA packages are not provided. Mobile devices can use the Web interface.
