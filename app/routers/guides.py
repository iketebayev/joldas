from fastapi import APIRouter, HTTPException, Request

from ..auth import current_user, require_user
from ..config import ADDON_KINDS, APP_NAME, CONTACT_REDIRECT_URL, GUIDE_LANGS, KYC_REQUIRED, SPECIALIZATIONS
from ..db import pool
from ..services import contact
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
async def profile(request: Request, guide_id: int, region: str = ""):
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
    # Связь до бронирования: порядок каналов под регион туриста (можно переключить вручную).
    lang = lang_of(request)
    if region not in contact.REGIONS:
        region = await contact.region_of(await current_user(request), lang)
    greet_lang = contact.greeting_lang(region, lang, g["languages"])
    return await render(request, "guides/profile.html", g=g, reviews=reviews,
                        criteria=criteria, sites=sites, addons=await guide_addons(guide_id),
                        channels=contact.channels(g, region), region=region, regions=contact.REGIONS,
                        greeting=contact.GREETING[greet_lang].format(app=APP_NAME),
                        demo_contacts=bool(CONTACT_REDIRECT_URL),
                        phone=contact.fmt_phone(g["whatsapp"] or await db.fetchval("SELECT phone FROM users WHERE id=$1", guide_id)))


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
               whatsapp=$9, instagram=$10, rednote_id=$11, rednote_link=$12, x_handle=$13
           WHERE user_id=$1""",
        user["id"],
        [x for x in form.getlist("languages") if x in GUIDE_LANGS],
        [x for x in form.getlist("specializations") if x in SPECIALIZATIONS],
        ints("site_ids"), num("day_rate"), num("experience_years"),
        (form.get("bio") or "").strip() or None,
        (form.get("external_links") or "").strip() or None,
        contact.norm_phone(form.get("whatsapp")), contact.norm_handle(form.get("instagram")),
        contact.norm_rednote_id(form.get("rednote_id")), contact.norm_rednote_link(form.get("rednote_link")),
        contact.norm_handle(form.get("x_handle")),
    )
    flash(request, "profile.saved")
    return redirect("/profile")
