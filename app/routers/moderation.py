"""Модерация: верификация личности гидов и видеовизитки."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..auth import require_user
from ..config import UI_LANGS, VIDEO_LEVELS
from ..db import pool
from ..services import kyc as K
from ..services import media
from ..services import video as V
from ..web import flash, redirect, render

router = APIRouter()
NO_STORE = {"Cache-Control": "private, no-store"}


@router.get("/dashboard/verify")
async def queue(request: Request):
    await require_user(request, "admin")
    db = pool()
    kyc = await db.fetch(
        """SELECT k.*, u.name FROM guide_kyc k JOIN users u ON u.id=k.guide_id
           WHERE k.status='pending' ORDER BY k.created_at"""
    )
    vids = await db.fetch(
        """SELECT v.*, u.name FROM guide_videos v JOIN users u ON u.id=v.guide_id
           WHERE v.status IN ('review','processing') ORDER BY v.created_at"""
    )
    done = await db.fetch(
        """(SELECT 'kyc' AS kind, k.id, u.name, k.status, k.reviewed_at, k.reject_reason AS reason, NULL AS level
            FROM guide_kyc k JOIN users u ON u.id=k.guide_id WHERE k.reviewed_at IS NOT NULL)
           UNION ALL
           (SELECT 'video', v.id, u.name, v.status, v.reviewed_at, v.reject_reason, v.level
            FROM guide_videos v JOIN users u ON u.id=v.guide_id WHERE v.reviewed_at IS NOT NULL)
           ORDER BY reviewed_at DESC LIMIT 15"""
    )
    return await render(request, "moderation/queue.html", kyc=kyc, vids=vids, done=done)


async def _kyc(kid: int):
    k = await pool().fetchrow(
        """SELECT k.*, u.name, u.email, u.phone FROM guide_kyc k JOIN users u ON u.id=k.guide_id
           WHERE k.id=$1""", kid,
    )
    if not k:
        raise HTTPException(404)
    return k


@router.get("/dashboard/kyc/{kid}")
async def kyc_detail(request: Request, kid: int):
    await require_user(request, "admin")
    return await render(request, "moderation/kyc.html", k=await _kyc(kid), checks=K.CHECKS,
                        reasons=K.REJECT_REASONS)


@router.get("/dashboard/kyc/{kid}/file/{kind}/{i}")
async def kyc_file(request: Request, kid: int, kind: str, i: int):
    """Расшифровка скана только для модератора и только пока заявка не решена."""
    await require_user(request, "admin")
    k = await _kyc(kid)
    name = k["doc_file"] if kind == "doc" else (
        (k["selfie_files"] or [None] * (i + 1))[i] if kind == "selfie" and i < len(k["selfie_files"] or []) else None)
    if not name:
        raise HTTPException(404)
    return Response(media.kyc_read(name), media_type="image/jpeg", headers=NO_STORE)


@router.post("/dashboard/kyc/{kid}/approve")
async def kyc_approve(request: Request, kid: int):
    admin = await require_user(request, "admin")
    form = await request.form()
    checks = [c for c in K.CHECKS if form.get(c)]
    k = await _kyc(kid)
    if k["status"] != "pending":
        return redirect("/dashboard/verify")
    if len(checks) != len(K.CHECKS):
        flash(request, "mod.need_all_checks", "error")
        return redirect(f"/dashboard/kyc/{kid}")
    async with pool().acquire() as conn, conn.transaction():
        await K.approve(conn, k, admin["id"], checks)
    flash(request, "mod.kyc_approved", name=k["name"])
    return redirect("/dashboard/verify")


@router.post("/dashboard/kyc/{kid}/reject")
async def kyc_reject(request: Request, kid: int):
    admin = await require_user(request, "admin")
    reason = (await request.form()).get("reason")
    k = await _kyc(kid)
    if k["status"] != "pending" or reason not in K.REJECT_REASONS:
        return redirect(f"/dashboard/kyc/{kid}")
    async with pool().acquire() as conn, conn.transaction():
        await K.reject(conn, k, admin["id"], reason)
    flash(request, "mod.rejected")
    return redirect("/dashboard/verify")


async def _video(vid: int):
    v = await pool().fetchrow(
        """SELECT v.*, u.name, g.languages FROM guide_videos v JOIN users u ON u.id=v.guide_id
           JOIN guides g ON g.user_id=v.guide_id WHERE v.id=$1""", vid,
    )
    if not v:
        raise HTTPException(404)
    return v


@router.get("/dashboard/video/{vid}")
async def video_detail(request: Request, vid: int):
    await require_user(request, "admin")
    v = await _video(vid)
    subs = V.subs_of(v)
    # Автоматические дорожки + пустые поля для языков интерфейса: модератор может добавить перевод.
    langs = list(subs) + [x for x in UI_LANGS if x not in subs]
    return await render(request, "moderation/video.html", v=v, subs=subs, sub_langs=langs, levels=VIDEO_LEVELS,
                        reasons=V.REJECT_REASONS)


@router.post("/dashboard/video/{vid}/approve")
async def video_approve(request: Request, vid: int):
    admin = await require_user(request, "admin")
    form = await request.form()
    v = await _video(vid)
    level = form.get("level")
    if v["status"] != "review" or level not in VIDEO_LEVELS:
        flash(request, "mod.need_level", "error")
        return redirect(f"/dashboard/video/{vid}")
    subs = {}
    auto = V.subs_of(v)
    for lang in [*auto, *(x for x in UI_LANGS if x not in auto)]:
        text = V.clean_vtt(form.get(f"sub_{lang}"))
        if text:
            subs[lang] = text
    async with pool().acquire() as conn, conn.transaction():
        await V.approve(conn, v, admin["id"], level, subs)
    flash(request, "mod.video_approved", name=v["name"])
    return redirect("/dashboard/verify")


@router.post("/dashboard/video/{vid}/reject")
async def video_reject(request: Request, vid: int):
    admin = await require_user(request, "admin")
    reason = (await request.form()).get("reason")
    v = await _video(vid)
    if v["status"] != "review" or reason not in V.REJECT_REASONS:
        return redirect(f"/dashboard/video/{vid}")
    async with pool().acquire() as conn, conn.transaction():
        await V.reject(conn, v, admin["id"], reason)
    flash(request, "mod.rejected")
    return redirect("/dashboard/verify")
