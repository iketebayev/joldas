from fastapi import APIRouter, HTTPException, Request

from ..auth import require_user
from ..config import GUIDE_LANGS, SPECIALIZATIONS
from ..db import pool
from ..web import flash, redirect, render

router = APIRouter()

LEVEL_FILTER = {"experienced": ("experienced", "expert"), "expert": ("expert",)}


async def all_sites():
    return await pool().fetch("SELECT * FROM sites ORDER BY name_ru")


@router.get("/guides")
async def catalog(request: Request, language: str = "", spec: str = "", level: str = "",
                  site: int | None = None):
    where, args = ["TRUE"], []
    if language in GUIDE_LANGS:
        args.append(language); where.append(f"${len(args)} = ANY(g.languages)")
    if spec in SPECIALIZATIONS:
        args.append(spec); where.append(f"${len(args)} = ANY(g.specializations)")
    if level in LEVEL_FILTER:
        args.append(list(LEVEL_FILTER[level])); where.append(f"g.level = ANY(${len(args)}::text[])")
    if site:
        args.append(site); where.append(f"${len(args)} = ANY(g.site_ids)")
    rows = await pool().fetch(
        f"""SELECT u.id, u.name, u.rating, u.reviews_count, u.is_demo, g.*
            FROM guides g JOIN users u ON u.id=g.user_id
            WHERE {' AND '.join(where)}
            ORDER BY u.rating DESC NULLS LAST, g.completed_count DESC, u.reviews_count DESC""",
        *args,
    )
    return await render(request, "guides/list.html", rows=rows, sites=await all_sites(),
                        f={"language": language, "spec": spec, "level": level, "site": site})


async def guide_reviews(guide_id: int):
    return await pool().fetch(
        """SELECT r.*, a.request_id, u.name AS author_name, u.role AS author_role
           FROM reviews r JOIN assignments a ON a.id=r.assignment_id
           LEFT JOIN users u ON u.id=r.author_id
           WHERE r.target_id=$1 AND r.target_role='guide' AND NOT r.hidden
           ORDER BY r.created_at DESC""",
        guide_id,
    )


@router.get("/guides/{guide_id}")
async def profile(request: Request, guide_id: int):
    db = pool()
    g = await db.fetchrow(
        """SELECT u.id, u.name, u.rating, u.reviews_count, u.is_demo, g.*
           FROM guides g JOIN users u ON u.id=g.user_id WHERE u.id=$1""",
        guide_id,
    )
    if not g:
        raise HTTPException(404)
    reviews = await guide_reviews(guide_id)
    criteria = await db.fetchrow(
        """SELECT avg(c_route) AS route, avg(c_language) AS language,
                  avg(c_punctuality) AS punctuality, avg(c_communication) AS communication
           FROM reviews WHERE target_id=$1 AND target_role='guide' AND NOT hidden AND NOT is_system""",
        guide_id,
    )
    sites = [s for s in await all_sites() if s["id"] in g["site_ids"]]
    return await render(request, "guides/profile.html", g=g, reviews=reviews,
                        criteria=criteria, sites=sites)


@router.get("/profile")
async def edit_form(request: Request):
    user = await require_user(request, "guide")
    g = await pool().fetchrow("SELECT * FROM guides WHERE user_id=$1", user["id"])
    return await render(request, "guides/edit.html", g=g, sites=await all_sites())


@router.post("/profile")
async def edit(request: Request):
    user = await require_user(request, "guide")
    form = await request.form()

    def ints(key):
        return [int(v) for v in form.getlist(key) if str(v).isdigit()]

    def num(key):
        v = str(form.get(key, "")).replace(" ", "")
        return int(v) if v.isdigit() else None

    await pool().execute(
        """UPDATE guides SET languages=$2, specializations=$3, site_ids=$4, day_rate=$5,
               experience_years=$6, bio=$7, external_links=$8 WHERE user_id=$1""",
        user["id"],
        [x for x in form.getlist("languages") if x in GUIDE_LANGS],
        [x for x in form.getlist("specializations") if x in SPECIALIZATIONS],
        ints("site_ids"), num("day_rate"), num("experience_years"),
        (form.get("bio") or "").strip() or None,
        (form.get("external_links") or "").strip() or None,
    )
    flash(request, "profile.saved")
    return redirect("/profile")
