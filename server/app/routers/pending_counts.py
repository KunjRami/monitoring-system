from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import verify_access_token
from app.services.status_service import get_pending_pagesaves

router = APIRouter(
    prefix="/api/v1/pending-pagesaves",
    tags=["Pending Page Saves"],
)


@router.get("/pending-summary", dependencies=[Depends(verify_access_token)])
async def pending_summary():
    return await get_pending_pagesaves()