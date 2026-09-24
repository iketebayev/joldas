from fastapi import APIRouter, Request

from ..auth import require_user
from ..config import GUIDE_LANGS
from ..db import pool
from ..services.notify import notify_text
from ..web import flash, redirect, render

router = APIRouter()


@router.get("/dashboard")
async def dashboard(request: Request):
    await require_user(request, "admin")
    db = pool()
    totals = await db.fetchrow(
        """SELECT count(*) AS all,
                  count(*) FILTER (WHERE status='open') AS open,
                  count(*) FILTER (WHERE status IN ('confirmed','done')) AS filled,
                  count(*) FILTER (WHERE status='done') AS done,
                  count(*) FILTER (WHERE status='cancelled') AS cancelled
           FROM requests"""
    )
    active = totals["all"] - totals["cancelled"]
    fill_rate = round(100 * totals["filled"] / active) if active else 0

    # Спрос и предложение по языкам: сколько заявок и сколько гидов.
    by_lang = await db.fetch(
        """WITH demand AS (
               SELECT language,
                      count(*) FILTER (WHERE status <> 'cancelled') AS total,
                      count(*) FILTER (WHERE status IN ('confirmed','done')) AS filled,
                      count(*) FILTER (WHERE status='open') AS open,
                      count(*) FILTER (WHERE status='open' AND NOT EXISTS
                          (SELECT 1 FROM offers o WHERE o.request_id=r.id AND o.status='pending')) AS no_offers
               FROM requests r GROUP BY language),
           supply AS (SELECT l AS language, count(*) AS guides FROM guides, unnest(languages) l GROUP BY l)
           SELECT d.*, coalesce(s.guides,0) AS guides
           FROM demand d LEFT JOIN supply s USING (language)
           ORDER BY d.no_offers DESC, d.open DESC, d.total DESC"""
    )
    # Теплокарта «язык × месяц»: доля закрытых заявок.
    heat = await db.fetch(
        """SELECT language, to_char(date_from,'YYYY-MM') AS month,
                  count(*) FILTER (WHERE status <> 'cancelled') AS total,
                  count(*) FILTER (WHERE status IN ('confirmed','done')) AS filled
           FROM requests GROUP BY 1,2 ORDER BY 2,1"""
    )
    months = sorted({h["month"] for h in heat})
    heat_langs = [r["language"] for r in by_lang]
    heat_map = {(h["language"], h["month"]): h for h in heat}

    sites = await db.fetch(
        """SELECT s.*, count(r.id) FILTER (WHERE r.status <> 'cancelled') AS total,
                  count(r.id) FILTER (WHERE r.status='open') AS open
           FROM sites s LEFT JOIN requests r ON s.id = ANY(r.site_ids)
           GROUP BY s.id ORDER BY total DESC"""
    )
    fin = await db.fetchrow(
        """SELECT round(avg(price_per_day)) AS avg_rate,
                  (SELECT round(avg(rating),2) FROM users WHERE role='guide' AND rating IS NOT NULL) AS avg_rating,
                  (SELECT count(*) FROM guides) AS guides,
                  (SELECT coalesce(sum(amount),0) FROM payments WHERE kind='deposit')
                    - (SELECT coalesce(sum(amount),0) FROM payments WHERE kind='refund') AS deposits,
                  (SELECT coalesce(sum(amount),0) FROM payments WHERE kind='subscription') AS subscriptions
           FROM assignments WHERE status <> 'cancelled'"""
    )
    reports = await db.fetch(
        """SELECT rr.id AS report_id, rr.reason, r.id, r.overall, r.text, u.name AS target_name
           FROM review_reports rr JOIN reviews r ON r.id=rr.review_id JOIN users u ON u.id=r.target_id
           WHERE NOT rr.resolved AND NOT r.hidden ORDER BY rr.created_at DESC"""
    )
    broadcasts = await db.fetch("SELECT * FROM broadcasts ORDER BY id DESC LIMIT 5")
    return await render(
        request, "dashboard/index.html", totals=totals, fill_rate=fill_rate, by_lang=by_lang,
        months=months, heat_langs=heat_langs, heat_map=heat_map,
        sites_json=[dict(s) for s in sites], fin=fin,
        reports=reports, broadcasts=broadcasts,
    )


@router.post("/dashboard/broadcast")
async def broadcast(request: Request):
    admin = await require_user(request, "admin")
    form = await request.form()
    language = form.get("language")
    text = (form.get("text") or "").strip()
    if language not in GUIDE_LANGS or not text:
        flash(request, "dash.broadcast_invalid", "error")
        return redirect("/dashboard")
    async with pool().acquire() as conn, conn.transaction():
        # Две аудитории: «набор» — всем гидам (позвать учить дефицитный язык),
        # «спрос» — только тем, кто уже знает язык (есть заявки — берите).
        if form.get("audience") == "lang":
            recipients = await conn.fetch(
                "SELECT u.id FROM guides g JOIN users u ON u.id=g.user_id WHERE $1 = ANY(g.languages)",
                language,
            )
        else:
            recipients = await conn.fetch("SELECT id FROM users WHERE role='guide'")
        for r in recipients:
            await notify_text(conn, r["id"], text)
        await conn.execute(
            "INSERT INTO broadcasts (language, text, recipients, created_by) VALUES ($1,$2,$3,$4)",
            language, text, len(recipients), admin["id"],
        )
    flash(request, "dash.broadcast_sent", count=len(recipients))
    return redirect("/dashboard")
