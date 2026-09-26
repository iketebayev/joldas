"""Связь с гидом до бронирования: каналы, регион туриста, приветствие, ссылки."""
import re
from urllib.parse import quote

from ..config import APP_NAME, CHANNEL_ORDER, CHANNELS, CIS_COUNTRIES, CONTACT_REDIRECT_URL
from ..db import pool

REGIONS = ("west", "cn", "cis")

# Сообщение в WhatsApp после оплаты депозита: номер ваучера и даты, чтобы гид сразу нашёл бронь.
# Язык — общий для туриста и гида.
GREETING = {
    "en": "Hello! I booked your Mangystau tour on {app}. Voucher {code}, {dates}. Looking forward to meeting you!",
    "ru": "Здравствуйте! У меня бронь тура по Мангистау через {app}: ваучер {code}, {dates}. До встречи!",
    "kk": "Сәлеметсіз бе! {app} арқылы Маңғыстау турын брондадым. Ваучер {code}, {dates}. Кездескенше!",
    "zh": "您好！我在 {app} 上预订了您的曼格斯套旅行。凭证 {code}，日期 {dates}。期待与您见面！",
}

HOTEL_GREETING = {
    "en": "Hello! Found your hotel on {app}. I'd like to ask about a room in Aktau...",
    "ru": "Здравствуйте! Пишу вам с {app} — хочу уточнить наличие номеров в Актау...",
    "kk": "Сәлеметсіз бе! Қонақүйіңізді {app} сайтынан таптым. Бос нөмірлер туралы сұрағым бар...",
    "zh": "您好！我在 {app} 上看到了贵酒店，想咨询一下阿克套的客房情况……",
}

RN_HOSTS = ("https://www.xiaohongshu.com/", "https://xiaohongshu.com/", "https://xhslink.com/")


# --- нормализация того, что гид вводит в профиле --------------------------------

def norm_phone(raw) -> str | None:
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("8") and len(digits) == 11:  # 8 701 … → 7 701 …
        digits = "7" + digits[1:]
    return digits if 10 <= len(digits) <= 15 else None


def fmt_phone(raw) -> str | None:
    """+77011234567 → +7 701 123 45 67; остальные номера — как есть."""
    d = re.sub(r"\D", "", str(raw or ""))
    if len(d) == 11 and d[0] == "7":
        return f"+7 {d[1:4]} {d[4:7]} {d[7:9]} {d[9:]}"
    return ("+" + d) if d else None


def norm_handle(raw, tg: bool = False) -> str | None:
    """@name, instagram.com/name, x.com/name, t.me/name → name."""
    s = str(raw or "").strip()
    s = re.sub(r"^https?://(www\.)?(instagram\.com|x\.com|twitter\.com|t\.me)/", "", s).strip("/@ ")
    if tg:
        s = s.split("?")[0].split("/")[0]
        return s if re.fullmatch(r"[A-Za-z0-9_]{5,32}", s) else None
    s = s.split("?")[0].split("/")[0]
    return s if re.fullmatch(r"[A-Za-z0-9_.]{1,30}", s) else None


def norm_rednote_id(raw) -> str | None:
    s = str(raw or "").strip()
    return s[:40] if re.fullmatch(r"[A-Za-z0-9_.\-]{3,40}", s) else None


def norm_rednote_link(raw) -> str | None:
    s = str(raw or "").strip()
    return s[:300] if s.startswith(RN_HOSTS) else None


# --- регион туриста ---------------------------------------------------------------

async def region_of(user, lang: str) -> str:
    """По странам в последней анкете безопасности, иначе по языку интерфейса.
    Турфирмы — местные агентства: пишет менеджер, а не турист, поэтому регион СНГ."""
    if user and user["role"] == "company":
        return "cis"
    if user:
        countries = await pool().fetchval(
            """SELECT s.countries FROM request_safety s JOIN requests r ON r.id=s.request_id
               WHERE r.author_id=$1 AND cardinality(s.countries) > 0
               ORDER BY r.created_at DESC LIMIT 1""",
            user["id"],
        ) or []
        if "CN" in countries:
            return "cn"
        if countries and all(c in CIS_COUNTRIES for c in countries):
            return "cis"
        if countries:
            return "west"
    return "cis" if lang in ("ru", "kk") else "west"


def greeting_lang(region: str, ui_lang: str, guide_langs) -> str:
    langs = set(guide_langs or ())
    if region == "cn":
        prefer = ["zh", "en", "ru"]
    elif region == "cis":
        prefer = [ui_lang, "ru", "kk", "en"]
    else:
        prefer = ["en", "ru"]
    return next((x for x in prefer if x in langs and x in GREETING), "en")


# --- каналы гида --------------------------------------------------------------------

def channels(g, region: str) -> list[dict]:
    """Каналы, заполненные гидом, в порядке для региона; первый — рекомендуемый.
    В демо-режиме (CONTACT_REDIRECT_URL) показываются все каналы."""
    if CONTACT_REDIRECT_URL:
        out = [{"ch": ch, "handle": None} for ch in CHANNEL_ORDER[region]]
        out[0]["recommended"] = True
        return out
    have = {
        "whatsapp": g["whatsapp"],
        "telegram": g["telegram"],
        "instagram": g["instagram"],
        "rednote": g["rednote_id"] or g["rednote_link"],
        "x": g["x_handle"],
    }
    out = [{"ch": ch, "handle": g["rednote_id"] if ch == "rednote" else None}
           for ch in CHANNEL_ORDER[region] if have[ch]]
    if out:
        out[0]["recommended"] = True
    return out


def greeting(text_lang: str, code: str, dates: str) -> str:
    return GREETING[text_lang].format(app=APP_NAME, code=code, dates=dates)


def target_url(g, ch: str, text: str) -> str | None:
    """Куда ведёт кнопка канала. text — готовое сообщение для WhatsApp."""
    if CONTACT_REDIRECT_URL:
        return CONTACT_REDIRECT_URL if ch in CHANNELS else None
    if ch == "whatsapp" and g["whatsapp"]:
        return f"https://wa.me/{g['whatsapp']}?text=" + quote(text)
    if ch == "telegram" and g["telegram"]:
        return f"https://t.me/{g['telegram']}"
    if ch == "instagram" and g["instagram"]:
        return f"https://ig.me/m/{g['instagram']}"
    if ch == "x" and g["x_handle"]:
        return f"https://x.com/{g['x_handle']}"
    if ch == "rednote" and g["rednote_link"]:
        return g["rednote_link"]
    return None


def hotel_wa(phone: str, lang: str) -> str:
    return f"https://wa.me/{norm_phone(phone)}?text=" + quote(HOTEL_GREETING.get(lang, HOTEL_GREETING["en"]).format(app=APP_NAME))


async def log(target_type: str, ref, channel: str, user) -> None:
    await pool().execute(
        "INSERT INTO contact_clicks (target_type, target_ref, channel, user_id) VALUES ($1,$2,$3,$4)",
        target_type, str(ref), channel, user["id"] if user else None,
    )
