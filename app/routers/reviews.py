from fastapi import APIRouter, HTTPException, Request

from ..auth import require_user
from ..db import pool
from ..services import rating
from ..services.notify import notify
from ..web import flash, redirect, render

router = APIRouter()
CRITERIA = ("c_route", "c_language", "c_punctuality", "c_communication")


def score(v) -> int | None:
    return int(v) if str(v) in ("1", "2", "3", "4", "5") else None


async def reviewable(user, aid: int):
    """Отзыв можно оставить только по своему выполненному заказу и только один раз."""
    a = await pool().fetchrow("SELECT * FROM assignments WHERE id=$1", aid)
    if not a or a["status"] != "done" or user["id"] not in (a["client_id"], a["guide_id"]):
        raise HTTPException(403)
    exists = await pool().fetchval(
        "SELECT 1 FROM reviews WHERE assignment_id=$1 AND author_id=$2", aid, user["id"]
    )
    return a, bool(exists)


@router.get("/assignments/{aid}/review")
async def form(request: Request, aid: int):
    user = await require_user(request)
    a, exists = await reviewable(user, aid)
    if exists:
        flash(request, "review.already")
        return redirect(f"/requests/{a['request_id']}")
    about_guide = user["id"] == a["client_id"]
    target = await pool().fetchrow(
        "SELECT name FROM users WHERE id=$1", a["guide_id"] if about_guide else a["client_id"]
    )
    return await render(request, "reviews/form.html", a=a, about_guide=about_guide,
                        target=target, criteria=CRITERIA)


@router.post("/assignments/{aid}/review")
async def submit(request: Request, aid: int):
    user = await require_user(request)
    a, exists = await reviewable(user, aid)
    if exists:
        raise HTTPException(409)
    form = await request.form()
    overall = score(form.get("overall"))
    if overall is None:
        flash(request, "review.need_score", "error")
        return redirect(f"/assignments/{aid}/review")
    about_guide = user["id"] == a["client_id"]
    crit = [score(form.get(c)) if about_guide else None for c in CRITERIA]
    target_id = a["guide_id"] if about_guide else a["client_id"]
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute(
            """INSERT INTO reviews (assignment_id, author_id, target_id, target_role, overall,
                   c_route, c_language, c_punctuality, c_communication, text)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
            aid, user["id"], target_id, "guide" if about_guide else "client", overall,
            *crit, (form.get("text") or "").strip() or None,
        )
        await rating.recompute_all(conn)
        link = f"/guides/{target_id}" if about_guide else f"/requests/{a['request_id']}"
        await notify(conn, target_id, "n.new_review", link, stars=overall)
    flash(request, "review.thanks")
    return redirect(f"/requests/{a['request_id']}")


@router.post("/reviews/{rev_id}/reply")
async def reply(request: Request, rev_id: int):
    user = await require_user(request, "guide")
    form = await request.form()
    text = (form.get("reply") or "").strip()
    rev = await pool().fetchrow("SELECT * FROM reviews WHERE id=$1", rev_id)
    if not rev or rev["target_id"] != user["id"] or rev["reply"] or rev["is_system"] or not text:
        raise HTTPException(403)
    await pool().execute("UPDATE reviews SET reply=$2, reply_at=now() WHERE id=$1", rev_id, text)
    flash(request, "review.replied")
    return redirect(f"/guides/{user['id']}")


@router.post("/reviews/{rev_id}/report")
async def report(request: Request, rev_id: int):
    user = await require_user(request)
    form = await request.form()
    rev = await pool().fetchrow("SELECT target_id FROM reviews WHERE id=$1", rev_id)
    if not rev:
        raise HTTPException(404)
    await pool().execute(
        """INSERT INTO review_reports (review_id, reporter_id, reason) VALUES ($1,$2,$3)
           ON CONFLICT DO NOTHING""",
        rev_id, user["id"], (form.get("reason") or "").strip() or None,
    )
    flash(request, "review.reported")
    return redirect(f"/guides/{rev['target_id']}")


@router.post("/reviews/{rev_id}/hide")
async def hide(request: Request, rev_id: int):
    await require_user(request, "admin")
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute("UPDATE reviews SET hidden=TRUE WHERE id=$1", rev_id)
        await conn.execute("UPDATE review_reports SET resolved=TRUE WHERE review_id=$1", rev_id)
        await rating.recompute_all(conn)
    flash(request, "review.hidden")
    return redirect("/dashboard#reports")
