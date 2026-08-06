from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.auth import verify_access_token
from app.database import get_database

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", dependencies=[Depends(verify_access_token)])
async def list_alerts(
    resolved: Optional[bool] = Query(default=None),
    machine_name: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=1000),
):
    db = get_database()
    query: dict = {}
    if resolved is not None:
        query["resolved"] = resolved
    if machine_name:
        query["machine_name"] = machine_name

    alerts = []
    async for a in db.alerts.find(query).sort("created_at", -1).limit(limit):
        a["id"] = str(a.pop("_id"))
        alerts.append(a)

    return {"alerts": alerts}
