from __future__ import annotations

import ctypes
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    import ctypes.wintypes as wintypes
else:
    wintypes = None


DEFAULT_IDLE_SECONDS = 180
MAX_TITLE_CHARS = 140

STATE_LABELS = {
    "coding": "写代码",
    "web": "看网页",
    "gaming": "打游戏",
    "idle": "发呆/离开",
    "chatting": "聊天",
    "media": "看视频/听音乐",
    "writing": "写文档",
    "desktop": "使用电脑",
    "unknown": "未知状态",
}

CODING_PROCESSES = {
    "code.exe",
    "cursor.exe",
    "windsurf.exe",
    "pycharm.exe",
    "pycharm64.exe",
    "idea.exe",
    "idea64.exe",
    "webstorm.exe",
    "clion.exe",
    "rider64.exe",
    "devenv.exe",
    "notepad++.exe",
    "sublime_text.exe",
    "atom.exe",
    "vim.exe",
    "nvim.exe",
    "emacs.exe",
}
TERMINAL_PROCESSES = {
    "windowsterminal.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "wt.exe",
    "conhost.exe",
}
BROWSER_PROCESSES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "arc.exe",
    "iexplore.exe",
}
CHAT_PROCESSES = {
    "discord.exe",
    "wechat.exe",
    "weixin.exe",
    "qq.exe",
    "telegram.exe",
    "slack.exe",
    "teams.exe",
}
MEDIA_PROCESSES = {
    "spotify.exe",
    "music.ui.exe",
    "vlc.exe",
    "potplayermini64.exe",
    "mpv.exe",
}
WRITING_PROCESSES = {
    "winword.exe",
    "excel.exe",
    "powerpnt.exe",
    "onenote.exe",
    "notion.exe",
    "obsidian.exe",
    "typora.exe",
}
GAME_PROCESSES = {
    "steam.exe",
    "steamwebhelper.exe",
    "epicgameslauncher.exe",
    "riotclientservices.exe",
    "leagueclient.exe",
    "league of legends.exe",
    "valorant-win64-shipping.exe",
    "minecraft.exe",
    "genshinimpact.exe",
    "yuanshen.exe",
    "starrail.exe",
    "zenlesszonezero.exe",
    "osu!.exe",
    "bandoriclient.exe",
    "unityplayer.dll",
}

CODING_TITLE_HINTS = (
    "visual studio code",
    "cursor",
    "pycharm",
    "intellij",
    "webstorm",
    "github",
    "git",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".cpp",
    ".cs",
    ".json",
    "powershell",
    "terminal",
)
GAME_TITLE_HINTS = (
    "steam",
    "genshin",
    "原神",
    "崩坏",
    "star rail",
    "绝区零",
    "valorant",
    "league of legends",
    "minecraft",
    "osu!",
    "bang dream",
    "bandori",
)
MEDIA_TITLE_HINTS = ("youtube", "bilibili", "哔哩哔哩", "netflix", "spotify", "music")


def current_desktop_state(idle_threshold_seconds: int = DEFAULT_IDLE_SECONDS) -> dict:
    idle_seconds = _idle_seconds()
    window = _foreground_window_info()
    process_name = str(window.get("process_name", "") or "").lower()
    title = str(window.get("title", "") or "")
    state, confidence, reason = _classify_state(process_name, title, idle_seconds, idle_threshold_seconds)
    return {
        "state": state,
        "label": STATE_LABELS.get(state, STATE_LABELS["unknown"]),
        "confidence": confidence,
        "reason": reason,
        "foreground_title": _truncate_title(title),
        "process_name": process_name,
        "app_name": window.get("app_name", ""),
        "idle_seconds": idle_seconds,
        "idle_threshold_seconds": idle_threshold_seconds,
        "captured_at": datetime.now().replace(microsecond=0).isoformat(timespec="seconds"),
    }


def _classify_state(process_name: str, title: str, idle_seconds: int, idle_threshold_seconds: int) -> tuple[str, float, str]:
    lowered_title = title.lower()
    if idle_seconds >= max(30, idle_threshold_seconds):
        return "idle", 0.95, f"键鼠已空闲 {idle_seconds} 秒"
    if process_name in GAME_PROCESSES or _contains_any(lowered_title, GAME_TITLE_HINTS):
        return "gaming", 0.88, "前台应用或标题像游戏"
    if process_name in CODING_PROCESSES:
        return "coding", 0.92, "前台应用是开发工具"
    if process_name in TERMINAL_PROCESSES and _contains_any(lowered_title, CODING_TITLE_HINTS):
        return "coding", 0.78, "前台终端标题像开发任务"
    if _contains_any(lowered_title, CODING_TITLE_HINTS):
        return "coding", 0.72, "窗口标题包含开发相关线索"
    if process_name in BROWSER_PROCESSES:
        if _contains_any(lowered_title, MEDIA_TITLE_HINTS):
            return "media", 0.72, "浏览器正在打开视频或音乐页面"
        return "web", 0.86, "前台应用是浏览器"
    if process_name in CHAT_PROCESSES:
        return "chatting", 0.82, "前台应用是聊天工具"
    if process_name in MEDIA_PROCESSES or _contains_any(lowered_title, MEDIA_TITLE_HINTS):
        return "media", 0.80, "前台应用或标题像媒体内容"
    if process_name in WRITING_PROCESSES:
        return "writing", 0.82, "前台应用是文档或笔记工具"
    if process_name or title:
        return "desktop", 0.45, "只能确认用户正在使用电脑"
    return "unknown", 0.20, "无法读取前台窗口"


def _foreground_window_info() -> dict:
    if os.name != "nt":
        return {"title": "", "process_name": "", "process_path": "", "app_name": ""}
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "", "process_name": "", "process_path": "", "app_name": ""}
        title = _window_title(hwnd)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_path = _process_path(int(pid.value))
        process_name = Path(process_path).name if process_path else ""
        app_name = Path(process_path).stem if process_path else process_name
        return {
            "title": title,
            "process_name": process_name,
            "process_path": process_path,
            "app_name": app_name,
        }
    except Exception:
        return {"title": "", "process_name": "", "process_path": "", "app_name": ""}


def _window_title(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = int(user32.GetWindowTextLengthW(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return _truncate_title(buffer.value)


def _process_path(pid: int) -> str:
    if pid <= 0:
        return ""
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        return buffer.value if ok else ""
    finally:
        kernel32.CloseHandle(handle)


def _idle_seconds() -> int:
    if os.name != "nt":
        return 0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        now = ctypes.windll.kernel32.GetTickCount64()
        return max(0, int((now - int(info.dwTime)) / 1000))
    except Exception:
        return 0


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _truncate_title(title: str) -> str:
    title = " ".join(str(title or "").split())
    if len(title) <= MAX_TITLE_CHARS:
        return title
    return title[: MAX_TITLE_CHARS - 1] + "..."
