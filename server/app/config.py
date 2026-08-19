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


class PendingConfig(BaseModel):
    # Separate MongoDB deployment that holds page-save progress data --
    # unrelated to the main monitoring DB above. Read from config.yaml
    # instead of being hardcoded in code, same as every other setting here.
    uri: str
    database: str
    collection: str = "Amazon_scope_2_testing_final"


class ApiConfig(BaseModel):
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
    days: int = 1


class ExcelAccountsConfig(BaseModel):
    enabled: bool = True
    file_path: str = "Accounts.xlsx"
    sheet_name: str = "Sheet1"
    header_rows: int = 1
    cache_seconds: int = 30


class ServerConfig(BaseModel):
    mongodb: MongoConfig
    api: ApiConfig
    auth: AuthConfig
    heartbeat: HeartbeatConfig
    alerts: AlertsConfig
    retention: RetentionConfig = RetentionConfig()
    excel_accounts: ExcelAccountsConfig = ExcelAccountsConfig()
    pending: PendingConfig | None = None  # optional -- pending-counts widget is skipped if absent


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