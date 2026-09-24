"""Курсы валют к тенге. Основной источник — официальные курсы Нацбанка РК (RSS),
запасной — open.er-api.com. Обновление каждые RATES_REFRESH_HOURS часов из main.py."""
import logging
import xml.etree.ElementTree as ET

import httpx

from ..config import CURRENCIES

log = logging.getLogger("rates")
NBK_URL = "https://nationalbank.kz/rss/rates_all.xml"
FALLBACK_URL = "https://open.er-api.com/v6/latest/KZT"
WANTED = [c for c in CURRENCIES if c != "KZT"]


async def _nbk(client) -> tuple[dict, str | None]:
    r = await client.get(NBK_URL, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rates, date = {}, None
    for item in ET.fromstring(r.content).iter("item"):
        code = item.findtext("title")
        if code in WANTED:
            quant = float(item.findtext("quant") or 1)
            rates[code] = float(item.findtext("description")) / quant
            date = item.findtext("pubDate")
    return rates, date


async def _fallback(client) -> tuple[dict, str | None]:
    r = await client.get(FALLBACK_URL)
    r.raise_for_status()
    d = r.json()
    return {c: 1 / d["rates"][c] for c in WANTED if d["rates"].get(c)}, d.get("time_last_update_utc")


async def refresh(conn) -> str | None:
    """Возвращает источник или None, если оба недоступны (тогда остаются прежние курсы)."""
    async with httpx.AsyncClient(timeout=15) as client:
        for name, fetch in (("nationalbank.kz", _nbk), ("open.er-api.com", _fallback)):
            try:
                rates, date = await fetch(client)
                if set(rates) >= set(WANTED):
                    for code, kzt in rates.items():
                        await conn.execute(
                            """INSERT INTO exchange_rates (code, kzt, source, rate_date, fetched_at)
                               VALUES ($1,$2,$3,$4,now())
                               ON CONFLICT (code) DO UPDATE SET kzt=EXCLUDED.kzt, source=EXCLUDED.source,
                                   rate_date=EXCLUDED.rate_date, fetched_at=now()""",
                            code, round(kzt, 4), name, date,
                        )
                    return name
            except Exception as e:  # сеть или формат — пробуем следующий источник
                log.warning("rates from %s failed: %s", name, e)
    return None


async def current(conn) -> dict:
    rows = await conn.fetch("SELECT * FROM exchange_rates")
    rates = {"KZT": 1.0}
    rates.update({r["code"]: float(r["kzt"]) for r in rows})
    meta = rows[0] if rows else None
    return {"rates": rates,
            "source": meta["source"] if meta else None,
            "rate_date": meta["rate_date"] if meta else None,
            "fetched_at": meta["fetched_at"].isoformat() if meta else None}
