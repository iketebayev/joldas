"""Жизненный цикл заказа: заявка → отклики → выбор → (депозит) → выполнено / отмена."""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException

from ..config import CANCEL_REFUND_HOURS, START_PLAN_MONTHLY_REQUESTS
from . import booking, fees, payments, rating
from .notify import notify

AQTAU = timezone(timedelta(hours=5))
TOUR_START = time(9, 0)


def tour_start(d: date) -> datetime:
    return datetime.combine(d, TOUR_START, tzinfo=AQTAU)


async def company_can_post(conn, company_id: int) -> bool:
    c = await conn.fetchrow("SELECT plan, plan_until FROM companies WHERE user_id=$1", company_id)
    if c and c["plan"] == "season" and (c["plan_until"] is None or c["plan_until"] >= date.today()):
        return True
    used = await conn.fetchval(
        """SELECT count(*) FROM requests WHERE author_id=$1
           AND date_trunc('month', created_at) = date_trunc('month', now())""",
        company_id,
    )
    return used < START_PLAN_MONTHLY_REQUESTS


async def matching_guides(conn, req) -> list:
    """Гиды региона с нужным языком, не занятые на эти даты."""
    return await conn.fetch(
        """SELECT u.id FROM guides g JOIN users u ON u.id=g.user_id
           WHERE g.region_id=$1 AND $2 = ANY(g.languages)
             AND NOT EXISTS (
               SELECT 1 FROM assignments a JOIN requests r ON r.id=a.request_id
               WHERE a.guide_id=u.id AND a.status IN ('awaiting_payment','confirmed')
                 AND r.date_from <= $4 AND r.date_to >= $3)""",
        req["region_id"], req["language"], req["date_from"], req["date_to"],
    )


async def create_request(conn, author, data: dict) -> int:
    rid = await conn.fetchval(
        """INSERT INTO requests (author_id, author_type, region_id, date_from, date_to,
               site_ids, language, group_size, price_per_day, note, urgent)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
        author["id"], author["role"], data["region_id"], data["date_from"], data["date_to"],
        data["site_ids"], data["language"], data["group_size"], data["price_per_day"],
        data.get("note"), data.get("urgent", False),
    )
    req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1", rid)
    guides = await matching_guides(conn, req)
    for g in guides:
        await notify(conn, g["id"], "n.new_request", f"/requests/{rid}",
                     lang_code=req["language"].upper(), date=req["date_from"].strftime("%d.%m"),
                     price=f"{req['price_per_day']:,}".replace(",", " "))
    return rid, len(guides)


async def make_offer(conn, guide, req, price: int, message: str | None) -> None:
    if req["status"] != "open":
        raise HTTPException(409)
    await conn.execute(
        """INSERT INTO offers (request_id, guide_id, price_per_day, message)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (request_id, guide_id)
           DO UPDATE SET price_per_day=EXCLUDED.price_per_day, message=EXCLUDED.message,
                         status='pending', created_at=now()""",
        req["id"], guide["id"], price, message,
    )
    await notify(conn, req["author_id"], "n.new_offer", f"/requests/{req['id']}", name=guide["name"])


async def choose_offer(conn, owner, offer_id: int, addon_ids: list[int] | None = None) -> int:
    offer = await conn.fetchrow(
        """SELECT o.*, r.author_id, r.author_type, r.date_from, r.date_to, r.status AS rstatus,
                  r.group_size
           FROM offers o JOIN requests r ON r.id=o.request_id WHERE o.id=$1""",
        offer_id,
    )
    if not offer or offer["author_id"] != owner["id"]:
        raise HTTPException(404)
    if offer["rstatus"] != "open" or offer["status"] != "pending":
        raise HTTPException(409)

    busy = await conn.fetchval(
        """SELECT 1 FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE a.guide_id=$1 AND a.status IN ('awaiting_payment','confirmed')
             AND r.date_from <= $3 AND r.date_to >= $2 LIMIT 1""",
        offer["guide_id"], offer["date_from"], offer["date_to"],
    )
    if busy:
        raise HTTPException(409, detail="Guide is already booked for these dates")

    days = (offer["date_to"] - offer["date_from"]).days + 1
    # Допуслуги: берём только активные допы этого гида, цену фиксируем снимком.
    addons = []
    if addon_ids:
        rows = await conn.fetch(
            "SELECT * FROM guide_addons WHERE guide_id=$1 AND active AND id = ANY($2::int[])",
            offer["guide_id"], addon_ids,
        )
        for a in rows:
            qty = offer["group_size"] if a["per"] == "person" else 1
            addons.append((a, qty, a["price"] * qty))
    total = offer["price_per_day"] * days + sum(amount for _, _, amount in addons)
    slugs = [r["slug"] for r in await conn.fetch(
        "SELECT s.slug FROM sites s JOIN requests r ON s.id = ANY(r.site_ids) WHERE r.id=$1", offer["request_id"])]
    fee = fees.compute(slugs, offer["group_size"], days)
    status = "awaiting_payment" if offer["author_type"] == "tourist" else "confirmed"
    deposit, balance = booking.amounts(total, offer["author_type"])
    aid = await conn.fetchval(
        """INSERT INTO assignments (request_id, offer_id, guide_id, client_id,
               price_per_day, days, total, status, entry_fee, deposit_amount, balance_to_guide)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
        offer["request_id"], offer_id, offer["guide_id"], owner["id"],
        offer["price_per_day"], days, total, status, fee["total"] if fee else 0, deposit, balance,
    )
    if status == "confirmed":  # турфирма без депозита: контакты — сразу после подтверждения
        await booking.unlock(conn, aid, paid=False)
    for a, qty, amount in addons:
        await conn.execute(
            """INSERT INTO assignment_addons (assignment_id, addon_id, kind, price, per, qty, amount)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""",
            aid, a["id"], a["kind"], a["price"], a["per"], qty, amount,
        )
    await conn.execute("UPDATE offers SET status='chosen' WHERE id=$1", offer_id)
    await conn.execute(
        "UPDATE offers SET status='rejected' WHERE request_id=$1 AND id<>$2 AND status='pending'",
        offer["request_id"], offer_id,
    )
    await conn.execute(
        "UPDATE requests SET status=$2 WHERE id=$1",
        offer["request_id"], "matched" if status == "awaiting_payment" else "confirmed",
    )
    key = "n.chosen_wait_payment" if status == "awaiting_payment" else "n.chosen_confirmed"
    await notify(conn, offer["guide_id"], key, f"/requests/{offer['request_id']}")
    return aid


async def confirm_deposit(conn, owner, assignment) -> None:
    if assignment["client_id"] != owner["id"] or assignment["status"] != "awaiting_payment":
        raise HTTPException(409)
    await payments.pay_deposit(conn, assignment)
    await conn.execute("UPDATE assignments SET status='confirmed' WHERE id=$1", assignment["id"])
    await booking.unlock(conn, assignment["id"], paid=True)
    await conn.execute("UPDATE requests SET status='confirmed' WHERE id=$1", assignment["request_id"])
    await notify(conn, assignment["guide_id"], "n.deposit_paid", f"/requests/{assignment['request_id']}")


async def complete(conn, owner, assignment) -> None:
    if assignment["client_id"] != owner["id"] or assignment["status"] != "confirmed":
        raise HTTPException(409)
    await conn.execute(
        "UPDATE assignments SET status='done', completed_at=now() WHERE id=$1", assignment["id"]
    )
    await conn.execute("UPDATE requests SET status='done' WHERE id=$1", assignment["request_id"])
    await rating.recompute_all(conn)
    link = f"/requests/{assignment['request_id']}"
    await notify(conn, assignment["guide_id"], "n.done_review", link)
    await notify(conn, assignment["client_id"], "n.done_review", link)


async def cancel(conn, actor, assignment) -> dict:
    """Правила отмены. Возвращает, что произошло, — для сообщения пользователю."""
    if assignment["status"] not in ("awaiting_payment", "confirmed"):
        raise HTTPException(409)
    req = await conn.fetchrow("SELECT * FROM requests WHERE id=$1", assignment["request_id"])
    link = f"/requests/{req['id']}"
    result = {"refund": 0, "penalty": False}

    if actor["id"] == assignment["client_id"]:
        await conn.execute(
            "UPDATE assignments SET status='cancelled', cancelled_by='client', cancelled_at=now(), contacts_unlocked=FALSE WHERE id=$1",
            assignment["id"],
        )
        await conn.execute("UPDATE requests SET status='cancelled' WHERE id=$1", req["id"])
        hours_left = (tour_start(req["date_from"]) - datetime.now(AQTAU)).total_seconds() / 3600
        if hours_left >= CANCEL_REFUND_HOURS:
            result["refund"] = await payments.refund_deposit(conn, assignment["id"])
        await notify(conn, assignment["guide_id"], "n.client_cancelled", link)

    elif actor["id"] == assignment["guide_id"]:
        was_confirmed = assignment["status"] == "confirmed"
        await conn.execute(
            "UPDATE assignments SET status='cancelled', cancelled_by='guide', cancelled_at=now(), contacts_unlocked=FALSE WHERE id=$1",
            assignment["id"],
        )
        result["refund"] = await payments.refund_deposit(conn, assignment["id"])
        # Штраф: системная оценка 1 в рейтинг гида только за отмену подтверждённого заказа.
        if was_confirmed:
            await conn.execute(
                """INSERT INTO reviews (assignment_id, author_id, target_id, target_role, overall, is_system)
                   VALUES ($1, NULL, $2, 'guide', 1, TRUE) ON CONFLICT DO NOTHING""",
                assignment["id"], assignment["guide_id"],
            )
            result["penalty"] = True
        # Заявка снова открыта, прежние отклики возвращаются в выбор.
        await conn.execute("UPDATE requests SET status='open' WHERE id=$1", req["id"])
        await conn.execute("UPDATE offers SET status='withdrawn' WHERE id=$1", assignment["offer_id"])
        await conn.execute(
            "UPDATE offers SET status='pending' WHERE request_id=$1 AND status='rejected'", req["id"]
        )
        await rating.recompute_all(conn)
        await notify(conn, assignment["client_id"], "n.guide_cancelled", link)
    else:
        raise HTTPException(403)
    return result
