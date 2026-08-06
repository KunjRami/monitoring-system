from __future__ import annotations

import time
import logging
from typing import Any

from app.database import get_database
from app.config import get_config
from app.services.alert_service import (
    raise_alert,
    resolve_alerts,
    ALERTABLE_CHROME_STATUSES,
    ALERTABLE_MACHINE_STATUSES,
)

logger = logging.getLogger("server.status_service")

# NOTE: heartbeat ingestion no longer happens via an HTTP endpoint on this
# server. Agents write directly to MongoDB (see agent/mongo_writer.py) so
# that they only need outbound reachability to Mongo, not an inbound HTTP
# connection into this server. This module now only *reads* that data for
# the dashboard, plus derives alerts from current DB state on each sweep
# cycle (see sweep_chrome_alerts below), since there's no longer a single
# ingestion call site to hook alert-raising into.


async def purge_old_data() -> dict[str, int]:
    """
    Deletes raw heartbeats/status_history older than config.retention.days,
    and RESOLVED alerts older than the same window. Unresolved alerts are
    never touched regardless of age -- an ongoing issue shouldn't silently
    disappear just because it's been open a while. Current live state
    (the `machines` and `chrome_instances` collections the dashboard
    actually reads for its main view) is untouched by this entirely; this
    only prunes history/log-style collections that otherwise grow forever.

    Called once at server startup and then once every 24h (see
    _purge_loop in app/main.py).
    """
    cfg = get_config()
    db = get_database()
    cutoff = time.time() - (cfg.retention.days * 24 * 3600)

    heartbeats_result = await db.heartbeats.delete_many({"timestamp": {"$lt": cutoff}})
    history_result = await db.status_history.delete_many({"timestamp": {"$lt": cutoff}})
    alerts_result = await db.alerts.delete_many(
        {"resolved": True, "resolved_at": {"$lt": cutoff}}
    )

    counts = {
        "heartbeats_deleted": heartbeats_result.deleted_count,
        "status_history_deleted": history_result.deleted_count,
        "resolved_alerts_deleted": alerts_result.deleted_count,
    }
    logger.info(
        "Daily purge (retention=%dd): removed %d heartbeats, %d status_history docs, "
        "%d resolved alerts",
        cfg.retention.days,
        counts["heartbeats_deleted"],
        counts["status_history_deleted"],
        counts["resolved_alerts_deleted"],
    )
    return counts


async def sweep_chrome_alerts() -> None:
    """
    Background task: scans current chrome_instances state and raises/resolves
    alerts accordingly. Runs on the same cadence as sweep_offline_machines
    since alerting no longer happens inline with heartbeat ingestion.
    """
    db = get_database()

    async for instance in db.chrome_instances.find({}):
        machine_name = instance["machine_name"]
        idx = instance["instance_index"]
        status = instance.get("status", "Unknown")

        if status in ALERTABLE_CHROME_STATUSES:
            await raise_alert(
                machine_name=machine_name,
                alert_type=status,
                message=(
                    f"{machine_name} Chrome #{idx}: {status} "
                    f"({instance.get('reason') or 'no detail'})"
                ),
                chrome_instance_index=idx,
            )
        else:
            for alertable in ALERTABLE_CHROME_STATUSES:
                await resolve_alerts(machine_name, alertable, chrome_instance_index=idx)


async def sweep_offline_machines() -> None:
    """Background task: mark machines Warning/Offline if heartbeats stop."""
    cfg = get_config()
    db = get_database()
    now = time.time()
    interval = cfg.heartbeat.expected_interval_seconds

    warning_cutoff = now - (interval * cfg.heartbeat.warning_after_missed_intervals)
    offline_cutoff = now - (interval * cfg.heartbeat.offline_after_missed_intervals)

    async for machine in db.machines.find({}):
        last = machine.get("last_heartbeat", 0)
        machine_name = machine["machine_name"]
        new_status = machine.get("status", "Online")

        if last < offline_cutoff:
            new_status = "Offline"
        elif last < warning_cutoff:
            new_status = "Warning"
        else:
            new_status = "Online"

        if new_status != machine.get("status"):
            await db.machines.update_one(
                {"machine_name": machine_name}, {"$set": {"status": new_status}}
            )

        if new_status in ALERTABLE_MACHINE_STATUSES:
            await raise_alert(
                machine_name=machine_name,
                alert_type="Machine Offline",
                message=f"{machine_name} has not sent a heartbeat in over "
                f"{cfg.heartbeat.offline_after_missed_intervals * interval}s",
            )
        else:
            await resolve_alerts(machine_name, "Machine Offline")


async def get_dashboard_summary() -> dict[str, Any]:
    db = get_database()

    machines = [m async for m in db.machines.find({})]
    chrome_instances = [c async for c in db.chrome_instances.find({})]

    total_systems = len(machines)
    systems_online = sum(1 for m in machines if m.get("status") == "Online")
    systems_offline = sum(1 for m in machines if m.get("status") == "Offline")

    status_counts = {
        "Working": 0,
        "Logged Out": 0,
        "Not Working_C": 0,
        "Not Working_F": 0,
        "Chrome Closed": 0,
        "Offline": 0,
        "Unknown": 0,
    }
    for c in chrome_instances:
        status_counts[c.get("status", "Unknown")] = status_counts.get(c.get("status", "Unknown"), 0) + 1

    avg_cpu = round(sum(m.get("cpu_percent", 0) for m in machines) / total_systems, 1) if total_systems else 0.0
    avg_ram = round(sum(m.get("ram_percent", 0) for m in machines) / total_systems, 1) if total_systems else 0.0

    return {
        "total_systems": total_systems,
        "systems_online": systems_online,
        "systems_offline": systems_offline,
        "total_chrome_instances": len(chrome_instances),
        "healthy_browsers": status_counts["Working"],
        "logged_out_browsers": status_counts["Logged Out"],
        "captcha_count": status_counts["Not Working_C"],
        "frozen_browsers": status_counts["Not Working_F"],
        "closed_browsers": status_counts["Chrome Closed"],
        "average_cpu": avg_cpu,
        "average_ram": avg_ram,
        "unknown_browsers": status_counts.get("Unknown", 0) + status_counts.get("Not Working", 0),
    }