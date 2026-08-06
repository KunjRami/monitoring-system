"""
Read-only discovery of Chrome windows and processes.

IMPORTANT: everything in this module only *reads* OS state (process list,
window titles, "is this window hung" flag). Nothing here sends input events,
attaches debuggers, or modifies any window/process in any way.
"""

from __future__ import annotations

import dataclasses
import sys

import psutil

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import win32gui  # type: ignore
    import win32process  # type: ignore


@dataclasses.dataclass
class ChromeWindow:
    hwnd: int
    pid: int
    title: str
    is_responding: bool


class ChromeMonitor:
    """Enumerates Chrome top-level windows without interacting with them."""

    PROCESS_NAME = "chrome.exe"

    def is_chrome_process_alive(self) -> bool:
        for proc in psutil.process_iter(attrs=["name"]):
            if (proc.info.get("name") or "").lower() == self.PROCESS_NAME:
                return True
        return False

    def count_chrome_processes(self) -> int:
        return sum(
            1
            for proc in psutil.process_iter(attrs=["name"])
            if (proc.info.get("name") or "").lower() == self.PROCESS_NAME
        )

    def list_windows(self) -> list[ChromeWindow]:
        """
        Returns one entry per visible top-level Chrome window. On non-Windows
        platforms (e.g. running this file in CI/dev on Linux/Mac) this returns
        an empty list -- the real deployment target is Windows per the
        environment description.
        """
        if not IS_WINDOWS:
            return []

        windows: list[ChromeWindow] = []

        def _enum_handler(hwnd: int, _extra) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                if proc.name().lower() != self.PROCESS_NAME:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return True

            # IsHungAppWindow is a pure, read-only OS query -- the same
            # mechanism Windows Explorer uses to gray out unresponsive
            # windows. It does not send any message that could be mistaken
            # for user input.
            try:
                is_responding = not bool(win32gui.IsHungAppWindow(hwnd))
            except Exception:
                is_responding = True

            windows.append(
                ChromeWindow(hwnd=hwnd, pid=pid, title=title, is_responding=is_responding)
            )
            return True

        win32gui.EnumWindows(_enum_handler, None)
        return windows
