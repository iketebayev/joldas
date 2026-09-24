from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..auth import require_user
from ..config import GUIDE_LANGS
from ..db import pool
from .. import academy
from ..services import orders, route, safety
from ..services.payments import deposit_for
from ..web import flash, lang_of, redirect, render
from .guides import all_sites

router = APIRouter()


@router.get("/requests")
async def index(request: Request):
    user = await require_user(request)
    db = pool()
    if user["role"] == "admin":
        return redirect("/dashboard")
    if user["role"] == "guide":
        g = await db.fetchrow("SELECT * FROM guides WHERE user_id=$1", user["id"])
        feed = await db.fetch(
            """SELECT r.*, (SELECT count(*) FROM offers o WHERE o.request_id=r.id) AS offers_count,
                      EXISTS(SELECT 1 FROM offers o WHERE o.request_id=r.id AND o.guide_id=$1) AS offered
               FROM requests r
               WHERE r.status='open' AND r.date_from >= CURRENT_DATE AND r.region_id=$2 AND r.language = ANY($3::text[])
               ORDER BY r.urgent DESC, r.date_from""",
            user["id"], g["region_id"], g["languages"],
        )
        mine = await db.fetch(
            """SELECT a.*, r.date_from, r.date_to, r.language, r.site_ids
               FROM assignments a JOIN requests r ON r.id=a.request_id
               WHERE a.guide_id=$1 ORDER BY r.date_from DESC""",
            user["id"],
        )
        active = [a for a in mine if a["status"] in ("awaiting_payment", "confirmed")]
        history = [a for a in mine if a["status"] not in ("awaiting_payment", "confirmed")]
        return await render(request, "requests/guide_feed.html", g=g, feed=feed, active=active,
                            history=history[:5], history_total=len(history), sites=await all_sites())
    rows = await db.fetch(
        """SELECT r.*, (SELECT count(*) FROM offers o WHERE o.request_id=r.id AND o.status='pending') AS offers_count
           FROM requests r WHERE r.author_id=$1 ORDER BY r.created_at DESC""",
        user["id"],
    )
    company = None
    if user["role"] == "company":
        company = await db.fetchrow("SELECT * FROM companies WHERE user_id=$1", user["id"])
    return await render(request, "requests/mine.html", rows=rows, company=company,
                        sites=await all_sites())


@router.get("/requests/new")
async def new_form(request: Request):
    user = await require_user(request, "company", "tourist")
    if user["role"] == "company" and not await orders.company_can_post(pool(), user["id"]):
        flash(request, "billing.limit_reached", "error")
        return redirect("/pricing")
    return await render(request, "requests/new.html", sites=await all_sites())


@router.post("/requests/new")
async def create(request: Request):
    user = await require_user(request, "company", "tourist")
    form = await request.form()
    try:
        d_from = date.fromisoformat(form["date_from"])
        d_to = date.fromisoformat(form.get("date_to") or form["date_from"])
        price = int(str(form["price_per_day"]).replace(" ", ""))
        group = int(form.get("group_size") or 1)
    except (KeyError, ValueError):
        flash(request, "req.invalid", "error")
        return redirect("/requests/new")
    language = form.get("language")
    if d_to < d_from or d_from < date.today() or price <= 0 or group <= 0 or language not in GUIDE_LANGS:
        flash(request, "req.invalid", "error")
        return redirect("/requests/new")

    try:
        safety_data = safety.parse(form)
    except safety.SafetyError as e:
        flash(request, str(e), "error")
        return redirect("/requests/new")

    db = pool()
    async with db.acquire() as conn, conn.transaction():
        if user["role"] == "company" and not await orders.company_can_post(conn, user["id"]):
            flash(request, "billing.limit_reached", "error")
            return redirect("/pricing")
        region_id = await conn.fetchval("SELECT id FROM regions WHERE code='mangystau'")
        rid, notified = await orders.create_request(conn, user, {
            "region_id": region_id, "date_from": d_from, "date_to": d_to,
            "site_ids": [int(x) for x in form.getlist("site_ids") if str(x).isdigit()],
            "language": language, "group_size": group, "price_per_day": price,
            "note": (form.get("note") or "").strip() or None,
            "urgent": user["role"] == "company" and form.get("urgent") == "on",
        })
        await safety.save(conn, rid, safety_data)
    if notified:
        flash(request, "req.created_n", n=notified)
    else:
        flash(request, "req.created_none", "error")
    return redirect(f"/requests/{rid}")


async def load_assignment(aid: int):
    a = await pool().fetchrow("SELECT * FROM assignments WHERE id=$1", aid)
    if not a:
        raise HTTPException(404)
    return a


@router.get("/requests/{rid}")
async def detail(request: Request, rid: int):
    user = await require_user(request)
    db = pool()
    req = await db.fetchrow(
        """SELECT r.*, u.name AS author_name, u.rating AS author_rating,
                  u.reviews_count AS author_reviews, c.name AS company_name
           FROM requests r JOIN users u ON u.id=r.author_id
           LEFT JOIN companies c ON c.user_id=r.author_id WHERE r.id=$1""",
        rid,
    )
    if not req:
        raise HTTPException(404)
    is_owner = req["author_id"] == user["id"]
    assignment = await db.fetchrow(
        "SELECT * FROM assignments WHERE request_id=$1 ORDER BY (status='cancelled'), id DESC LIMIT 1", rid
    )
    is_assigned_guide = bool(assignment and assignment["guide_id"] == user["id"]
                             and assignment["status"] != "cancelled")
    my_offer = None
    if user["role"] == "guide":
        my_offer = await db.fetchrow(
            "SELECT * FROM offers WHERE request_id=$1 AND guide_id=$2", rid, user["id"]
        )
    if not (is_owner or user["role"] == "admin" or
            (user["role"] == "guide" and (req["status"] == "open" or my_offer or is_assigned_guide))):
        raise HTTPException(403)

    offers = []
    if is_owner or user["role"] == "admin":
        offers = await db.fetch(
            """SELECT o.*, u.name, u.rating, u.reviews_count, g.level, g.languages,
                      g.completed_count, g.experience_years
               FROM offers o JOIN users u ON u.id=o.guide_id JOIN guides g ON g.user_id=o.guide_id
               WHERE o.request_id=$1 AND o.status IN ('pending','chosen')
               ORDER BY (o.status='chosen') DESC, u.rating DESC NULLS LAST, g.completed_count DESC""",
            rid,
        )

    # Контакты открываются только после подтверждения.
    contacts, guide = None, None
    if assignment and assignment["status"] != "cancelled":
        guide = await db.fetchrow(
            """SELECT u.id, u.name, u.rating, u.reviews_count, g.level
               FROM users u JOIN guides g ON g.user_id=u.id WHERE u.id=$1""",
            assignment["guide_id"],
        )
        if assignment["status"] in ("confirmed", "done") and (is_owner or is_assigned_guide):
            other = assignment["guide_id"] if is_owner else assignment["client_id"]
            contacts = await db.fetchrow("SELECT name, phone, email FROM users WHERE id=$1", other)

    my_review = None
    if assignment and assignment["status"] == "done":
        my_review = await db.fetchrow(
            "SELECT id FROM reviews WHERE assignment_id=$1 AND author_id=$2", assignment["id"], user["id"]
        )
    deposit = deposit_for(assignment["total"]) if assignment else 0

    # Допуслуги: у каждого отклика — допы гида; у заказа — выбранные.
    offer_addons = {}
    if offers:
        for a in await db.fetch(
            "SELECT * FROM guide_addons WHERE active AND guide_id = ANY($1::int[]) ORDER BY price",
            [o["guide_id"] for o in offers],
        ):
            offer_addons.setdefault(a["guide_id"], []).append(a)
    chosen_addons = []
    if assignment:
        chosen_addons = await db.fetch(
            "SELECT * FROM assignment_addons WHERE assignment_id=$1 ORDER BY amount DESC", assignment["id"]
        )

    # Маршрут: объекты в порядке объезда из Актау и подтверждённые инциденты на них.
    lang = lang_of(request)
    route_sites = route.order([dict(x) for x in await all_sites() if x["id"] in req["site_ids"]])
    slugs = {x["slug"] for x in route_sites}
    incidents = [{**i, "text": i[lang]} for i in academy.INCIDENTS if i["site"] in slugs]

    # Анкета безопасности: страны видны всем, кто видит заявку; здоровье и ICE —
    # только автору и назначенному гиду после подтверждения. Акимату — не показываем.
    sf = await db.fetchrow("SELECT * FROM request_safety WHERE request_id=$1", rid)
    guide_confirmed = is_assigned_guide and assignment["status"] in ("confirmed", "done")
    show_health = bool(sf) and (is_owner or guide_confirmed)
    all_sites_rows = await all_sites()
    brief = safety.brief(req, sf, all_sites_rows, lang_of(request)) if (is_owner or guide_confirmed) else None
    return await render(
        request, "requests/detail.html", req=req, offers=offers, assignment=assignment,
        guide=guide, contacts=contacts, is_owner=is_owner, is_assigned_guide=is_assigned_guide,
        my_offer=my_offer, my_review=my_review, deposit=deposit, sites=all_sites_rows,
        sf=sf, show_health=show_health, brief=brief,
        offer_addons=offer_addons, chosen_addons=chosen_addons,
        route_sites=route_sites, incidents=incidents, aktau=route.AKTAU,
    )


@router.post("/requests/{rid}/offer")
async def offer(request: Request, rid: int):
    user = await require_user(request, "guide")
    form = await request.form()
    db = pool()
    req = await db.fetchrow("SELECT * FROM requests WHERE id=$1", rid)
    if not req:
        raise HTTPException(404)
    g = await db.fetchrow("SELECT languages FROM guides WHERE user_id=$1", user["id"])
    if req["language"] not in g["languages"]:
        raise HTTPException(403)
    if form.get("action") == "accept":
        price = req["price_per_day"]
    else:
        raw = str(form.get("price", "")).replace(" ", "")
        if not raw.isdigit() or int(raw) <= 0:
            flash(request, "req.invalid", "error")
            return redirect(f"/requests/{rid}")
        price = int(raw)
    async with db.acquire() as conn, conn.transaction():
        await orders.make_offer(conn, user, req, price, (form.get("message") or "").strip() or None)
    flash(request, "offer.sent")
    return redirect(f"/requests/{rid}")


@router.post("/offers/{oid}/choose")
async def choose(request: Request, oid: int):
    user = await require_user(request, "company", "tourist")
    form = await request.form()
    addon_ids = [int(x) for x in form.getlist("addon_ids") if str(x).isdigit()]
    db = pool()
    async with db.acquire() as conn, conn.transaction():
        await orders.choose_offer(conn, user, oid, addon_ids)
        rid = await conn.fetchval("SELECT request_id FROM offers WHERE id=$1", oid)
    flash(request, "offer.chosen_tourist" if user["role"] == "tourist" else "offer.chosen_company")
    return redirect(f"/requests/{rid}")


@router.post("/assignments/{aid}/pay")
async def pay(request: Request, aid: int):
    user = await require_user(request, "tourist")
    a = await load_assignment(aid)
    async with pool().acquire() as conn, conn.transaction():
        await orders.confirm_deposit(conn, user, a)
    flash(request, "pay.done")
    return redirect(f"/requests/{a['request_id']}")


@router.post("/assignments/{aid}/complete")
async def complete(request: Request, aid: int):
    user = await require_user(request, "company", "tourist")
    a = await load_assignment(aid)
    async with pool().acquire() as conn, conn.transaction():
        await orders.complete(conn, user, a)
    flash(request, "a.completed")
    return redirect(f"/assignments/{aid}/review")


@router.post("/assignments/{aid}/cancel")
async def cancel(request: Request, aid: int):
    user = await require_user(request)
    a = await load_assignment(aid)
    async with pool().acquire() as conn, conn.transaction():
        res = await orders.cancel(conn, user, a)
    if res["penalty"]:
        flash(request, "a.cancelled_guide", "error")
    elif res["refund"]:
        flash(request, "a.cancelled_refund", amount=f"{res['refund']:,}".replace(",", " "))
    elif user["role"] == "tourist" and a["status"] == "confirmed":
        flash(request, "a.cancelled_no_refund", "error")
    else:
        flash(request, "a.cancelled")
    return redirect(f"/requests/{a['request_id']}")


@router.post("/requests/{rid}/cancel")
async def cancel_request(request: Request, rid: int):
    user = await require_user(request)
    db = pool()
    req = await db.fetchrow("SELECT * FROM requests WHERE id=$1", rid)
    if not req or (req["author_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(403)
    if req["status"] != "open":
        raise HTTPException(409)
    async with db.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE requests SET status='cancelled' WHERE id=$1", rid)
        await conn.execute("UPDATE offers SET status='rejected' WHERE request_id=$1 AND status='pending'", rid)
    flash(request, "req.cancelled")
    return redirect(f"/requests/{rid}")


@router.get("/requests/{rid}/route.gpx")
async def route_gpx(request: Request, rid: int):
    user = await require_user(request)
    db = pool()
    req = await db.fetchrow("SELECT * FROM requests WHERE id=$1", rid)
    if not req:
        raise HTTPException(404)
    allowed = req["author_id"] == user["id"] or user["role"] == "admin" or (
        user["role"] == "guide" and (
            req["status"] == "open"
            or await db.fetchval("SELECT 1 FROM offers WHERE request_id=$1 AND guide_id=$2", rid, user["id"])))
    if not allowed:
        raise HTTPException(403)
    sites = route.order([dict(x) for x in await all_sites() if x["id"] in req["site_ids"]])
    body = route.gpx(f"Tour #{rid}", sites, lang_of(request))
    return Response(body, media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="tour-{rid}.gpx"'})
