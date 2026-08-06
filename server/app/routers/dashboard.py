from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import verify_access_token
from app.database import get_database
from app.services.status_service import get_dashboard_summary

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/summary", dependencies=[Depends(verify_access_token)])
async def summary():
    return await get_dashboard_summary()
