"""
Monitoring Agent entrypoint.

Runs as an ordinary Python process, completely separate from the scraper. It
never imports, calls, or communicates with the scraper's code or Selenium
sessions -- it only reads OS/window state and POSTs status to the central
server.

Usage:
    python main.py                          # uses ./config.yaml
    MONITOR_AGENT_CONFIG=other.yaml python main.py
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict

from config import AgentConfig
from logging_setup import setup_logging
from system_monitor import SystemMonitor
from chrome_monitor import ChromeMonitor
from login_detector import (
    PageStatus,
    classify_from_title,
    classify_from_ocr_text,
    capture_screenshot_bytes,
    ocr_text_from_png_bytes,
    screenshot_hash,
    read_address_bar_uia,
    read_account_name_uia,
    extract_account_name,
    get_foreground_window_hwnd,
)
from freeze_detector import FreezeTracker
from mongo_writer import MongoHeartbeatWriter

logger = logging.getLogger("agent.main")


class MonitoringAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.system_monitor = SystemMonitor(machine_name=config.machine_name)
        self.chrome_monitor = ChromeMonitor()
        self.heartbeat_writer = MongoHeartbeatWriter(
            uri=config.mongodb.uri,
            database=config.mongodb.database,
            connect_timeout_ms=config.mongodb.connect_timeout_ms,
            server_selection_timeout_ms=config.mongodb.server_selection_timeout_ms,
        )
        # One FreezeTracker per Chrome window handle (hwnd), created lazily.
        self._freeze_trackers: dict[int, FreezeTracker] = {}
        self._last_screenshot_time = 0.0
        self._last_ocr_text = ""
        # Cache of last-known account name per hwnd. Deliberately never
        # cleared on a "not detected this cycle" result -- OCR only ever sees
        # whichever window is currently in the foreground, so other windows
        # would otherwise flicker to blank every cycle even though the
        # account signed into them hasn't changed.
        self._account_names: dict[int, str] = {}

    def _refresh_account_names(self, windows: list) -> None:
        """
        Updates self._account_names for as many windows as we can detect this
        cycle. UIA can read every window's greeting text regardless of which
        one is on screen; OCR can only ever confirm the foreground window's
        account, since it reads a screenshot of the visible desktop.
        """
        if self.config.detection.use_ui_automation:
            for window in windows:
                name = read_account_name_uia(window.hwnd)
                if name:
                    self._account_names[window.hwnd] = name

        if self._last_ocr_text:
            foreground_hwnd = get_foreground_window_hwnd()
            if foreground_hwnd is not None:
                name = extract_account_name(self._last_ocr_text)
                if name:
                    self._account_names[foreground_hwnd] = name

    def _get_freeze_tracker(self, hwnd: int) -> FreezeTracker:
        if hwnd not in self._freeze_trackers:
            self._freeze_trackers[hwnd] = FreezeTracker(
                cpu_zero_threshold_seconds=self.config.detection.frozen_cpu_zero_seconds,
                same_screenshot_samples=self.config.detection.frozen_same_screenshot_samples,
            )
        return self._freeze_trackers[hwnd]

    def _maybe_refresh_ocr(self) -> None:
        interval = self.config.intervals.screenshot_seconds
        if interval <= 0 or not self.config.detection.use_ocr:
            return
        now = time.time()
        if now - self._last_screenshot_time < interval:
            return
        self._last_screenshot_time = now

        png_bytes = capture_screenshot_bytes()
        if not png_bytes:
            return
        self._last_ocr_text = ocr_text_from_png_bytes(png_bytes)
        # store hash for freeze detection reuse
        self._last_screenshot_hash = screenshot_hash(png_bytes)

    def build_chrome_instance_reports(self) -> list[dict]:
        windows = self.chrome_monitor.list_windows()
        chrome_alive = self.chrome_monitor.is_chrome_process_alive()

        self._maybe_refresh_ocr()
        last_hash = getattr(self, "_last_screenshot_hash", None)
        self._refresh_account_names(windows)

        reports: list[dict] = []

        if not chrome_alive:
            for i in range(self.config.chrome_instance_count):
                reports.append(
                    {
                        "instance_index": i + 1,
                        "status": PageStatus.CHROME_CLOSED.value,
                        "window_title": None,
                        "current_page_hint": None,
                        "reason": "chrome.exe not running",
                    }
                )
            return reports

        # Map each detected window to a slot 1..N. If fewer/more windows exist
        # than configured, we report what we actually see (helps surface a
        # crashed instance immediately).
        for idx, window in enumerate(windows[: self.config.chrome_instance_count], start=1):
            tracker = self._get_freeze_tracker(window.hwnd)
            is_frozen = tracker.is_frozen(
                hung_flag=not window.is_responding,
                pid=window.pid,
                screenshot_hash_value=last_hash,
            )

            if is_frozen:
                classification = None
                status = PageStatus.FROZEN
                reason = "window not responding / no visual change over threshold"
            else:
                classification = classify_from_title(window.title)
                status = classification.status
                reason = classification.reason

                if status == PageStatus.UNKNOWN and self._last_ocr_text:
                    ocr_result = classify_from_ocr_text(self._last_ocr_text)
                    if ocr_result:
                        status = ocr_result.status
                        reason = ocr_result.reason

                if self.config.detection.use_ui_automation and status == PageStatus.UNKNOWN:
                    address_bar_text = read_address_bar_uia(window.hwnd)
                    if address_bar_text and "amazon" in address_bar_text.lower():
                        status = PageStatus.HEALTHY
                        reason = "UIA address bar contains amazon.com"

            reports.append(
                {
                    "instance_index": idx,
                    "status": status.value if isinstance(status, PageStatus) else status,
                    "window_title": window.title,
                    "current_page_hint": reason,
                    "reason": reason,
                    "prime_account_name": self._account_names.get(window.hwnd),
                }
            )

        # Pad out missing instances as "Chrome Closed" (crashed / never opened)
        for idx in range(len(windows) + 1, self.config.chrome_instance_count + 1):
            reports.append(
                {
                    "instance_index": idx,
                    "status": PageStatus.CHROME_CLOSED.value,
                    "window_title": None,
                    "current_page_hint": None,
                    "reason": "no matching Chrome window detected",
                }
            )

        return reports

    def build_heartbeat_payload(self) -> dict:
        snap = self.system_monitor.snapshot()
        return {
            "machine_name": self.config.machine_name,
            "system": asdict(snap),
            "chrome_instances": self.build_chrome_instance_reports(),
            "monitoring_enabled": self.config.monitoring_enabled,
        }

    def run_forever(self) -> None:
        logger.info("Monitoring Agent starting for machine '%s'", self.config.machine_name)
        poll_interval = self.config.intervals.poll_seconds
        heartbeat_interval = self.config.intervals.heartbeat_seconds
        last_heartbeat = 0.0

        while True:
            try:
                if not self.config.monitoring_enabled:
                    time.sleep(poll_interval)
                    continue

                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    payload = self.build_heartbeat_payload()
                    ok = self.heartbeat_writer.send_heartbeat(payload)
                    logger.info(
                        "Heartbeat %s for '%s'",
                        "sent" if ok else "FAILED",
                        self.config.machine_name,
                    )
                    last_heartbeat = now
            except Exception:
                logger.exception("Unhandled error in agent loop; continuing")

            time.sleep(poll_interval)


def main() -> None:
    config = AgentConfig.load()
    setup_logging(config.log_dir, config.log_level)
    agent = MonitoringAgent(config)
    agent.run_forever()


if __name__ == "__main__":
    main()
