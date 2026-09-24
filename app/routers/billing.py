from fastapi import APIRouter, Request

from ..auth import current_user, require_user
from ..config import SEASON_PRICE, URGENT_PRICE
from ..db import pool
from ..services import payments
from ..web import flash, redirect, render

router = APIRouter()


@router.get("/pricing")
async def pricing(request: Request):
    user = await current_user(request)
    company = None
    if user and user["role"] == "company":
        company = await pool().fetchrow("SELECT * FROM companies WHERE user_id=$1", user["id"])
    return await render(request, "billing/pricing.html", company=company,
                        season_price=SEASON_PRICE, urgent_price=URGENT_PRICE)


@router.post("/billing/subscribe")
async def subscribe(request: Request):
    user = await require_user(request, "company")
    async with pool().acquire() as conn, conn.transaction():
        await payments.subscribe(conn, user["id"], SEASON_PRICE)
    flash(request, "billing.subscribed")
    return redirect("/requests")
