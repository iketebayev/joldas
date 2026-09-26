"""Аналитика для финансового дашборда и дашборда управления туризма.

Считается на лету из заказов (assignments) и платежей:
  GMV        = Σ total                       — подтверждённые и завершённые брони
  Revenue    = Σ deposit_amount               — депозиты 10% (только брони туристов; турфирмы — по подписке)
  Local      = Σ balance_to_guide             — деньги, оставшиеся у гидов региона (90%, у турфирм — 100%)
  AOV        = GMV / число броней
  CR         = оплаченные брони туристов / созданные брони туристов × 100%
Финансы считаются по дате оплаты депозита, туризм — по дате тура (когда туристы были в регионе).
"""
from datetime import date, datetime, timedelta, timezone

from ..config import ACQUIRING_PCT, ANALYTICS_PERIODS, CANCEL_REFUND_HOURS, DEPOSIT_PERCENT

LIVE = "('confirmed','done')"


def window(period: str) -> tuple[str, datetime, datetime, datetime]:
    """(ключ периода, начало, конец, начало прошлого такого же периода)."""
    if period not in ANALYTICS_PERIODS:
        period = "quarter"
    days = ANALYTICS_PERIODS[period]
    end = datetime.now(timezone.utc)
    if period == "today":
        start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = end - timedelta(days=days)
    return period, start, end, start - (end - start)


def trend(cur, prev) -> float | None:
    """Изменение к прошлому периоду, %. None — сравнивать не с чем."""
    if not prev:
        return None
    return round((float(cur or 0) - float(prev)) / float(prev) * 100, 1)


async def usd_rate(db) -> float | None:
    v = await db.fetchval("SELECT kzt FROM exchange_rates WHERE code='USD'")
    return float(v) if v else None


def fill(rows, start: datetime, end: datetime, step: str) -> list[dict]:
    """Ряд без пропусков: дни или месяцы без оплат — нули, а не соединённые линией точки."""
    have = {x["d"]: x for x in rows}
    out, d = [], start.astimezone(timezone(timedelta(hours=5))).date()
    last = end.astimezone(timezone(timedelta(hours=5))).date()
    if step == "month":
        d = d.replace(day=1)
    while d <= last:
        x = have.get(d)
        out.append({"d": d.isoformat(), "deposits": int(x["deposits"]) if x else 0, "n": x["n"] if x else 0})
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1) if step == "month" else d + timedelta(days=1)
    return out


# --- финансы ----------------------------------------------------------------------------

async def _money(db, start, end) -> dict:
    r = await db.fetchrow(
        f"""SELECT
              coalesce(sum(a.deposit_amount) FILTER (WHERE r.author_type='tourist' AND a.deposit_paid_at >= $1
                                                       AND a.deposit_paid_at < $2), 0) AS deposits,
              count(*) FILTER (WHERE r.author_type='tourist' AND a.deposit_paid_at >= $1 AND a.deposit_paid_at < $2) AS paid,
              coalesce(sum(a.total) FILTER (WHERE a.status IN {LIVE}
                  AND coalesce(a.deposit_paid_at, a.created_at) >= $1 AND coalesce(a.deposit_paid_at, a.created_at) < $2), 0) AS gmv,
              coalesce(sum(a.total) FILTER (WHERE a.status IN {LIVE} AND r.author_type='tourist'
                  AND a.deposit_paid_at >= $1 AND a.deposit_paid_at < $2), 0) AS gmv_tourist,
              count(*) FILTER (WHERE a.status IN {LIVE}
                  AND coalesce(a.deposit_paid_at, a.created_at) >= $1 AND coalesce(a.deposit_paid_at, a.created_at) < $2) AS bookings,
              coalesce(sum(a.balance_to_guide) FILTER (WHERE a.status IN {LIVE}
                  AND coalesce(a.deposit_paid_at, a.created_at) >= $1 AND coalesce(a.deposit_paid_at, a.created_at) < $2), 0) AS payouts,
              count(DISTINCT a.guide_id) FILTER (WHERE a.status IN {LIVE}
                  AND coalesce(a.deposit_paid_at, a.created_at) >= $1 AND coalesce(a.deposit_paid_at, a.created_at) < $2) AS guides,
              count(*) FILTER (WHERE r.author_type='tourist' AND a.created_at >= $1 AND a.created_at < $2) AS created,
              count(*) FILTER (WHERE r.author_type='tourist' AND a.created_at >= $1 AND a.created_at < $2
                               AND a.deposit_paid_at IS NOT NULL) AS created_paid
            FROM assignments a JOIN requests r ON r.id=a.request_id""",
        start, end,
    )
    pay = await db.fetchrow(
        """SELECT coalesce(sum(amount) FILTER (WHERE kind='refund'), 0) AS refunds,
                  coalesce(sum(amount) FILTER (WHERE kind='subscription'), 0) AS subs
           FROM payments WHERE created_at >= $1 AND created_at < $2""",
        start, end,
    )
    deposits = int(r["deposits"])
    acquiring = round(deposits * ACQUIRING_PCT / 100)
    net = deposits - int(pay["refunds"]) - acquiring
    return {
        "deposits": deposits, "refunds": int(pay["refunds"]), "acquiring": acquiring, "net": net,
        "subs": int(pay["subs"]), "gmv": int(r["gmv"]), "gmv_tourist": int(r["gmv_tourist"]),
        "bookings": r["bookings"], "paid": r["paid"], "created": r["created"],
        "payouts": int(r["payouts"]), "guides": r["guides"],
        "aov": round(r["gmv"] / r["bookings"]) if r["bookings"] else 0,
        "arpu_guide": round(r["payouts"] / r["guides"]) if r["guides"] else 0,
        # Конверсия по когорте: из броней, созданных в периоде, сколько оплачено.
        "cr": round(r["created_paid"] / r["created"] * 100, 1) if r["created"] else None,
        "created_paid": r["created_paid"],
        "take_nominal": float(DEPOSIT_PERCENT),
        "take_effective": round(deposits / r["gmv"] * 100, 1) if r["gmv"] else None,
    }


async def finance(db, period: str) -> dict:
    period, start, end, prev_start = window(period)
    cur, prev = await _money(db, start, end), await _money(db, prev_start, start)
    # Депозиты по будущим турам: деньги получены, но пока тур не прошёл, возможен возврат.
    pend = await db.fetchrow(
        f"""SELECT coalesce(sum(a.deposit_amount), 0) AS held, count(*) AS n,
                  coalesce(sum(a.deposit_amount) FILTER (
                      WHERE (r.date_from + time '09:00') AT TIME ZONE 'Asia/Aqtau' > now() + interval '{CANCEL_REFUND_HOURS} hours'), 0) AS refundable
           FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE a.status='confirmed' AND r.author_type='tourist' AND a.deposit_paid_at IS NOT NULL
             AND r.date_from >= CURRENT_DATE"""
    )
    monthly = period in ("year",)
    step = "month" if monthly else "day"
    series = await db.fetch(
        f"""SELECT date_trunc('{step}', a.deposit_paid_at AT TIME ZONE 'Asia/Aqtau')::date AS d,
                   sum(a.deposit_amount) AS deposits, count(*) AS n
            FROM assignments a JOIN requests r ON r.id=a.request_id
            WHERE r.author_type='tourist' AND a.deposit_paid_at >= $1 AND a.deposit_paid_at < $2
            GROUP BY 1 ORDER BY 1""",
        start, end,
    )
    by_currency = await db.fetch(
        """SELECT r.currency, count(*) AS n, sum(a.deposit_amount) AS deposits, sum(a.total) AS gmv
           FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE r.author_type='tourist' AND a.deposit_paid_at >= $1 AND a.deposit_paid_at < $2
           GROUP BY 1 ORDER BY 3 DESC""",
        start, end,
    )
    funnel = await db.fetch(
        """SELECT kind, count(DISTINCT visitor) AS n, bool_or(is_demo) AS demo FROM funnel_events
           WHERE created_at >= $1 AND created_at < $2 GROUP BY 1""",
        start, end,
    )
    f = {x["kind"]: x["n"] for x in funnel}
    tx = await db.fetch(
        """SELECT a.id, a.voucher_code, a.total, a.deposit_amount, a.deposit_paid_at, a.status, r.currency,
                  c.name AS tourist, g.name AS guide,
                  (SELECT p.status FROM payments p WHERE p.assignment_id=a.id AND p.kind='deposit' LIMIT 1) AS acq,
                  (SELECT sum(p.amount) FROM payments p WHERE p.assignment_id=a.id AND p.kind='refund') AS refund
           FROM assignments a JOIN requests r ON r.id=a.request_id
           JOIN users c ON c.id=a.client_id JOIN users g ON g.id=a.guide_id
           WHERE r.author_type='tourist' AND a.deposit_paid_at >= $1 AND a.deposit_paid_at < $2
           ORDER BY a.deposit_paid_at DESC LIMIT 50""",
        start, end,
    )
    return {
        "period": period, "start": start, "end": end, "cur": cur, "prev": prev,
        "trend": {k: trend(cur[k], prev[k]) for k in ("net", "gmv", "aov", "arpu_guide", "deposits", "bookings")},
        "pending": dict(pend), "step": step,
        "series": fill(series, start, end, step),
        "by_currency": by_currency, "tx": tx,
        "funnel": [("view", f.get("view", 0)), ("date", f.get("date", 0)),
                   ("booking", f.get("booking", 0)), ("paid", f.get("paid", 0))],
        "funnel_demo": any(x["demo"] for x in funnel),
        "usd": await usd_rate(db), "acquiring_pct": ACQUIRING_PCT,
    }


# --- туризм региона ---------------------------------------------------------------------

async def _region(db, d_from: date, d_to: date) -> dict:
    r = await db.fetchrow(
        f"""SELECT coalesce(sum(a.total), 0) AS gmv, coalesce(sum(a.balance_to_guide), 0) AS local,
                  coalesce(sum(r.group_size), 0) AS tourists,
                  coalesce(sum(r.group_size * a.days), 0) AS tourist_days,
                  count(*) AS bookings, count(DISTINCT a.guide_id) AS guides
           FROM assignments a JOIN requests r ON r.id=a.request_id
           WHERE a.status IN {LIVE} AND r.date_from >= $1 AND r.date_from <= $2""",
        d_from, d_to,
    )
    out = {k: int(v) for k, v in dict(r).items()}
    out["avg_stay"] = round(out["tourist_days"] / out["tourists"], 1) if out["tourists"] else 0
    return out


async def gov(db, period: str) -> dict:
    period, start, end, prev_start = window(period)
    d_from, d_to, p_from = start.date(), end.date(), prev_start.date()
    cur, prev = await _region(db, d_from, d_to), await _region(db, p_from, d_from - timedelta(days=1))
    days = max(1, (d_to - d_from).days)
    # Страны: группа делится поровну между указанными странами; без анкеты — «не указано».
    countries = await db.fetch(
        f"""SELECT c AS country, round(sum(r.group_size::numeric / cardinality(s.countries)), 1) AS people
            FROM assignments a JOIN requests r ON r.id=a.request_id
            JOIN request_safety s ON s.request_id=r.id, unnest(s.countries) c
            WHERE a.status IN {LIVE} AND r.date_from >= $1 AND r.date_from <= $2 AND cardinality(s.countries) > 0
            GROUP BY 1 ORDER BY 2 DESC""",
        d_from, d_to,
    )
    known = sum(float(x["people"]) for x in countries)
    sites = await db.fetch(
        f"""SELECT s.id, s.slug, s.name_ru, s.name_kk, s.name_en, sum(r.group_size) AS people, count(*) AS tours
            FROM assignments a JOIN requests r ON r.id=a.request_id JOIN sites s ON s.id = ANY(r.site_ids)
            WHERE a.status IN {LIVE} AND r.date_from >= $1 AND r.date_from <= $2
            GROUP BY s.id ORDER BY people DESC""",
        d_from, d_to,
    )
    monthly = await db.fetch(
        f"""SELECT date_trunc('month', r.date_from)::date AS m, sum(a.total) AS gmv,
                   sum(a.balance_to_guide) AS local, sum(r.group_size) AS tourists
            FROM assignments a JOIN requests r ON r.id=a.request_id
            WHERE a.status IN {LIVE} AND r.date_from >= $1 AND r.date_from <= $2
            GROUP BY 1 ORDER BY 1""",
        d_to - timedelta(days=365 if period == "year" else 183), d_to,
    )
    verified = await db.fetchval("SELECT count(*) FROM guides WHERE id_verified_at IS NOT NULL")
    active = cur["guides"]
    return {
        "period": period, "start": d_from, "end": d_to, "cur": cur, "prev": prev,
        "trend": {k: trend(cur[k], prev[k]) for k in ("gmv", "local", "tourists", "tourist_days", "avg_stay")},
        "countries": countries, "unknown": max(0, round(cur["tourists"] - known)),
        "sites": sites, "monthly": monthly, "verified": verified, "active": active,
        "guide_month": round(cur["local"] / active / max(1, days / 30)) if active else 0,
        "usd": await usd_rate(db),
    }
