import re

import asyncpg
from fastapi import APIRouter, Form, Request

from ..auth import check_password, hash_password
from ..db import pool
from ..web import flash, lang_of, redirect, render

router = APIRouter()

ROLES = ("guide", "company", "tourist")


def normalize_phone(raw: str | None) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return "+" + digits


def safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/requests"


@router.get("/login")
async def login_form(request: Request, next: str | None = None):
    return await render(request, "auth/login.html", next=safe_next(next))


@router.post("/login")
async def login(request: Request, login: str = Form(...), password: str = Form(...),
                next: str | None = Form(None)):
    ident = login.strip().lower()
    user = await pool().fetchrow(
        "SELECT * FROM users WHERE lower(email)=$1 OR phone=$2", ident, normalize_phone(ident)
    )
    if not user or not check_password(password, user["password_hash"]):
        flash(request, "auth.bad_login", "error")
        return redirect(f"/login?next={safe_next(next)}")
    request.session["uid"] = user["id"]
    resp = redirect(safe_next(next))
    resp.set_cookie("lang", user["ui_lang"], max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return redirect("/")


@router.get("/register")
async def register_form(request: Request, role: str = "tourist"):
    return await render(request, "auth/register.html", role=role if role in ROLES else "tourist")


@router.post("/register")
async def register(request: Request, role: str = Form(...), name: str = Form(...),
                   email: str = Form(""), phone: str = Form(""), password: str = Form(...),
                   company_name: str = Form("")):
    if role not in ROLES:
        role = "tourist"
    email = email.strip().lower() or None
    phone = normalize_phone(phone)
    if not (email or phone) or len(password) < 6 or not name.strip():
        flash(request, "auth.fill_required", "error")
        return redirect(f"/register?role={role}")

    db = pool()
    region_id = await db.fetchval("SELECT id FROM regions WHERE code='mangystau'")
    async with db.acquire() as conn, conn.transaction():
        try:
            uid = await conn.fetchval(
                """INSERT INTO users (role, name, email, phone, password_hash, ui_lang)
                   VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
                role, name.strip(), email, phone, hash_password(password), lang_of(request),
            )
        except asyncpg.UniqueViolationError:
            flash(request, "auth.exists", "error")
            return redirect(f"/register?role={role}")
        if role == "guide":
            await conn.execute("INSERT INTO guides (user_id, region_id) VALUES ($1,$2)", uid, region_id)
        elif role == "company":
            await conn.execute(
                "INSERT INTO companies (user_id, region_id, name) VALUES ($1,$2,$3)",
                uid, region_id, company_name.strip() or name.strip(),
            )
    request.session["uid"] = uid
    flash(request, "auth.welcome")
    return redirect("/profile" if role == "guide" else "/requests")
