from urllib.parse import urlsplit

from fastapi import APIRouter, Request

from ..auth import require_user
from ..config import UI_LANGS
from ..db import pool
from ..web import redirect, render

router = APIRouter()


def safe_referer(raw: str | None) -> str:
    if not raw:
        return "/"
    try:
        parts = urlsplit(raw)
        path = parts.path or "/"
        if parts.query:
            path += f"?{parts.query}"
        return path if path.startswith("/") and not path.startswith("//") else "/"
    except Exception:
        return "/"


@router.get("/health")
async def health():
    await pool().fetchval("SELECT 1")
    return {"status": "ok"}


@router.get("/")
async def index(request: Request):
    db = pool()
    top = await db.fetch(
        """SELECT u.id, u.name, u.rating, u.reviews_count, g.languages, g.level, g.completed_count
           FROM guides g JOIN users u ON u.id=g.user_id
           ORDER BY u.rating DESC NULLS LAST, g.completed_count DESC LIMIT 3"""
    )
    stats = await db.fetchrow(
        """SELECT (SELECT count(*) FROM guides) AS guides,
                  (SELECT count(*) FROM requests WHERE status='open') AS open_requests,
                  (SELECT count(DISTINCT l) FROM guides, unnest(languages) l) AS languages"""
    )
    return await render(request, "index.html", top=top, stats=stats)


@router.get("/lang/{code}")
async def set_lang(request: Request, code: str):
    back = safe_referer(request.headers.get("referer"))
    resp = redirect(back)
    if code in UI_LANGS:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="lax")
        uid = request.session.get("uid")
        if uid:
            await pool().execute("UPDATE users SET ui_lang=$2 WHERE id=$1", uid, code)
    return resp


@router.get("/notifications")
async def notifications(request: Request):
    user = await require_user(request)
    rows = await pool().fetch(
        "SELECT * FROM notifications WHERE user_id=$1 ORDER BY id DESC LIMIT 100", user["id"]
    )
    await pool().execute("UPDATE notifications SET is_read=TRUE WHERE user_id=$1", user["id"])
    return await render(request, "notifications.html", rows=rows)
