"""Воронка прямой брони: просмотр карточки гида → выбор даты → бронь → оплата депозита."""
import secrets

from fastapi import Request

from ..db import pool

BOTS = ("bot", "spider", "crawl", "headless", "curl", "python-")


def visitor(request: Request) -> str:
    """Анонимный id посетителя в сессии: шаги воронки считаются по уникальным посетителям."""
    v = request.session.get("vid")
    if not v:
        v = request.session["vid"] = secrets.token_hex(8)
    return v


async def track(request: Request, kind: str, guide_id: int | None, conn=None) -> None:
    ua = (request.headers.get("user-agent") or "").lower()
    if any(b in ua for b in BOTS):
        return
    await (conn or pool()).execute(
        "INSERT INTO funnel_events (kind, guide_id, visitor) VALUES ($1,$2,$3)", kind, guide_id, visitor(request)
    )
