"""
Direct-to-MongoDB heartbeat writer.

The agent connects straight to the central MongoDB instead of going through
an HTTP API, so it needs no inbound firewall rule on the server for an HTTP
port -- just outbound reachability to Mongo's port. Writes are upserts keyed
on machine_name (and instance_index for Chrome documents), so brand-new
machines register themselves automatically and there is nothing to configure
on the "server" side when a machine is added, replaced, or removed.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError

logger = logging.getLogger("agent.mongo_writer")


class MongoHeartbeatWriter:
    def __init__(
        self,
        uri: str,
        database: str,
        connect_timeout_ms: int = 5000,
        server_selection_timeout_ms: int = 5000,
    ):
        # A single persistent client with its own internal connection pool --
        # NOT a new connection per heartbeat. This is what keeps 20 agents
        # from ever putting meaningful load on MongoDB.
        self._client = MongoClient(
            uri,
            connectTimeoutMS=connect_timeout_ms,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
            retryWrites=True,
        )
        self._db = self._client[database]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self._db.machines.create_index("machine_name", unique=True)
            self._db.chrome_instances.create_index(
                [("machine_name", 1), ("instance_index", 1)], unique=True
            )
            # TTL index: raw history documents older than 7 days are
            # automatically deleted by MongoDB itself, so the history
            # collections never grow unbounded no matter how long this runs.
            self._db.heartbeats.create_index("timestamp", expireAfterSeconds=7 * 24 * 3600)
            self._db.status_history.create_index("timestamp", expireAfterSeconds=7 * 24 * 3600)
        except PyMongoError as exc:
            logger.warning("Could not ensure indexes (will retry on next successful connect): %s", exc)

    def send_heartbeat(self, payload: dict[str, Any]) -> bool:
        """
        Mirrors the shape the FastAPI server used to accept over HTTP, but
        writes straight into the same collections the dashboard reads from
        (see server/app/services/status_service.py for the read side).
        """
        now = time.time()
        machine_name = payload["machine_name"]
        system = payload["system"]

        try:
            machine_doc = {
                "machine_name": machine_name,
                "ip_address": system["ip_address"],
                "last_heartbeat": now,
                "status": "Online",
                "cpu_percent": system["cpu_percent"],
                "ram_percent": system["ram_percent"],
                "ram_used_mb": system["ram_used_mb"],
                "ram_total_mb": system["ram_total_mb"],
                "disk_percent": system["disk_percent"],
                "uptime_seconds": system["uptime_seconds"],
                "internet_connected": system["internet_connected"],
                "python_process_running": system["python_process_running"],
                "monitoring_enabled": payload.get("monitoring_enabled", True),
                "chrome_instance_count": len(payload.get("chrome_instances", [])),
            }

            self._db.machines.update_one(
                {"machine_name": machine_name},
                {"$set": machine_doc, "$setOnInsert": {"first_seen": now}},
                upsert=True,
            )

            self._db.heartbeats.insert_one({**machine_doc, "timestamp": now})

            instance_ops = []
            history_docs = []
            for instance in payload.get("chrome_instances", []):
                instance_doc = {
                    "machine_name": machine_name,
                    "instance_index": instance["instance_index"],
                    "status": instance["status"],
                    "window_title": instance.get("window_title"),
                    "current_page_hint": instance.get("current_page_hint"),
                    "reason": instance.get("reason"),
                    "prime_account_name": instance.get("prime_account_name"),
                    "last_updated": now,
                }
                instance_ops.append(
                    UpdateOne(
                        {"machine_name": machine_name, "instance_index": instance["instance_index"]},
                        {"$set": instance_doc},
                        upsert=True,
                    )
                )
                history_docs.append({**instance_doc, "timestamp": now})

            if instance_ops:
                self._db.chrome_instances.bulk_write(instance_ops, ordered=False)
            if history_docs:
                self._db.status_history.insert_many(history_docs, ordered=False)

            # If this machine now reports fewer Chrome instances than it used
            # to (e.g. count turned down from 6 to 3 in config.yaml), drop the
            # now-stale higher-index documents so the dashboard doesn't show
            # ghost entries.
            reported_indices = [i["instance_index"] for i in payload.get("chrome_instances", [])]
            if reported_indices:
                self._db.chrome_instances.delete_many(
                    {
                        "machine_name": machine_name,
                        "instance_index": {"$gt": max(reported_indices)},
                    }
                )

            return True
        except PyMongoError as exc:
            logger.warning("Heartbeat write failed: %s", exc)
            return False

    def close(self) -> None:
        self._client.close()
