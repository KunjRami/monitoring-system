from __future__ import annotations

import abc
import logging
import time
from typing import Any

import httpx

from app.config import get_config
from app.database import get_database

logger = logging.getLogger("server.alert_service")

# Statuses that should raise an alert when first observed.
ALERTABLE_CHROME_STATUSES = {"Logged Out", "CAPTCHA", "Chrome Closed", "Frozen"}
ALERTABLE_MACHINE_STATUSES = {"Offline"}


class AlertChannel(abc.ABC):
    @abc.abstractmethod
    async def send(self, message: str, context: dict[str, Any]) -> None: ...


class ConsoleAlertChannel(AlertChannel):
    async def send(self, message: str, context: dict[str, Any]) -> None:
        logger.warning("ALERT: %s | %s", message, context)


class WebhookAlertChannel(AlertChannel):
    """Generic HTTP POST -- compatible with Slack/Teams incoming webhooks
    with zero code changes, just set alerts.webhook_url in config.yaml."""

    def __init__(self, url: str):
        self.url = url

    async def send(self, message: str, context: dict[str, Any]) -> None:
        if not self.url:
            return
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self.url, json={"text": message, "context": context})
        except httpx.HTTPError as exc:
            logger.warning("Webhook alert delivery failed: %s", exc)


def get_alert_channels() -> list[AlertChannel]:
    cfg = get_config()
    channels: list[AlertChannel] = [ConsoleAlertChannel()]
    if cfg.alerts.webhook_url:
        channels.append(WebhookAlertChannel(cfg.alerts.webhook_url))
    return channels


async def raise_alert(
    machine_name: str,
    alert_type: str,
    message: str,
    chrome_instance_index: int | None = None,
) -> None:
    db = get_database()

    # Avoid duplicate open alerts for the same (machine, instance, type).
    existing = await db.alerts.find_one(
        {
            "machine_name": machine_name,
            "chrome_instance_index": chrome_instance_index,
            "alert_type": alert_type,
            "resolved": False,
        }
    )
    if existing:
        return

    doc = {
        "machine_name": machine_name,
        "chrome_instance_index": chrome_instance_index,
        "alert_type": alert_type,
        "message": message,
        "created_at": time.time(),
        "resolved": False,
        "resolved_at": None,
    }
    await db.alerts.insert_one(doc)

    for channel in get_alert_channels():
        await channel.send(message, doc)


async def resolve_alerts(machine_name: str, alert_type: str, chrome_instance_index: int | None = None) -> None:
    db = get_database()
    await db.alerts.update_many(
        {
            "machine_name": machine_name,
            "chrome_instance_index": chrome_instance_index,
            "alert_type": alert_type,
            "resolved": False,
        },
        {"$set": {"resolved": True, "resolved_at": time.time()}},
    )
