"""Бронь гида: суммы (депозит 10% / остаток 90%), занятость, открытие контактов после депозита."""
import secrets
from datetime import date, timedelta

from ..config import CALENDAR_DAYS
from . import contact
from .payments import deposit_for

UNLOCKED = ("confirmed", "done")


def amounts(total: int, author_type: str) -> tuple[int, int]:
    """(deposit_amount, balance_to_guide). Турфирма депозит не платит — работает по подписке."""
    deposit = deposit_for(total) if author_type == "tourist" else 0
    return deposit, total - deposit


async def unlock(conn, assignment_id: int, paid: bool) -> str:
    """Открыть контакты и выдать ваучер. paid — отметка времени оплаты депозита."""
    code = "JL-" + secrets.token_hex(3).upper()
    await conn.execute(
        """UPDATE assignments SET contacts_unlocked=TRUE, voucher_code=coalesce(voucher_code, $2),
               deposit_paid_at=CASE WHEN $3 THEN now() ELSE deposit_paid_at END WHERE id=$1""",
        assignment_id, code, paid,
    )
    return code


async def busy_dates(db, guide_id: int, start: date | None = None, days: int = CALENDAR_DAYS) -> list[date]:
    """Дни, когда гид занят (ждёт депозита или подтверждён)."""
    start = start or date.today()
    end = start + timedelta(days=days - 1)
    rows = await db.fetch(
        """SELECT r.date_from, r.date_to FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE a.guide_id=$1 AND a.status IN ('awaiting_payment','confirmed')
             AND r.date_to >= $2 AND r.date_from <= $3""",
        guide_id, start, end,
    )
    out = set()
    for r in rows:
        d = max(r["date_from"], start)
        while d <= min(r["date_to"], end):
            out.add(d)
            d += timedelta(days=1)
    return sorted(out)


async def unlocked_for(db, client_id: int, guide_id: int):
    """Последняя бронь клиента у гида, по которой контакты открыты."""
    return await db.fetchrow(
        """SELECT a.*, r.date_from, r.date_to FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE a.client_id=$1 AND a.guide_id=$2 AND a.contacts_unlocked AND a.status IN ('confirmed','done')
           ORDER BY a.id DESC LIMIT 1""",
        client_id, guide_id,
    )


def dates_label(a) -> str:
    f, t = a["date_from"], a["date_to"]
    return f.strftime("%d.%m.%Y") if f == t else f"{f.strftime('%d.%m')}–{t.strftime('%d.%m.%Y')}"


async def guide_contacts(db, g, a, user, lang: str) -> dict:
    """Контакты гида для клиента с оплаченной бронью: телефон, каналы, готовое сообщение."""
    region = await contact.region_of(user, lang)
    text = contact.greeting(contact.greeting_lang(region, lang, g["languages"]), a["voucher_code"], dates_label(a))
    phone = await db.fetchval("SELECT phone FROM users WHERE id=$1", g["user_id"])
    return {
        "phone": contact.fmt_phone(g["whatsapp"] or phone),
        "tel": "+" + (g["whatsapp"] or "".join(c for c in (phone or "") if c.isdigit())),
        "channels": contact.channels(g, region),
        "greeting": text,
        "guide_id": g["user_id"],
    }
