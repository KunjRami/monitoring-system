"""
Classifies the state of an Amazon page shown in a Chrome window, using only
passive/read-only signals. See docs/LOGIN_DETECTION_METHODS.md for the full
tradeoff discussion.

Layered approach:
  1. Window title keyword match (fast, always on)
  2. Screenshot + OCR (optional, throttled) to disambiguate generic titles
  3. UI Automation address-bar read (optional, off by default)
"""

from __future__ import annotations

import enum
import hashlib
import re
import sys
from dataclasses import dataclass
from typing import Optional

IS_WINDOWS = sys.platform == "win32"


class PageStatus(str, enum.Enum):
    HEALTHY = "Healthy"
    LOGGED_OUT = "Logged Out"
    CAPTCHA = "CAPTCHA"
    FROZEN = "Frozen"
    CHROME_CLOSED = "Chrome Closed"
    OFFLINE = "Offline"
    UNKNOWN = "Unknown"


# Keyword sets used purely for read-only text classification of a window
# title / OCR'd page text. These are generic, well-known UI copy fragments
# (e.g. the standard wording of a sign-in prompt or a robot-check page) --
# not scraping logic, not credentials, not anything that interacts with the
# site.
_LOGGED_OUT_HINTS = ("sign in", "sign-in", "login", "log in")
_CAPTCHA_HINTS = ("robot check", "captcha", "enter the characters", "verify you're a human")
_ERROR_HINTS = ("page not found", "something went wrong", "err_", "dinosaur")
_BLANK_HINTS = ("new tab", "")


@dataclass
class ClassificationResult:
    status: PageStatus
    reason: str
    matched_signal: str  # "title", "ocr", "uia", "hung", "heuristic"


def classify_from_title(title: str) -> ClassificationResult:
    lowered = title.lower().strip()

    if lowered in _BLANK_HINTS:
        return ClassificationResult(PageStatus.UNKNOWN, "blank/new-tab title", "title")

    for hint in _CAPTCHA_HINTS:
        if hint in lowered:
            return ClassificationResult(PageStatus.CAPTCHA, f"title matched '{hint}'", "title")

    for hint in _LOGGED_OUT_HINTS:
        if hint in lowered:
            return ClassificationResult(PageStatus.LOGGED_OUT, f"title matched '{hint}'", "title")

    for hint in _ERROR_HINTS:
        if hint in lowered:
            return ClassificationResult(PageStatus.UNKNOWN, f"title matched error hint '{hint}'", "title")

    if "amazon" in lowered:
        return ClassificationResult(PageStatus.HEALTHY, "generic Amazon page title", "title")

    return ClassificationResult(PageStatus.UNKNOWN, "no matching title heuristic", "title")


def classify_from_ocr_text(text: str) -> Optional[ClassificationResult]:
    """Refines an UNKNOWN/ambiguous title-based result using OCR'd screen text."""
    lowered = text.lower()
    for hint in _CAPTCHA_HINTS:
        if hint in lowered:
            return ClassificationResult(PageStatus.CAPTCHA, f"OCR matched '{hint}'", "ocr")
    for hint in _LOGGED_OUT_HINTS:
        if hint in lowered:
            return ClassificationResult(PageStatus.LOGGED_OUT, f"OCR matched '{hint}'", "ocr")
    return None


# Amazon's standard signed-in greeting reads "Hello, <name>" (top-right nav,
# e.g. "Hello, kishor  Account & Lists"). This regex is just matching that
# fixed, publicly-visible UI copy pattern -- the same text a human glancing
# at the screen would read -- not decoding anything hidden or credential-like.
_ACCOUNT_NAME_PATTERN = re.compile(r"hello,?\s*\n?\s*([A-Za-z][A-Za-z.\-' ]{1,40})", re.IGNORECASE)
# Trailing words that sometimes get OCR'd/UIA'd onto the same text node with
# no separating space/newline; strip them and anything after.
_ACCOUNT_NAME_STOP_WORDS = ("account", "lists", "sign", "returns", "orders")


def extract_account_name(text: str) -> Optional[str]:
    """
    Pulls the signed-in account's display name out of OCR'd or UIA-read page
    text using Amazon's standard "Hello, <name>" greeting. Returns None if no
    greeting is found (e.g. logged out, or greeting not currently visible).
    """
    if not text:
        return None
    match = _ACCOUNT_NAME_PATTERN.search(text)
    if not match:
        return None

    name = match.group(1).strip()
    lowered = name.lower()
    for stop in _ACCOUNT_NAME_STOP_WORDS:
        idx = lowered.find(stop)
        if idx != -1:
            name = name[:idx].strip()
            break

    name = name.strip(" .,-'")
    if not name or len(name) > 40:
        return None
    return name


def capture_screenshot_bytes(monitor_index: int = 0):
    """
    Captures the whole screen (or a given monitor) as PNG bytes using `mss`.
    This is a pure screen-read operation -- equivalent to pressing PrintScreen
    -- and never sends anything to the target window.
    Returns None if screenshotting isn't available (e.g. non-Windows dev env
    or `mss` not installed).
    """
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore
    except ImportError:
        return None

    try:
        with mss.mss() as sct:
            monitor = sct.monitors[monitor_index if monitor_index < len(sct.monitors) else 0]
            raw = sct.grab(monitor)
            return mss.tools.to_png(raw.rgb, raw.size)
    except Exception:
        return None


def ocr_text_from_png_bytes(png_bytes: bytes) -> str:
    """Runs Tesseract OCR over screenshot bytes. Returns '' if unavailable."""
    try:
        import io
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return ""

    try:
        image = Image.open(io.BytesIO(png_bytes))
        return pytesseract.image_to_string(image)
    except Exception:
        return ""


def screenshot_hash(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes).hexdigest()


def read_address_bar_uia(hwnd: int) -> Optional[str]:
    """
    OPTIONAL, off by default (see config.detection.use_ui_automation).
    Reads the Chrome address bar's text via UI Automation, using only
    read-only property getters (never .click()/.set_focus()/.invoke()).
    Returns None if UIA isn't available or the control can't be found.
    """
    if not IS_WINDOWS:
        return None
    try:
        import uiautomation as auto  # type: ignore
    except ImportError:
        return None

    try:
        window = auto.ControlFromHandle(hwnd)
        if window is None:
            return None
        edit = window.EditControl(searchDepth=8, foundIndex=1)
        if edit and edit.Exists(0, 0):
            return edit.GetValuePattern().Value  # read-only property access
    except Exception:
        return None
    return None


def read_account_name_uia(hwnd: int, search_depth: int = 24) -> Optional[str]:
    """
    OPTIONAL, gated by config.detection.use_ui_automation. Walks a specific
    Chrome window's accessibility tree (read-only -- no click/focus/activate
    calls) looking for a text node matching Amazon's "Hello, <name>" greeting.

    Crucially, this works on a *background* window -- it does not require
    that window to be visible/foregrounded, unlike the screenshot+OCR path,
    so it can be run for all 5 Chrome instances on a machine even though only
    one of them is ever actually on screen at a time.
    """
    if not IS_WINDOWS:
        return None
    try:
        import uiautomation as auto  # type: ignore
    except ImportError:
        return None

    try:
        window = auto.ControlFromHandle(hwnd)
        if window is None:
            return None
        walker = auto.WalkControl(window, includeTop=False, maxDepth=search_depth)
        for control, _depth in walker:
            try:
                text = control.Name
            except Exception:
                continue
            if text and "hello" in text.lower():
                name = extract_account_name(text)
                if name:
                    return name
    except Exception:
        return None
    return None


def get_foreground_window_hwnd() -> Optional[int]:
    """
    Read-only query for which window currently has focus -- used only to
    decide which window's screenshot text a detected account name should be
    attributed to. Does not change focus or activate anything.
    """
    if not IS_WINDOWS:
        return None
    try:
        import win32gui  # type: ignore
        return win32gui.GetForegroundWindow()
    except Exception:
        return None
