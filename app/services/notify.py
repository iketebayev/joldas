"""Уведомления: всегда в ленту на сайте, плюс WhatsApp через GreenAPI, если настроен.
Демо-пользователям WhatsApp не отправляется никогда — у них выдуманные номера."""
import logging
import re

import httpx

from .. import config
from ..i18n import t

log = logging.getLogger("notify")


def whatsapp_enabled() -> bool:
    return bool(config.GREENAPI_URL and config.GREENAPI_INSTANCE and config.GREENAPI_TOKEN)


def _chat_id(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return f"{digits}@c.us" if len(digits) >= 11 else None


def _full_url(link: str | None) -> str | None:
    if not link:
        return None
    if link.startswith("/"):
        proto = "https" if config.COOKIE_SECURE else "http"
        return f"{proto}://{config.DOMAIN}{link}"
    return link


async def _send_whatsapp(phone: str | None, text: str) -> str:
    chat = _chat_id(phone)
    if not chat:
        return "failed"
    url = f"{config.GREENAPI_URL}/waInstance{config.GREENAPI_INSTANCE}/sendMessage/{config.GREENAPI_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.post(url, json={"chatId": chat, "message": text})
            return "sent" if r.status_code == 200 else "failed"
    except Exception as e:
        log.warning("whatsapp failed: %s", e)
        return "failed"


async def notify(conn, user_id: int, key: str, link: str | None = None, **kw) -> None:
    """Текст собирается на языке интерфейса получателя."""
    lang = await conn.fetchval("SELECT ui_lang FROM users WHERE id=$1", user_id) or "ru"
    await notify_text(conn, user_id, t(lang, key, **kw), link)


async def notify_text(conn, user_id: int, text: str, link: str | None = None) -> None:
    user = await conn.fetchrow("SELECT phone, is_demo FROM users WHERE id=$1", user_id)
    wa = "off"
    if user and whatsapp_enabled() and not user["is_demo"] and user["phone"]:
        full_link = _full_url(link)
        wa = await _send_whatsapp(user["phone"], text + (f"\n{full_link}" if full_link else ""))
    await conn.execute(
        "INSERT INTO notifications (user_id, text, link, whatsapp) VALUES ($1,$2,$3,$4)",
        user_id, text, link, wa,
    )
