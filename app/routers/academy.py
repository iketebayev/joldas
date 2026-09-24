from fastapi import APIRouter, HTTPException, Request

from .. import academy
from ..db import pool
from ..web import lang_of, render

router = APIRouter()


@router.get("/academy")
async def index(request: Request):
    lang = lang_of(request)
    sites = await pool().fetch("SELECT * FROM sites ORDER BY id")
    cards = [(s, academy.site_content(s["slug"], lang)) for s in sites]
    cards = [(s, c) for s, c in cards if c]
    return await render(
        request, "academy/index.html", general=academy.GENERAL[lang], cards=cards,
        phrases=academy.PHRASES, read=academy.READ_GENERAL, rules_source=academy.RULES_SOURCE,
        incident_sources=academy.INCIDENT_SOURCES, fee_source=academy.FEE_SOURCE,
    )


@router.get("/academy/{slug}")
async def site(request: Request, slug: str):
    lang = lang_of(request)
    s = await pool().fetchrow("SELECT * FROM sites WHERE slug=$1", slug)
    c = academy.site_content(slug, lang) if s else None
    if not c:
        raise HTTPException(404)
    guides = await pool().fetchval("SELECT count(*) FROM guides WHERE $1 = ANY(site_ids)", s["id"])
    return await render(request, "academy/site.html", s=s, c=c, guides=guides,
                        fee_source=academy.FEE_SOURCE)
