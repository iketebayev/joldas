import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .auth import LoginRequired
from .db import close_pool, init_pool, pool
from .config import RATES_REFRESH_HOURS
from .services import kyc, rates, safety
from .routers import academy, account, analytics, api, contact, moderation, verify, tours, auth, billing, dashboard, guides, public, requests, reviews
from .web import redirect, render

log = logging.getLogger("app")


async def _purge_loop():
    """Анкеты безопасности — через SAFETY_RETENTION_DAYS после тура, непроверенные сканы KYC — через KYC_PENDING_DAYS."""
    while True:
        try:
            async with pool().acquire() as conn:
                n = await safety.purge(conn)
                stale = await kyc.purge_stale(conn)
            if n or stale:
                log.info("purged %s safety forms, %s stale kyc submissions", n, stale)
        except Exception as e:  # не роняем приложение из-за фоновой задачи
            log.warning("safety purge failed: %s", e)
        await asyncio.sleep(6 * 3600)


async def _rates_loop():
    """Курсы валют: при старте и дальше каждые RATES_REFRESH_HOURS часов."""
    while True:
        try:
            async with pool().acquire() as conn:
                src = await rates.refresh(conn)
            log.info("exchange rates refreshed from %s", src)
        except Exception as e:
            log.warning("rates refresh failed: %s", e)
        await asyncio.sleep(RATES_REFRESH_HOURS * 3600)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_pool()
    tasks = [asyncio.create_task(_purge_loop()), asyncio.create_task(_rates_loop())]
    yield
    for task in tasks:
        task.cancel()
    await close_pool()


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="gp_session",
    max_age=60 * 60 * 24 * 30, same_site="lax", https_only=config.COOKIE_SECURE,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

for r in (public, auth, account, academy, api, contact, verify, moderation, analytics, tours, guides, requests, reviews, billing, dashboard):
    app.include_router(r.router)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, _exc):
    return redirect(f"/login?next={request.url.path}")


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    code = exc.status_code if exc.status_code in (403, 404, 409) else 400
    return await render(request, "error.html", status_code=exc.status_code, code=code)
