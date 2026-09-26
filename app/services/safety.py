"""Анкета безопасности группы и автобриф для гида.

Данные о здоровье — чувствительные: сохраняются только с согласием, видны автору заявки
и назначенному гиду после подтверждения, удаляются через SAFETY_RETENTION_DAYS после тура.
"""
import re
from datetime import date, timedelta

from .. import academy
from ..config import COUNTRIES, DIETS, RISKS, SAFETY_RETENTION_DAYS
from ..i18n import t


class SafetyError(Exception):
    """Ключ i18n с причиной отказа."""


def parse(form) -> dict:
    countries = [c for c in form.getlist("countries") if c in COUNTRIES]
    diet = [d for d in form.getlist("diet") if d in DIETS]
    risks = [r for r in form.getlist("risks") if r in RISKS]
    epipen = form.get("epipen") == "on"
    ice_name = (form.get("ice_name") or "").strip() or None
    ice_phone = re.sub(r"[^\d+]", "", form.get("ice_phone") or "") or None
    note = (form.get("note_safety") or "").strip() or None
    health = bool(diet or risks or epipen or ice_name or ice_phone or note)
    if health and form.get("consent") != "on":
        raise SafetyError("safety.need_consent")
    if (ice_name and not ice_phone) or (ice_phone and not ice_name):
        raise SafetyError("safety.ice_incomplete")
    if ice_phone and not ice_phone.startswith("+"):
        raise SafetyError("safety.ice_code")
    return {"countries": countries, "diet": diet, "risks": risks, "epipen": epipen,
            "ice_name": ice_name, "ice_phone": ice_phone, "note": note, "health": health}


async def save(conn, request_id: int, data: dict) -> None:
    if not (data["countries"] or data["health"]):
        return
    await conn.execute(
        """INSERT INTO request_safety (request_id, countries, diet, risks, epipen,
               ice_name, ice_phone, note, consent_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8, CASE WHEN $9 THEN now() END)""",
        request_id, data["countries"], data["diet"], data["risks"], data["epipen"],
        data["ice_name"], data["ice_phone"], data["note"], data["health"],
    )


def season_key(d: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(d.month, "autumn")


def brief(req, safety, sites, lang: str) -> dict:
    """Конкретные действия гида: по рискам группы, питанию, объектам маршрута и сезону."""
    yes_no = t(lang, "safety.yes" if safety and safety["epipen"] else "safety.no")
    risks = [t(lang, f"safety.act_{r}", epipen=yes_no) for r in (safety["risks"] if safety else [])]
    diet = [t(lang, f"safety.act_{d}") for d in (safety["diet"] if safety else [])]
    by_site = []
    for s in sites:
        if s["id"] in req["site_ids"]:
            c = academy.site_content(s["slug"], lang)
            if c and c["safety"]:
                by_site.append((s[f"name_{lang}"], c["safety"]))
    return {"risks": risks, "diet": diet, "sites": by_site,
            "season": t(lang, f"safety.season_{season_key(req['date_from'])}")}


async def purge(conn) -> int:
    cutoff = date.today() - timedelta(days=SAFETY_RETENTION_DAYS)
    # Здоровье, питание и контакт ICE стираются; страны остаются — это обезличенная статистика
    # турпотока для акимата, без неё пропадёт география за прошлые месяцы.
    res = await conn.execute(
        """UPDATE request_safety s SET diet='{}', risks='{}', epipen=FALSE, ice_name=NULL,
               ice_phone=NULL, note=NULL
           FROM requests r
           WHERE r.id = s.request_id AND r.date_to < $1
             AND (cardinality(s.diet) > 0 OR cardinality(s.risks) > 0 OR s.epipen
                  OR s.ice_name IS NOT NULL OR s.ice_phone IS NOT NULL OR s.note IS NOT NULL)""",
        cutoff,
    )
    return int(res.split()[-1])
