from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.auth import verify_access_token
from app.database import get_database

router = APIRouter(prefix="/api/v1/machines", tags=["machines"])


@router.get("", dependencies=[Depends(verify_access_token)])
async def list_machines(
    search: Optional[str] = Query(default=None, description="Filter by machine name substring"),
    status: Optional[str] = Query(default=None, description="Online | Warning | Offline"),
    sort_by: Optional[str] = Query(default="machine_name", description="machine_name | status"),
):
    db = get_database()

    query: dict = {}
    if search:
        query["machine_name"] = {"$regex": search, "$options": "i"}
    if status:
        query["status"] = status

    sort_field = "machine_name" if sort_by not in ("machine_name", "status") else sort_by
    machines = [m async for m in db.machines.find(query).sort(sort_field, 1)]

    result = []
    for m in machines:
        m.pop("_id", None)
        chrome_instances = [
            c async for c in db.chrome_instances.find({"machine_name": m["machine_name"]}).sort(
                "instance_index", 1
            )
        ]
        for c in chrome_instances:
            c.pop("_id", None)
        m["chrome_instances"] = chrome_instances
        result.append(m)

    return {"machines": result}


@router.get("/{machine_name}", dependencies=[Depends(verify_access_token)])
async def get_machine(machine_name: str):
    db = get_database()
    machine = await db.machines.find_one({"machine_name": machine_name})
    if not machine:
        return {"error": "not found"}
    machine.pop("_id", None)
    chrome_instances = [
        c async for c in db.chrome_instances.find({"machine_name": machine_name}).sort(
            "instance_index", 1
        )
    ]
    for c in chrome_instances:
        c.pop("_id", None)
    machine["chrome_instances"] = chrome_instances
    return machine
