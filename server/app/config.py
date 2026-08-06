from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import BaseModel

DEFAULT_CONFIG_PATH = os.environ.get("MONITOR_SERVER_CONFIG", "config.yaml")


class MongoConfig(BaseModel):
    uri: str
    database: str


class ApiConfig(BaseModel):
    # No longer used for agent auth (agents write directly to MongoDB now --
    # see agent/mongo_writer.py). Kept only in case a future HTTP-facing
    # integration needs a shared secret again.
    api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000


class AuthConfig(BaseModel):
    username: str
    password: str
    jwt_secret: str
    jwt_expiry_minutes: int = 480


class HeartbeatConfig(BaseModel):
    warning_after_missed_intervals: int = 2
    offline_after_missed_intervals: int = 4
    expected_interval_seconds: int = 30


class AlertsConfig(BaseModel):
    webhook_url: str = ""


class RetentionConfig(BaseModel):
    # Raw heartbeats/status_history older than this are deleted daily.
    # Resolved alerts older than this are also deleted; UNRESOLVED alerts
    # are never deleted regardless of age. Current live state (machines,
    # chrome_instances) is untouched -- this only prunes history logs.
    days: int = 1


class ExcelAccountsConfig(BaseModel):
    # Source of truth for the "Available Accounts" widget: a local .xlsx
    # file instead of Google Sheets -- no API, no credentials, no network
    # call. Columns, in order: Account name, Phone No, Password, Remarks.
    enabled: bool = True
    file_path: str = "Accounts.xlsx"
    sheet_name: str = "Sheet1"
    header_rows: int = 1  # number of header rows to skip before data starts
    cache_seconds: int = 30


class ServerConfig(BaseModel):
    mongodb: MongoConfig
    api: ApiConfig
    auth: AuthConfig
    heartbeat: HeartbeatConfig
    alerts: AlertsConfig
    retention: RetentionConfig = RetentionConfig()
    excel_accounts: ExcelAccountsConfig = ExcelAccountsConfig()


@lru_cache
def get_config() -> ServerConfig:
    path = Path(DEFAULT_CONFIG_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Server config not found at '{path}'. Copy config.yaml.example to "
            f"config.yaml and edit it."
        )
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return ServerConfig(**raw)