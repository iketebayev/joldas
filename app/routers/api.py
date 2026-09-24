from fastapi import APIRouter

from ..config import GUIDE_LANGS
from ..db import pool
from ..services import pricing, rates

router = APIRouter()


@router.get("/api/price-hint")
async def price_hint(language: str = "", sites: str = ""):
    """Средняя ставка гида по языку и объектам + текущие курсы (для формы заявки)."""
    site_ids = [int(x) for x in sites.split(",") if x.strip().isdigit()]
    async with pool().acquire() as conn:
        avg = await pricing.average_rate(conn, language if language in GUIDE_LANGS else None, site_ids)
        cur = await rates.current(conn)
    return {**avg, **cur}
