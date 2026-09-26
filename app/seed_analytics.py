"""Аккаунты аналитики и демо-данные для финансового и туристического дашбордов.

    python -m app.seed_analytics            — аккаунты + дозаполнение демо-броней + 65 демо-броней за 6 месяцев
    python -m app.seed_analytics --accounts — только аккаунты
    python -m app.seed_analytics --remove   — удалить сгенерированные брони (аккаунты остаются)

Все сгенерированные записи помечены is_demo, туристы — почта an-*@demo.kz. Настоящие брони не трогаются.
Суммы: депозит = 10% от итога, остаток гиду = 90%.
"""
import asyncio
import random
import secrets
import sys
from datetime import date, datetime, time, timedelta, timezone

from .auth import hash_password
from .config import DEMO_PASSWORD
from .db import close_pool, init_pool, pool
from .services import rating
from .services.payments import deposit_for

AQTAU = timezone(timedelta(hours=5))

ACCOUNTS = [
    ("finance_admin", "Финансовый аналитик", "admin-finance@demo.kz", "+70000000901"),
    ("gov_observer", "Управление туризма (наблюдатель)", "admin-gov@demo.kz", "+70000000902"),
]

# Туристы: страна, валюта заявки, язык тура по возможности.
TOURISTS = [
    ("Lukas Becker", "DE", "EUR", "de"), ("Sophie Wagner", "DE", "EUR", "de"), ("Jonas Fischer", "DE", "EUR", "en"),
    ("Camille Laurent", "FR", "EUR", "fr"), ("Julien Moreau", "FR", "EUR", "fr"),
    ("Kim Min-jun", "KR", "USD", "ko"), ("Park Ji-woo", "KR", "USD", "en"),
    ("Emily Carter", "US", "USD", "en"), ("Michael Brooks", "US", "USD", "en"),
    ("Anna Kowalska", "PL", "EUR", "en"), ("Piotr Nowak", "PL", "KZT", "ru"),
    ("Oliver Hughes", "GB", "USD", "en"), ("Charlotte Evans", "GB", "USD", "en"),
    ("Giulia Romano", "IT", "EUR", "en"), ("Omar Al Mansoori", "AE", "USD", "ar"),
    ("Chen Jing", "CN", "CNY", "zh"), ("Sato Yuki", "JP", "USD", "en"),
]
N_BOOKINGS = 65


def at(d: date, h: int = 10) -> datetime:
    return datetime.combine(d, time(h), tzinfo=AQTAU)


async def accounts(conn) -> None:
    pw = hash_password(DEMO_PASSWORD)
    for role, name, email, phone in ACCOUNTS:
        await conn.execute(
            """INSERT INTO users (role, name, email, phone, password_hash, ui_lang, is_demo)
               VALUES ($1,$2,$3,$4,$5,'ru',TRUE)
               ON CONFLICT (email) DO UPDATE SET role=EXCLUDED.role, password_hash=EXCLUDED.password_hash""",
            role, name, email, phone, pw,
        )


async def backfill(conn) -> None:
    """Старые демо-брони из сида: дата брони = дата заявки, депозит оплачен через час, платёж записан."""
    await conn.execute(
        """UPDATE assignments a SET created_at = least(r.created_at + interval '6 hours', now())
           FROM requests r WHERE r.id=a.request_id AND r.is_demo AND a.created_at > r.created_at + interval '3 days'"""
    )
    await conn.execute(
        """UPDATE assignments a SET deposit_paid_at = a.created_at + interval '1 hour'
           FROM requests r WHERE r.id=a.request_id AND r.is_demo AND r.author_type='tourist'
             AND a.status IN ('confirmed','done') AND a.deposit_paid_at IS NULL"""
    )
    await conn.execute(
        """INSERT INTO payments (kind, assignment_id, amount, status, created_at)
           SELECT 'deposit', a.id, a.deposit_amount, 'paid_test', a.deposit_paid_at
           FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE r.is_demo AND a.deposit_paid_at IS NOT NULL AND a.deposit_amount > 0
             AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.assignment_id=a.id AND p.kind='deposit')"""
    )
    await conn.execute(
        """UPDATE assignments SET voucher_code = 'JL-' || upper(substr(md5(id::text || created_at::text), 1, 6))
           WHERE contacts_unlocked AND voucher_code IS NULL"""
    )


async def generate(conn, rnd: random.Random) -> int:
    if await conn.fetchval("SELECT 1 FROM users WHERE email LIKE 'an-%@demo.kz' LIMIT 1"):
        print("демо-брони аналитики уже есть — пропускаю (удалить: --remove)")
        return 0
    region = await conn.fetchval("SELECT id FROM regions WHERE code='mangystau'")
    sites = {r["slug"]: r["id"] for r in await conn.fetch("SELECT id, slug FROM sites")}
    guides = await conn.fetch(
        "SELECT user_id, languages FROM guides WHERE id_verified_at IS NOT NULL AND day_rate > 0"
    )
    pw = hash_password(DEMO_PASSWORD)
    tourists = []
    for i, (name, cc, cur, lang) in enumerate(TOURISTS):
        uid = await conn.fetchval(
            """INSERT INTO users (role, name, email, phone, password_hash, ui_lang, is_demo)
               VALUES ('tourist',$1,$2,$3,$4,'en',TRUE) RETURNING id""",
            name, f"an-{i + 1:02d}@demo.kz", f"+7000000095{i:02d}", pw,
        )
        tourists.append((uid, cc, cur, lang))

    # Занятость гидов: существующие брони + сгенерированные, чтобы не было двойных броней.
    busy = {}
    for r in await conn.fetch(
        """SELECT a.guide_id, r.date_from, r.date_to FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE a.status IN ('awaiting_payment','confirmed','done')"""
    ):
        d = r["date_from"]
        while d <= r["date_to"]:
            busy.setdefault(r["guide_id"], set()).add(d)
            d += timedelta(days=1)

    today = date.today()
    made = 0
    popular = ["bozjyra", "tuzbair", "kyzylkup", "torysh", "sherkala", "bokty", "shakpak_ata", "beket_ata", "karaman_ata"]
    weights = [9, 6, 6, 4, 5, 3, 3, 3, 1]
    while made < N_BOOKINGS:
        uid, cc, cur, want = rnd.choice(tourists)
        kind = rnd.choices(["day", "two", "expedition"], [60, 25, 15])[0]
        days = {"day": 1, "two": 2, "expedition": rnd.choice([3, 4])}[kind]
        rate = {"day": rnd.randrange(20000, 45001, 1000), "two": rnd.randrange(30000, 60001, 1000),
                "expedition": rnd.randrange(250000, 300001, 5000)}[kind]
        group = rnd.randint(1, 6) if kind != "expedition" else rnd.randint(2, 4)
        d_from = today + timedelta(days=rnd.randint(-178, 21))
        d_to = d_from + timedelta(days=days - 1)
        g = rnd.choice(guides)
        span = {d_from + timedelta(days=k) for k in range(days)}
        if busy.get(g["user_id"], set()) & span:
            continue
        lang = want if want in g["languages"] else ("en" if "en" in g["languages"] else g["languages"][0])
        n_sites = 1 if kind == "day" else rnd.randint(2, 3)
        picked = set(rnd.choices(popular, weights, k=n_sites + 2))
        if kind == "expedition":
            picked.add("bozjyra")
        site_ids = [sites[s] for s in list(picked)[: max(n_sites, 1) + (1 if kind == "expedition" else 0)] if s in sites]

        created = min(at(d_from) - timedelta(days=rnd.randint(3, 40), hours=rnd.randint(0, 12)),
                      datetime.now(AQTAU) - timedelta(hours=2))
        future = d_from >= today
        roll = rnd.random()
        abandoned = False  # бронь создана, но депозит так и не оплачен — для честной конверсии
        if not future:
            status = "cancelled" if roll < 0.27 else "done"
            abandoned = 0.07 <= roll < 0.27
        else:
            status = "awaiting_payment" if roll < 0.2 else "confirmed"
        paid = status in ("confirmed", "done") or (status == "cancelled" and not abandoned)
        total = rate * days
        deposit = deposit_for(total)
        paid_at = created + timedelta(minutes=rnd.randint(4, 180)) if paid else None

        rid = await conn.fetchval(
            """INSERT INTO requests (author_id, author_type, region_id, date_from, date_to, site_ids, language,
                   group_size, price_per_day, status, is_demo, direct, currency, created_at)
               VALUES ($1,'tourist',$2,$3,$4,$5,$6,$7,$8,$9,TRUE,TRUE,$10,$11) RETURNING id""",
            uid, region, d_from, d_to, site_ids, lang, group, rate,
            {"done": "done", "confirmed": "confirmed", "cancelled": "cancelled", "awaiting_payment": "matched"}[status],
            cur, created - timedelta(minutes=10),
        )
        await conn.execute("INSERT INTO request_safety (request_id, countries) VALUES ($1,$2)", rid, [cc])
        oid = await conn.fetchval(
            """INSERT INTO offers (request_id, guide_id, price_per_day, status, created_at)
               VALUES ($1,$2,$3,'chosen',$4) RETURNING id""", rid, g["user_id"], rate, created,
        )
        aid = await conn.fetchval(
            """INSERT INTO assignments (request_id, offer_id, guide_id, client_id, price_per_day, days, total, status,
                   entry_fee, deposit_amount, balance_to_guide, contacts_unlocked, deposit_paid_at, voucher_code,
                   created_at, completed_at, cancelled_by, cancelled_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,0,$9,$10,$11,$12,$13,$14,$15,$16,$17) RETURNING id""",
            rid, oid, g["user_id"], uid, rate, days, total, status, deposit, total - deposit,
            status in ("confirmed", "done"), paid_at,
            ("JL-" + secrets.token_hex(3).upper()) if paid else None, created,
            at(d_to, 19) if status == "done" else None,
            "client" if status == "cancelled" else None,
            ((paid_at or created) + timedelta(days=rnd.randint(1, 5))) if status == "cancelled" else None,
        )
        if paid:
            await conn.execute(
                """INSERT INTO payments (kind, assignment_id, amount, status, created_at)
                   VALUES ('deposit',$1,$2,'paid_test',$3)""", aid, deposit, paid_at,
            )
        if status == "cancelled" and paid:  # отмена раньше 48 ч — возврат депозита
            await conn.execute(
                """INSERT INTO payments (kind, assignment_id, amount, status, created_at)
                   VALUES ('refund',$1,$2,'refunded_test',$3)""", aid, deposit, paid_at + timedelta(days=2),
            )
        # Воронка: у каждой брони — просмотр, выбор даты и бронь одного посетителя; плюс «ушедшие» посетители.
        vid = secrets.token_hex(8)
        events = [("view", created - timedelta(minutes=20), vid), ("date", created - timedelta(minutes=8), vid),
                  ("booking", created, vid)]
        if paid:
            events.append(("paid", paid_at, vid))
        for _ in range(rnd.randint(2, 6)):
            other, when = secrets.token_hex(8), created - timedelta(hours=rnd.randint(1, 72))
            events.append(("view", when, other))
            if rnd.random() < 0.3:
                events.append(("date", when + timedelta(minutes=3), other))
        for k, when, who in events:
            await conn.execute(
                "INSERT INTO funnel_events (kind, guide_id, visitor, is_demo, created_at) VALUES ($1,$2,$3,TRUE,$4)",
                k, g["user_id"], who, when,
            )
        busy.setdefault(g["user_id"], set()).update(span)
        made += 1
    return made


async def remove(conn) -> None:
    ids = [r["id"] for r in await conn.fetch("SELECT id FROM users WHERE email LIKE 'an-%@demo.kz'")]
    if not ids:
        print("нечего удалять")
        return
    rids = [r["id"] for r in await conn.fetch("SELECT id FROM requests WHERE author_id = ANY($1::int[])", ids)]
    aids = [r["id"] for r in await conn.fetch("SELECT id FROM assignments WHERE request_id = ANY($1::int[])", rids)]
    await conn.execute("DELETE FROM payments WHERE assignment_id = ANY($1::int[])", aids)
    await conn.execute("DELETE FROM assignment_addons WHERE assignment_id = ANY($1::int[])", aids)
    await conn.execute("DELETE FROM reviews WHERE assignment_id = ANY($1::int[])", aids)
    await conn.execute("DELETE FROM assignments WHERE id = ANY($1::int[])", aids)
    await conn.execute("DELETE FROM offers WHERE request_id = ANY($1::int[])", rids)
    await conn.execute("DELETE FROM requests WHERE id = ANY($1::int[])", rids)
    await conn.execute("DELETE FROM notifications WHERE user_id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM users WHERE id = ANY($1::int[])", ids)
    await conn.execute("DELETE FROM funnel_events WHERE is_demo")
    print(f"удалено: туристов {len(ids)}, броней {len(aids)}")


async def main(args: list[str]) -> None:
    await init_pool(apply_schema=False)
    async with pool().acquire() as conn, conn.transaction():
        if "--remove" in args:
            await remove(conn)
        else:
            await accounts(conn)
            print("аккаунты: admin-finance@demo.kz, admin-gov@demo.kz")
            if "--accounts" not in args:
                await backfill(conn)
                print(f"сгенерировано броней: {await generate(conn, random.Random(2026))}")
        # Счётчики заказов, уровни и рейтинги гидов — по фактическим броням, в том числе сгенерированным.
        await rating.recompute_all(conn)
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
