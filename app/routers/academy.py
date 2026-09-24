from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import academy
from ..db import pool
from ..services import route
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
        fauna=academy.FAUNA[lang], fauna_sources=academy.FAUNA_SOURCES,
    )


@router.get("/academy/{slug}.gpx")
async def site_gpx(request: Request, slug: str):
    s = await pool().fetchrow("SELECT * FROM sites WHERE slug=$1", slug)
    if not s:
        raise HTTPException(404)
    body = route.gpx(s["name_en"], [dict(s)], lang_of(request))
    return Response(body, media_type="application/gpx+xml",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.gpx"'})


@router.get("/academy/{slug}")
async def site(request: Request, slug: str):
    lang = lang_of(request)
    s = await pool().fetchrow("SELECT * FROM sites WHERE slug=$1", slug)
    c = academy.site_content(slug, lang) if s else None
    if not c:
        raise HTTPException(404)
    guides = await pool().fetchval("SELECT count(*) FROM guides WHERE $1 = ANY(site_ids)", s["id"])
    incidents = [{**i, "text": i[lang]} for i in academy.INCIDENTS if i["site"] == slug]
    return await render(request, "academy/site.html", s=s, c=c, guides=guides,
                        fee_source=academy.FEE_SOURCE, incidents=incidents)
