from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import LoginIn, LoginOut
from app.auth import verify_dashboard_credentials, create_access_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn):
    if not verify_dashboard_credentials(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(payload.username)
    return LoginOut(access_token=token)
