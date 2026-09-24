"""Средняя дневная ставка гида по реальным заказам площадки.

Сначала — по языку и пересечению объектов; если заказов меньше MIN_SAMPLES —
только по языку; дальше — по всем заказам. Возвращает, по какому срезу посчитано."""
MIN_SAMPLES = 3


async def average_rate(conn, language: str | None, site_ids: list[int]) -> dict:
    base = """SELECT round(avg(a.price_per_day)) AS avg, count(*) AS n
              FROM assignments a JOIN requests r ON r.id=a.request_id
              WHERE a.status <> 'cancelled'"""
    tries = []
    if language and site_ids:
        tries.append(("lang_sites", base + " AND r.language=$1 AND r.site_ids && $2::int[]", [language, site_ids]))
    if language:
        tries.append(("lang", base + " AND r.language=$1", [language]))
    tries.append(("all", base, []))
    for scope, sql, args in tries:
        row = await conn.fetchrow(sql, *args)
        if row["n"] >= MIN_SAMPLES or scope == "all":
            return {"avg_kzt": int(row["avg"]) if row["avg"] else None, "n": row["n"], "scope": scope}
