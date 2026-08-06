from __future__ import annotations

import time
from typing import Optional

from fastapi import Header, HTTPException, status
from jose import jwt, JWTError

from app.config import get_config

ALGORITHM = "HS256"


def create_access_token(username: str) -> str:
    cfg = get_config()
    expire = time.time() + cfg.auth.jwt_expiry_minutes * 60
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, cfg.auth.jwt_secret, algorithm=ALGORITHM)


def verify_dashboard_credentials(username: str, password: str) -> bool:
    cfg = get_config()
    return username == cfg.auth.username and password == cfg.auth.password


def verify_access_token(authorization: str = Header(default="")) -> str:
    cfg = get_config()
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, cfg.auth.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username: Optional[str] = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return username
