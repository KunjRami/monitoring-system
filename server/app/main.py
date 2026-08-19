from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from app.database import ensure_indexes
from app.services.status_service import (
    sweep_offline_machines,
    sweep_chrome_alerts,
    purge_old_data,
)
from app.routers import (
    dashboard,
    machines,
    alerts,
    accounts,
    auth as auth_router,
    pending_counts,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("server.main")

SWEEP_INTERVAL_SECONDS = 15
PURGE_INTERVAL_SECONDS = 24 * 60 * 60  # once a day


async def _sweep_loop():
    while True:
        try:
            await sweep_offline_machines()
            await sweep_chrome_alerts()
        except Exception:
            logger.exception("Error during status sweep")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


async def _purge_loop():
    while True:
        try:
            await purge_old_data()
        except Exception:
            logger.exception("Error during daily data purge")
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    sweep_task = asyncio.create_task(_sweep_loop())
    purge_task = asyncio.create_task(_purge_loop())
    logger.info("Server started, background sweep + daily purge tasks running")
    yield
    sweep_task.cancel()
    purge_task.cancel()


app = FastAPI(title="Amazon Scope-2 Monitoring Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(dashboard.router)
app.include_router(machines.router)
app.include_router(alerts.router)
app.include_router(accounts.router)
app.include_router(pending_counts.router)
app.mount("/static", StaticFiles(directory="../dashboard/static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/")
async def root():
    return FileResponse("../dashboard/templates/index.html")


@app.get("/login")
async def login_page():
    return FileResponse("../dashboard/templates/login.html")


@app.get("/health")
async def health():
    return {"status": "ok"}