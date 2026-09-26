from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from .. import hotels as H
from ..auth import current_user, require_user
from ..config import CHANNELS
from ..db import pool
from ..services import booking, contact
from ..web import lang_of, render

router = APIRouter()

HOTEL_CHANNELS = ("call", "whatsapp", "instagram", "website", "email")


@router.get("/c/guide/{gid}/{ch}")
async def guide_channel(request: Request, gid: int, ch: str):
    """Переход в мессенджер гида — только клиенту, оплатившему депозит по брони у этого гида.
    До оплаты контакты не отдаются ни страницей, ни этим адресом."""
    user = await require_user(request)
    db = pool()
    g = await db.fetchrow("SELECT * FROM guides WHERE user_id=$1", gid)
    if not g or ch not in CHANNELS:
        raise HTTPException(404)
    a = await booking.unlocked_for(db, user["id"], gid)
    if not a:
        raise HTTPException(403)
    c = await booking.guide_contacts(db, g, a, user, lang_of(request))
    url = contact.target_url(g, ch, c["greeting"])
    if not url:
        raise HTTPException(404)
    await contact.log("guide", gid, ch, user)
    return RedirectResponse(url, status_code=302)


@router.post("/c/track/{kind}/{ref}/{ch}")
async def track(request: Request, kind: str, ref: str, ch: str):
    """Счётчик для кнопок без редиректа: звонок отелю, показ RedNote ID."""
    ok = ((kind == "hotel" and ref in H.BY_SLUG and ch in HOTEL_CHANNELS)
          or (kind == "guide" and ref.isdigit() and ch == "rednote"))
    if not ok:
        raise HTTPException(404)
    user = await current_user(request)
    if kind == "guide" and not user:
        raise HTTPException(403)
    await contact.log(kind, ref, ch, user)
    return Response(status_code=204)


@router.get("/hotels")
async def hotels(request: Request):
    lang = lang_of(request)
    rows = []
    for h in H.HOTELS:
        links = []
        if h["phone"]:
            links.append(("call", "tel:" + h["phone"].replace(" ", "")))
        if h["whatsapp"]:
            links.append(("whatsapp", contact.hotel_wa(h["whatsapp"], lang)))
        if h["instagram"]:
            links.append(("instagram", f"https://www.instagram.com/{h['instagram']}/"))
        if h["website"]:
            links.append(("website", h["website"]))
        if h["email"]:
            links.append(("email", "mailto:" + h["email"]))
        rows.append({**h, "addr": h["address"][lang], "links": links})
    pins = [{"name": h["name"], "lat": h["lat"], "lon": h["lon"], "addr": h["addr"]}
            for h in rows if h["lat"]]
    return await render(request, "hotels.html", hotels=rows, pins=pins, checked_on=H.CHECKED_ON)
