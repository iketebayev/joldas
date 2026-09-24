import asyncpg
from fastapi import APIRouter, Request

from ..auth import check_password, hash_password, require_user
from ..config import UI_LANGS
from ..db import pool
from ..web import flash, redirect, render
from .auth import normalize_phone

router = APIRouter()


@router.get("/account")
async def account(request: Request):
    user = await require_user(request)
    company = None
    if user["role"] == "company":
        company = await pool().fetchrow("SELECT * FROM companies WHERE user_id=$1", user["id"])
    return await render(request, "account.html", company=company)


@router.post("/account")
async def save(request: Request):
    user = await require_user(request)
    form = await request.form()
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip().lower() or None
    phone = normalize_phone(form.get("phone"))
    ui_lang = form.get("ui_lang") if form.get("ui_lang") in UI_LANGS else user["ui_lang"]
    if not name or not (email or phone):
        flash(request, "account.need_contact", "error")
        return redirect("/account")
    async with pool().acquire() as conn, conn.transaction():
        try:
            await conn.execute(
                "UPDATE users SET name=$2, email=$3, phone=$4, ui_lang=$5 WHERE id=$1",
                user["id"], name, email, phone, ui_lang,
            )
        except asyncpg.UniqueViolationError:
            flash(request, "auth.exists", "error")
            return redirect("/account")
        if user["role"] == "company" and (form.get("company_name") or "").strip():
            await conn.execute(
                "UPDATE companies SET name=$2 WHERE user_id=$1", user["id"], form["company_name"].strip()
            )
    flash(request, "account.saved")
    resp = redirect("/account")
    resp.set_cookie("lang", ui_lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@router.post("/account/password")
async def password(request: Request):
    user = await require_user(request)
    form = await request.form()
    current = form.get("current_password") or ""
    new = form.get("new_password") or ""
    confirm = form.get("confirm_password") or ""
    if not check_password(current, user["password_hash"]):
        flash(request, "account.wrong_password", "error")
    elif len(new) < 6:
        flash(request, "auth.password_hint", "error")
    elif confirm and new != confirm:
        flash(request, "account.passwords_differ", "error")
    else:
        await pool().execute("UPDATE users SET password_hash=$2 WHERE id=$1", user["id"], hash_password(new))
        flash(request, "account.password_changed")
    return redirect("/account")
