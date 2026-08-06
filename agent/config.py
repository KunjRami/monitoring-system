"""
Configuration loading for the Monitoring Agent.

No values are hardcoded anywhere else in the agent -- everything comes from
config.yaml (path overridable via the MONITOR_AGENT_CONFIG env var), so a new
machine is onboarded purely by copying config.yaml.example -> config.yaml and
editing values, with no code changes.
"""

from __future__ import annotations

import os
import dataclasses
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = os.environ.get("MONITOR_AGENT_CONFIG", "config.yaml")


@dataclasses.dataclass
class MongoConfig:
    uri: str
    database: str
    connect_timeout_ms: int = 5000
    server_selection_timeout_ms: int = 5000


@dataclasses.dataclass
class Intervals:
    heartbeat_seconds: int = 30
    poll_seconds: int = 15
    screenshot_seconds: int = 90


@dataclasses.dataclass
class DetectionConfig:
    use_ocr: bool = True
    use_ui_automation: bool = False
    frozen_cpu_zero_seconds: int = 120
    frozen_same_screenshot_samples: int = 3


@dataclasses.dataclass
class AgentConfig:
    machine_name: str
    chrome_instance_count: int
    mongodb: MongoConfig
    intervals: Intervals
    detection: DetectionConfig
    monitoring_enabled: bool = True
    log_level: str = "INFO"
    log_dir: str = "./logs"

    @staticmethod
    def load(path: str | Path = DEFAULT_CONFIG_PATH) -> "AgentConfig":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Agent config not found at '{path}'. Copy config.yaml.example "
                f"to config.yaml and edit it for this machine."
            )
        with open(path, "r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        mongodb_raw = raw.get("mongodb", {})
        intervals_raw = raw.get("intervals", {})
        detection_raw = raw.get("detection", {})

        return AgentConfig(
            machine_name=raw["machine_name"],
            chrome_instance_count=int(raw.get("chrome_instance_count", 5)),
            mongodb=MongoConfig(
                uri=mongodb_raw["uri"],
                database=mongodb_raw.get("database", "amazon_monitoring"),
                connect_timeout_ms=int(mongodb_raw.get("connect_timeout_ms", 5000)),
                server_selection_timeout_ms=int(
                    mongodb_raw.get("server_selection_timeout_ms", 5000)
                ),
            ),
            intervals=Intervals(
                heartbeat_seconds=int(intervals_raw.get("heartbeat_seconds", 30)),
                poll_seconds=int(intervals_raw.get("poll_seconds", 15)),
                screenshot_seconds=int(intervals_raw.get("screenshot_seconds", 90)),
            ),
            detection=DetectionConfig(
                use_ocr=bool(detection_raw.get("use_ocr", True)),
                use_ui_automation=bool(detection_raw.get("use_ui_automation", False)),
                frozen_cpu_zero_seconds=int(detection_raw.get("frozen_cpu_zero_seconds", 120)),
                frozen_same_screenshot_samples=int(
                    detection_raw.get("frozen_same_screenshot_samples", 3)
                ),
            ),
            monitoring_enabled=bool(raw.get("monitoring_enabled", True)),
            log_level=str(raw.get("log_level", "INFO")),
            log_dir=str(raw.get("log_dir", "./logs")),
        )
