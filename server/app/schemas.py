from __future__ import annotations

import enum
from typing import Optional
from pydantic import BaseModel, Field


class ChromeStatus(str, enum.Enum):
    HEALTHY = "Healthy"
    LOGGED_OUT = "Logged Out"
    CAPTCHA = "CAPTCHA"
    FROZEN = "Frozen"
    CHROME_CLOSED = "Chrome Closed"
    OFFLINE = "Offline"
    UNKNOWN = "Unknown"


class MachineStatus(str, enum.Enum):
    ONLINE = "Online"
    WARNING = "Warning"
    OFFLINE = "Offline"


class SystemSnapshotIn(BaseModel):
    machine_name: str
    ip_address: str
    timestamp: float
    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    disk_percent: float
    uptime_seconds: float
    internet_connected: bool
    python_process_running: bool


class ChromeInstanceIn(BaseModel):
    instance_index: int
    status: ChromeStatus
    window_title: Optional[str] = None
    current_page_hint: Optional[str] = None
    reason: Optional[str] = None
    prime_account_name: Optional[str] = None


class HeartbeatIn(BaseModel):
    machine_name: str
    system: SystemSnapshotIn
    chrome_instances: list[ChromeInstanceIn] = Field(default_factory=list)
    monitoring_enabled: bool = True


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AlertOut(BaseModel):
    id: str
    machine_name: str
    chrome_instance_index: Optional[int] = None
    alert_type: str
    message: str
    created_at: float
    resolved: bool
    resolved_at: Optional[float] = None
