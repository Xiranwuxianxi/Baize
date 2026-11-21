"""在这台电脑上用对应的应用打开文件、在文件管理器里定位文件，并把窗口带到最前面。

为什么要专门处理「带到最前面」：本程序是后台服务，Windows 不允许后台进程把别的窗口切到前台，
直接 os.startfile 打开的窗口经常躲在浏览器后面，看起来像「没反应」。
"""
import os
import platform
import subprocess
import threading
import time
from typing import Set

SYSTEM = platform.system()

# 智能体写出的脚本 / 程序：点「打开」时不直接运行，改用文本编辑器打开，避免误执行
RUNNABLE = {".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp",
            ".scr", ".lnk", ".hta", ".cpl", ".reg", ".py", ".pyw", ".sh", ".bash", ".command", ".jar", ".app", ".pl", ".rb"}


def is_runnable(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RUNNABLE


# ---------------------------------------------------------------- Windows：找到新窗口并切到前台
def _win_windows() -> Set[int]:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    found: Set[int] = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            found.add(hwnd)
        return True

    user32.EnumWindows(each, 0)
    return found


def _win_title(hwnd: int) -> str:
    import ctypes
    n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


# 系统自己的浮层（任务切换、托盘等），不是我们要找的应用窗口
_SYSTEM_CLASSES = {"XamlExplorerHostIslandWindow", "MultitaskingViewFrame", "ForegroundStaging", "Shell_TrayWnd",
                   "Windows.UI.Core.CoreWindow", "TaskSwitcherWnd", "#32770"}


def _win_class(hwnd: int) -> str:
    import ctypes
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _win_front(hwnd: int) -> None:
    """把窗口切到前台。先用「挂到当前前台线程上」的标准做法；不行再按一下 Alt 拿到切换权限。"""
    import ctypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    me = kernel32.GetCurrentThreadId()
    attached = fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    if user32.GetForegroundWindow() != hwnd:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)


def _win_raise_after(before: Set[int], hint: str) -> None:
    """等目标窗口出现后切到前台：新开的窗口，或标题里出现了文件名的已有窗口
    （VS Code、记事本标签页这类会复用已经开着的窗口）。"""
    hint = (hint or "").lower()

    def run():
        deadline = time.time() + 8
        while time.time() < deadline:
            time.sleep(0.2)
            try:
                wins = [h for h in _win_windows() if _win_class(h) not in _SYSTEM_CLASSES]
            except Exception:
                return
            named = [h for h in wins if hint and hint in _win_title(h).lower()]
            new = [h for h in wins if h not in before]
            target = (named or new or [None])[0]
            if target:
                time.sleep(0.25)  # 让窗口画完再切，避免闪一下又被抢回去
                try:
                    _win_front(target)
                except Exception:
                    pass
                return
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- 对外接口
def open_file(path: str) -> str:
    """用系统默认应用打开文件，返回实际做了什么（给界面提示）。脚本 / 程序改用文本编辑器打开。"""
    runnable = is_runnable(path)
    if SYSTEM == "Windows":
        before = _win_windows()
        if runnable:
            subprocess.Popen(["notepad.exe", path])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
        _win_raise_after(before, os.path.basename(path))
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", "-e", path] if runnable else ["open", path])  # open 会自动把应用带到前台
    else:
        if runnable:
            return reveal(path)
        subprocess.Popen(["xdg-open", path])
    return "用文本编辑器打开（脚本和程序不会直接运行）" if runnable else "已用默认应用打开"


def reveal(path: str) -> str:
    """在文件管理器里打开所在文件夹，并选中这个文件。"""
    if SYSTEM == "Windows":
        before = _win_windows()
        if os.path.isfile(path):
            subprocess.Popen('explorer /select,"%s"' % path)
        else:
            os.startfile(path)  # type: ignore[attr-defined]
        _win_raise_after(before, os.path.basename(os.path.dirname(path) if os.path.isfile(path) else path))
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])
    return "已在文件夹中显示"
