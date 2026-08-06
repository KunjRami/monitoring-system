"""
Frozen-browser detection, combining three read-only signals:
  1. IsHungAppWindow (authoritative, instant)
  2. CPU pinned at ~0% for the Chrome process tree over a threshold window
  3. Screenshot hash unchanged across N consecutive samples

See docs/LOGIN_DETECTION_METHODS.md for the rationale.
"""

from __future__ import annotations

import collections
import time
from dataclasses import dataclass, field

import psutil


@dataclass
class FreezeTracker:
    """One instance per Chrome window/instance being tracked over time."""

    cpu_zero_threshold_seconds: int = 120
    same_screenshot_samples: int = 3

    _cpu_zero_since: float | None = None
    _screenshot_hashes: collections.deque = field(default_factory=lambda: collections.deque(maxlen=5))

    def observe_cpu(self, pid: int) -> bool:
        """Returns True if CPU has been ~0% for the configured threshold."""
        try:
            proc = psutil.Process(pid)
            cpu = proc.cpu_percent(interval=0.3)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

        now = time.time()
        if cpu < 0.5:
            if self._cpu_zero_since is None:
                self._cpu_zero_since = now
            elapsed = now - self._cpu_zero_since
            return elapsed >= self.cpu_zero_threshold_seconds
        else:
            self._cpu_zero_since = None
            return False

    def observe_screenshot_hash(self, hash_value: str) -> bool:
        """Returns True if the last N screenshot hashes are all identical."""
        self._screenshot_hashes.append(hash_value)
        if len(self._screenshot_hashes) < self.same_screenshot_samples:
            return False
        recent = list(self._screenshot_hashes)[-self.same_screenshot_samples:]
        return len(set(recent)) == 1

    def is_frozen(self, hung_flag: bool, pid: int, screenshot_hash_value: str | None) -> bool:
        if hung_flag:
            return True

        cpu_stuck = self.observe_cpu(pid)
        screenshot_stuck = (
            self.observe_screenshot_hash(screenshot_hash_value)
            if screenshot_hash_value
            else False
        )
        # Require both weaker signals together to reduce false positives from
        # a page that's just idle-but-fine.
        return cpu_stuck and screenshot_stuck
