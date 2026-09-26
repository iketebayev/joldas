from datetime import date

from fastapi import APIRouter, HTTPException, Request

from ..auth import current_user, require_user
from ..config import (ADDON_KINDS, CALENDAR_DAYS, CHANNELS, CONTACT_REDIRECT_URL, DIRECT_MAX_DAYS, GUIDE_LANGS,
                      KYC_REQUIRED, SPECIALIZATIONS)
from ..db import pool
from ..services import booking, contact, funnel, orders
from ..web import flash, lang_of, redirect, render

router = APIRouter()

LEVEL_FILTER = {"experienced": ("experienced", "expert"), "expert": ("expert",)}


# Одобренная видеовизитка и подтверждённые по видео языки — для каталога и профиля.
MEDIA_COLS = """, v.token AS video_token, v.lang AS video_lang, v.level AS video_level,
    (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(v.subtitles) k) AS video_subs,
    (SELECT array_agg(l.lang || ':' || l.level ORDER BY l.lang) FROM guide_lang_levels l
      WHERE l.guide_id = u.id) AS verified_langs"""
MEDIA_JOIN = """LEFT JOIN LATERAL (SELECT * FROM guide_videos gv WHERE gv.guide_id = u.id AND gv.status = 'approved'
    ORDER BY gv.id DESC LIMIT 1) v ON TRUE"""


# Контакты гида — приватные поля: в шаблон публичных страниц не передаются вообще.
PRIVATE = ("whatsapp", "telegram", "instagram", "rednote_id", "rednote_link", "x_handle")


def public(row) -> dict:
    return {k: v for k, v in dict(row).items() if k not in PRIVATE}


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
        f"""SELECT u.id, u.name, u.rating, u.reviews_count, u.is_demo, g.* {MEDIA_COLS}
            FROM guides g JOIN users u ON u.id=g.user_id {MEDIA_JOIN}
            WHERE {' AND '.join(where)}
            ORDER BY u.rating DESC NULLS LAST, g.completed_count DESC, u.reviews_count DESC""",
        *args,
    )
    return await render(request, "guides/list.html", rows=[public(r) for r in rows], sites=await all_sites(),
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
        f"""SELECT u.id, u.name, u.rating, u.reviews_count, u.is_demo, g.* {MEDIA_COLS}
           FROM guides g JOIN users u ON u.id=g.user_id {MEDIA_JOIN} WHERE u.id=$1""",
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
    user = await current_user(request)
    if not user or user["id"] != guide_id:
        await funnel.track(request, "view", guide_id)
    # Контакты — только клиенту с оплаченным депозитом по брони у этого гида.
    unlocked = contacts = None
    if user:
        unlocked = await booking.unlocked_for(db, user["id"], guide_id)
        if unlocked:
            contacts = await booking.guide_contacts(db, g, unlocked, user, lang_of(request))
    start = date.today()
    busy = await booking.busy_dates(db, guide_id, start)
    return await render(request, "guides/profile.html", g=public(g), reviews=reviews,
                        criteria=criteria, sites=sites, addons=await guide_addons(guide_id),
                        unlocked=unlocked, contacts=contacts,
                        rednote_id=g["rednote_id"] if contacts else None,
                        busy=[d.isoformat() for d in busy], cal_start=start, cal_days=CALENDAR_DAYS,
                        max_days=DIRECT_MAX_DAYS,
                        channel_kinds=[c for c in CHANNELS if CONTACT_REDIRECT_URL or g[
                            {"x": "x_handle", "rednote": "rednote_id"}.get(c, c)]])


@router.post("/guides/{guide_id}/book")
async def book(request: Request, guide_id: int):
    """Прямая бронь из профиля: даты → цена по ставке гида → заказ ждёт депозита 10%."""
    user = await require_user(request, "tourist")
    form = await request.form()
    db = pool()
    g = await db.fetchrow("SELECT * FROM guides WHERE user_id=$1", guide_id)
    if not g or not g["day_rate"] or not g["id_verified_at"]:
        raise HTTPException(404)
    try:
        d_from = date.fromisoformat(str(form.get("date_from")))
        d_to = date.fromisoformat(str(form.get("date_to") or form.get("date_from")))
        group = int(form.get("group_size") or 0)
    except ValueError:
        flash(request, "book.invalid", "error")
        return redirect(f"/guides/{guide_id}#book")
    lang = form.get("language")
    days = (d_to - d_from).days + 1
    if d_from < date.today() or not 1 <= days <= DIRECT_MAX_DAYS or not 1 <= group <= 30 or lang not in g["languages"]:
        flash(request, "book.invalid", "error")
        return redirect(f"/guides/{guide_id}#book")
    site_ids = [int(x) for x in form.getlist("site_ids") if str(x).isdigit() and int(x) in g["site_ids"]]
    try:
        async with db.acquire() as conn, conn.transaction():
            region = await conn.fetchval("SELECT id FROM regions WHERE code='mangystau'")
            rid = await conn.fetchval(
                """INSERT INTO requests (author_id, author_type, region_id, date_from, date_to, site_ids,
                       language, group_size, price_per_day, note, direct)
                   VALUES ($1,'tourist',$2,$3,$4,$5,$6,$7,$8,$9,TRUE) RETURNING id""",
                user["id"], region, d_from, d_to, site_ids, lang, group, g["day_rate"],
                (form.get("note") or "").strip()[:500] or None,
            )
            oid = await conn.fetchval(
                """INSERT INTO offers (request_id, guide_id, price_per_day, status)
                   VALUES ($1,$2,$3,'pending') RETURNING id""", rid, guide_id, g["day_rate"],
            )
            addon_ids = [int(x) for x in form.getlist("addon_ids") if str(x).isdigit()]
            await orders.choose_offer(conn, user, oid, addon_ids)
            await funnel.track(request, "booking", guide_id, conn)
    except HTTPException as e:
        if e.status_code == 409:
            flash(request, "book.busy", "error")
            return redirect(f"/guides/{guide_id}#book")
        raise
    flash(request, "book.created")
    return redirect(f"/requests/{rid}#pay")


async def guide_addons(guide_id: int):
    return await pool().fetch(
        "SELECT * FROM guide_addons WHERE guide_id=$1 AND active ORDER BY price", guide_id
    )


@router.get("/profile")
async def edit_form(request: Request):
    user = await require_user(request, "guide")
    db = pool()
    g = await db.fetchrow("SELECT * FROM guides WHERE user_id=$1", user["id"])
    # Онбординг: профиль → проверка личности → видеовизитка.
    kyc = await db.fetchrow("SELECT status FROM guide_kyc WHERE guide_id=$1 ORDER BY id DESC LIMIT 1", user["id"])
    vid = await db.fetchrow(
        "SELECT status FROM guide_videos WHERE guide_id=$1 AND status<>'replaced' ORDER BY id DESC LIMIT 1", user["id"]
    )
    return await render(request, "guides/edit.html", g=g, sites=await all_sites(),
                        addons=await guide_addons(user["id"]), kyc=kyc, vid=vid, kyc_required=KYC_REQUIRED)


@router.post("/profile/addons")
async def addon_save(request: Request):
    user = await require_user(request, "guide")
    form = await request.form()
    kind, per = form.get("kind"), form.get("per")
    raw = str(form.get("price", "")).replace(" ", "")
    if kind not in ADDON_KINDS or per not in ("tour", "person") or not raw.isdigit() or int(raw) <= 0:
        flash(request, "addon.invalid", "error")
        return redirect("/profile#addons")
    await pool().execute(
        """INSERT INTO guide_addons (guide_id, kind, price, per) VALUES ($1,$2,$3,$4)
           ON CONFLICT (guide_id, kind) DO UPDATE SET price=EXCLUDED.price, per=EXCLUDED.per, active=TRUE""",
        user["id"], kind, int(raw), per,
    )
    flash(request, "addon.saved")
    return redirect("/profile#addons")


@router.post("/profile/addons/{addon_id}/delete")
async def addon_delete(request: Request, addon_id: int):
    user = await require_user(request, "guide")
    await pool().execute(
        "UPDATE guide_addons SET active=FALSE WHERE id=$1 AND guide_id=$2", addon_id, user["id"]
    )
    flash(request, "addon.deleted")
    return redirect("/profile#addons")


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
               experience_years=$6, bio=$7, external_links=$8,
               whatsapp=$9, instagram=$10, rednote_id=$11, rednote_link=$12, x_handle=$13,
               telegram=$14, vehicle_details=$15
           WHERE user_id=$1""",
        user["id"],
        [x for x in form.getlist("languages") if x in GUIDE_LANGS],
        [x for x in form.getlist("specializations") if x in SPECIALIZATIONS],
        ints("site_ids"), num("day_rate"), num("experience_years"),
        (form.get("bio") or "").strip() or None,
        (form.get("external_links") or "").strip() or None,
        contact.norm_phone(form.get("whatsapp")), contact.norm_handle(form.get("instagram")),
        contact.norm_rednote_id(form.get("rednote_id")), contact.norm_rednote_link(form.get("rednote_link")),
        contact.norm_handle(form.get("x_handle")), contact.norm_handle(form.get("telegram"), tg=True),
        (form.get("vehicle_details") or "").strip()[:200] or None,
    )
    flash(request, "profile.saved")
    return redirect("/profile")
