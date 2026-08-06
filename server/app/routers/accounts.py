from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.auth import verify_access_token
from app.database import get_database
from app.services import excel_service

logger = logging.getLogger("server.routers.accounts")

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


@router.get("", dependencies=[Depends(verify_access_token)])
async def available_accounts(refresh: bool = Query(default=False, description="Bypass cache and re-read the Excel file")):
    """
    Returns the pool of available accounts from a local Excel file (account
    name, phone, password, remarks, inferred status). See
    app/services/excel_service.py for setup + the status-inference caveat.
    """
    try:
        return excel_service.get_available_accounts(force_refresh=refresh)
    except FileNotFoundError:
        logger.warning("Available-accounts Excel file not found")
        return {"success": False, "error": "Excel file not found on the server."}
    except Exception as exc:
        logger.exception("Failed to read available accounts from Excel file")
        return {"success": False, "error": f"Could not read the Excel file: {exc}"}


@router.get("/summary", dependencies=[Depends(verify_access_token)])
async def accounts_summary():
    """
    Aggregates Prime account usage across every known Chrome instance in the
    fleet: how many systems/instances each account is currently signed into,
    and which ones specifically -- so a heavily-reused account (risk of rate
    limiting / bans) or an underused one can be spotted at a glance.
    """
    db = get_database()

    accounts: dict[str, list[dict]] = {}
    unassigned_count = 0

    async for instance in db.chrome_instances.find({}):
        name = instance.get("prime_account_name")
        if not name:
            unassigned_count += 1
            continue
        accounts.setdefault(name, []).append(
            {
                "machine_name": instance["machine_name"],
                "instance_index": instance["instance_index"],
                "status": instance.get("status", "Unknown"),
            }
        )

    rows = [
        {
            "account_name": name,
            "instance_count": len(usages),
            "usages": sorted(usages, key=lambda u: (u["machine_name"], u["instance_index"])),
        }
        for name, usages in accounts.items()
    ]
    rows.sort(key=lambda r: r["instance_count"], reverse=True)

    counts = [r["instance_count"] for r in rows]
    max_count = max(counts) if counts else 0
    min_count = min(counts) if counts else 0

    for row in rows:
        row["is_highest_used"] = bool(counts) and row["instance_count"] == max_count
        row["is_lowest_used"] = bool(counts) and row["instance_count"] == min_count

    total_assigned_instances = sum(counts)

    return {
        "accounts": rows,
        "total_accounts": len(rows),
        "total_assigned_instances": total_assigned_instances,
        "unassigned_instances": unassigned_count,
        "highest_used_count": max_count,
        "lowest_used_count": min_count,
    }