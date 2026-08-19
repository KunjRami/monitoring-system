from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_config

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None

_client_pending: AsyncIOMotorClient | None = None
_db_pending: AsyncIOMotorDatabase | None = None


def get_database() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        cfg = get_config()
        _client = AsyncIOMotorClient(cfg.mongodb.uri)
        _db = _client[cfg.mongodb.database]
    return _db


def get_database_pending() -> AsyncIOMotorDatabase | None:
    """
    Separate MongoDB deployment for the pending-pagesaves widget. Returns
    None if no `pending:` section is configured in config.yaml -- callers
    must handle that (see status_service.get_pending_pagesaves), so a
    missing/optional pending DB never breaks the rest of the dashboard.
    """
    global _client_pending, _db_pending
    if _db_pending is None:
        cfg = get_config().pending
        if cfg is None:
            return None
        _client_pending = AsyncIOMotorClient(cfg.uri)
        _db_pending = _client_pending[cfg.database]
    return _db_pending


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
    # NOTE: no TTL indexes here -- `timestamp` is stored as a plain Python
    # float (time.time()), not a BSON Date, and MongoDB's TTL monitor
    # silently skips non-Date fields. Retention is handled explicitly by
    # purge_old_data() in status_service.py instead.