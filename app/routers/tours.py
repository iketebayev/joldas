"""Готовые туры турагентств: витрина, бронирование, кабинет агентства.

Туры видны, только пока у агентства активен тариф «Сезон» — это часть подписки.
Комиссии с брони нет: агентство платит подпиской."""
from datetime import date

from fastapi import APIRouter, HTTPException, Request

from ..auth import current_user, require_user
from ..config import GUIDE_LANGS, TOUR_INCLUDES
from ..db import pool
from ..services import fees
from ..services.notify import notify
from ..web import flash, lang_of, redirect, render
from .guides import all_sites

router = APIRouter()

VISIBLE = """t.active AND c.plan='season' AND (c.plan_until IS NULL OR c.plan_until >= current_date)"""
SELECT = f"""SELECT t.*, c.name AS agency, u.rating AS agency_rating, u.reviews_count AS agency_reviews
             FROM tours t JOIN companies c ON c.user_id=t.company_id JOIN users u ON u.id=t.company_id"""


async def visible_tours(site_ids: list[int] | None = None, language: str | None = None, limit: int = 50):
    where, args = [VISIBLE], []
    if site_ids:
        args.append(site_ids); where.append(f"t.site_ids && ${len(args)}::int[]")
    if language in GUIDE_LANGS:
        args.append(language); where.append(f"${len(args)} = ANY(t.languages)")
    return await pool().fetch(
        f"{SELECT} WHERE {' AND '.join(where)} ORDER BY u.rating DESC NULLS LAST, t.price_per_person LIMIT {limit}",
        *args,
    )


@router.get("/tours")
async def catalog(request: Request, site: int | None = None, language: str = ""):
    tours = await visible_tours([site] if site else None, language or None)
    return await render(request, "tours/list.html", tours=tours, sites=await all_sites(),
                        f={"site": site, "language": language})


@router.get("/api/tours")
async def api_tours(request: Request, sites: str = "", language: str = ""):
    """Для формы заявки: туры по выбранным объектам и языку; если нет — по объектам, потом любые."""
    site_ids = [int(x) for x in sites.split(",") if x.strip().isdigit()]
    tours = await visible_tours(site_ids or None, language or None, 6)
    if not tours and language:
        tours = await visible_tours(site_ids or None, None, 6)
    if not tours:
        tours = await visible_tours(None, None, 6)
    names = {s["id"]: s for s in await all_sites()}
    lang = lang_of(request)
    return [{"id": t["id"], "title": t["title"], "agency": t["agency"], "days": t["days"],
             "price": t["price_per_person"], "rating": float(t["agency_rating"]) if t["agency_rating"] else None,
             "includes": t["includes"], "languages": t["languages"],
             "sites": [names[i][f"name_{lang}"] for i in t["site_ids"] if i in names]} for t in tours]


@router.get("/tours/mine")
async def mine(request: Request):
    user = await require_user(request, "company")
    db = pool()
    company = await db.fetchrow("SELECT * FROM companies WHERE user_id=$1", user["id"])
    tours = await db.fetch("SELECT * FROM tours WHERE company_id=$1 ORDER BY active DESC, id DESC", user["id"])
    bookings = await db.fetch(
        """SELECT b.*, t.title, u.name AS tourist, u.phone, u.email
           FROM tour_bookings b JOIN tours t ON t.id=b.tour_id JOIN users u ON u.id=b.tourist_id
           WHERE t.company_id=$1 ORDER BY (b.status='pending') DESC, b.date_from""",
        user["id"],
    )
    active_plan = company["plan"] == "season" and (company["plan_until"] is None or company["plan_until"] >= date.today())
    return await render(request, "tours/mine.html", tours=tours, bookings=bookings,
                        active_plan=active_plan, sites=await all_sites(), includes=TOUR_INCLUDES)


@router.post("/tours/mine")
async def create(request: Request):
    user = await require_user(request, "company")
    form = await request.form()

    def num(key):
        v = str(form.get(key, "")).replace(" ", "")
        return int(v) if v.isdigit() else 0

    title = (form.get("title") or "").strip()
    days, price, max_group = num("days"), num("price_per_person"), num("max_group") or 8
    if not title or not (1 <= days <= 30) or price <= 0:
        flash(request, "tour.invalid", "error")
        return redirect("/tours/mine")
    await pool().execute(
        """INSERT INTO tours (company_id, title, description, days, price_per_person, languages,
               site_ids, includes, max_group) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        user["id"], title, (form.get("description") or "").strip() or None, days, price,
        [x for x in form.getlist("languages") if x in GUIDE_LANGS],
        [int(x) for x in form.getlist("site_ids") if str(x).isdigit()],
        [x for x in form.getlist("includes") if x in TOUR_INCLUDES], max_group,
    )
    flash(request, "tour.created")
    return redirect("/tours/mine")


@router.post("/tours/{tid}/toggle")
async def toggle(request: Request, tid: int):
    user = await require_user(request, "company")
    await pool().execute("UPDATE tours SET active = NOT active WHERE id=$1 AND company_id=$2", tid, user["id"])
    return redirect("/tours/mine")


@router.get("/tours/{tid}")
async def detail(request: Request, tid: int):
    t = await pool().fetchrow(f"{SELECT} WHERE t.id=$1", tid)
    user = await current_user(request)
    # Чужой неактивный тур не показываем; своё агентство видит всегда.
    if not t or (not (user and user["id"] == t["company_id"]) and not await pool().fetchval(
            f"SELECT 1 FROM tours t JOIN companies c ON c.user_id=t.company_id WHERE t.id=$1 AND {VISIBLE}", tid)):
        raise HTTPException(404)
    sites = [s for s in await all_sites() if s["id"] in t["site_ids"]]
    park = fees.compute([s["slug"] for s in sites], 1, t["days"]) if "entry_fee" not in t["includes"] else None
    return await render(request, "tours/detail.html", tour=t, sites=sites, park=park)


@router.post("/tours/{tid}/book")
async def book(request: Request, tid: int):
    user = await require_user(request, "tourist")
    form = await request.form()
    t = await pool().fetchrow(
        f"SELECT t.* FROM tours t JOIN companies c ON c.user_id=t.company_id WHERE t.id=$1 AND {VISIBLE}", tid)
    if not t:
        raise HTTPException(404)
    try:
        d = date.fromisoformat(form.get("date_from") or "")
        group = int(form.get("group_size") or 0)
    except ValueError:
        d, group = None, 0
    if not d or d < date.today() or not (1 <= group <= t["max_group"]):
        flash(request, "tour.book_invalid", "error", max=t["max_group"])
        return redirect(f"/tours/{tid}")
    async with pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tour_bookings (tour_id, tourist_id, date_from, group_size, total) VALUES ($1,$2,$3,$4,$5)",
            tid, user["id"], d, group, t["price_per_person"] * group,
        )
        await notify(conn, t["company_id"], "n.tour_booked", "/tours/mine", title=t["title"])
    flash(request, "tour.booked")
    return redirect("/requests")


async def _booking_for_company(user, bid: int):
    b = await pool().fetchrow(
        "SELECT b.*, t.company_id, t.title FROM tour_bookings b JOIN tours t ON t.id=b.tour_id WHERE b.id=$1", bid)
    if not b or b["company_id"] != user["id"]:
        raise HTTPException(404)
    if b["status"] != "pending":
        raise HTTPException(409)
    return b


@router.post("/bookings/{bid}/{action}")
async def booking_action(request: Request, bid: int, action: str):
    user = await require_user(request)
    if action in ("confirm", "decline") and user["role"] == "company":
        b = await _booking_for_company(user, bid)
        status = "confirmed" if action == "confirm" else "declined"
        async with pool().acquire() as conn, conn.transaction():
            await conn.execute("UPDATE tour_bookings SET status=$2 WHERE id=$1", bid, status)
            await notify(conn, b["tourist_id"], f"n.tour_{status}", "/requests", title=b["title"])
        return redirect("/tours/mine")
    if action == "cancel" and user["role"] == "tourist":
        n = await pool().execute(
            "UPDATE tour_bookings SET status='cancelled' WHERE id=$1 AND tourist_id=$2 AND status IN ('pending','confirmed')",
            bid, user["id"])
        if n.endswith(" 0"):
            raise HTTPException(409)
        return redirect("/requests")
    raise HTTPException(403)
