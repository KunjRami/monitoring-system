from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_config

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_database() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        cfg = get_config()
        _client = AsyncIOMotorClient(cfg.mongodb.uri)
        _db = _client[cfg.mongodb.database]
    return _db


async def ensure_indexes() -> None:
    db = get_database()
    await db.machines.create_index("machine_name", unique=True)
    await db.chrome_instances.create_index(
        [("machine_name", 1), ("instance_index", 1)], unique=True
    )
    await db.heartbeats.create_index([("machine_name", 1), ("timestamp", -1)])
    await db.status_history.create_index([("machine_name", 1), ("timestamp", -1)])
    await db.alerts.create_index([("machine_name", 1), ("created_at", -1)])
    await db.alerts.create_index("resolved")
    # NOTE: no TTL indexes here. An earlier version tried
    # `create_index("timestamp", expireAfterSeconds=...)`, but `timestamp` is
    # stored as a plain Python float (time.time()), not a BSON Date -- and
    # MongoDB's TTL monitor silently skips non-Date fields, so those indexes
    # never actually deleted anything. Retention is handled explicitly
    # instead by purge_old_data() in status_service.py, run daily.