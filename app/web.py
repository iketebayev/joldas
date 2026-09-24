"""Рендер страниц: язык, текущий пользователь, помощники для шаблонов."""
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from . import config
from .auth import current_user
from .db import pool
from .i18n import pick_lang, t

templates = Jinja2Templates(directory="app/templates")


def lang_of(request: Request) -> str:
    return pick_lang(request.cookies.get("lang"), request.headers.get("accept-language"))


def flash(request: Request, key: str, kind: str = "ok", **kw) -> None:
    request.session.setdefault("flash", []).append({"key": key, "kind": kind, "kw": kw})


def money(v) -> str:
    return f"{int(v):,}".replace(",", "\u00a0") + "\u00a0₸" if v is not None else "—"


def price_label(r) -> str:
    """Цена заявки: в валюте заказчика и в тенге, если валюта не тенге."""
    kzt = money(r["price_per_day"])
    cur = r.get("currency") if hasattr(r, "get") else r["currency"]
    if not cur or cur == "KZT" or r["price_original"] is None:
        return kzt
    amount = f"{float(r['price_original']):,.2f}".rstrip("0").rstrip(".").replace(",", "\u00a0")
    return f"{config.CURRENCY_SIGN.get(cur, cur)}{amount} ≈ {kzt}"


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


async def render(request: Request, name: str, status_code: int = 200, **ctx):
    lang = lang_of(request)
    user = await current_user(request)
    unread = 0
    if user:
        unread = await pool().fetchval(
            "SELECT count(*) FROM notifications WHERE user_id=$1 AND NOT is_read", user["id"]
        )
    flashes = request.session.pop("flash", [])

    def tr(key, /, **kw):
        return t(lang, key, **kw)

    def name_of(row):
        """Название объекта/региона на языке интерфейса."""
        return row[f"name_{lang}"] if row else ""

    ctx.update(
        request=request, lang=lang, user=user, unread=unread, flashes=flashes,
        t=tr, name_of=name_of, money=money, price_label=price_label, app_name=config.APP_NAME,
        ui_langs=config.UI_LANGS, guide_langs=config.GUIDE_LANGS,
        specializations=config.SPECIALIZATIONS, deposit_percent=config.DEPOSIT_PERCENT,
        countries=config.COUNTRIES, diets=config.DIETS, risks=config.RISKS,
        addon_kinds=config.ADDON_KINDS, currency_sign=config.CURRENCY_SIGN,
    )
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
