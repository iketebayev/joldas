import random
import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from ..auth import current_user, require_user
from ..config import (DOC_TYPES, KYC_CHALLENGES, PHOTO_MAX_MB, VIDEO_MAX_MB, VIDEO_MAX_SEC,
                      VIDEO_MIN_SEC)
from ..db import pool
from ..services import media
from ..services import video as videos
from ..services.notify import notify
from ..web import flash, redirect, render

router = APIRouter()


async def _latest_kyc(guide_id: int):
    return await pool().fetchrow(
        "SELECT * FROM guide_kyc WHERE guide_id=$1 ORDER BY id DESC LIMIT 1", guide_id
    )


@router.get("/verify")
async def verify_page(request: Request):
    user = await require_user(request, "guide")
    g = await pool().fetchrow("SELECT * FROM guides WHERE user_id=$1", user["id"])
    kyc = await _latest_kyc(user["id"])
    # Задания для живого селфи выдаёт сервер и помнит в сессии — подменить их из браузера нельзя.
    challenges = request.session.get("kyc_ch")
    if not challenges:
        challenges = random.sample(KYC_CHALLENGES, 2)
        request.session["kyc_ch"] = challenges
    return await render(request, "verify/index.html", g=g, kyc=kyc, challenges=challenges,
                        doc_types=DOC_TYPES, photo_max=PHOTO_MAX_MB)


async def _read_image(upload, max_mb: int) -> bytes:
    if upload is None or not hasattr(upload, "read"):
        raise media.BadFile("missing")
    data = await upload.read()
    if not data:
        raise media.BadFile("missing")
    if len(data) > max_mb * 1024 * 1024:
        raise media.BadFile("big")
    return data


@router.post("/verify")
async def verify_submit(request: Request):
    user = await require_user(request, "guide")
    form = await request.form()
    challenges = request.session.get("kyc_ch")
    kyc = await _latest_kyc(user["id"])
    if kyc and kyc["status"] in ("pending", "approved"):
        return redirect("/verify")
    if not form.get("consent"):
        flash(request, "kyc.need_consent", "error")
        return redirect("/verify")
    doc_type = form.get("doc_type")
    if doc_type not in DOC_TYPES or not challenges:
        flash(request, "kyc.bad_file", "error")
        return redirect("/verify")
    try:
        doc = media.clean_image(await _read_image(form.get("doc"), PHOTO_MAX_MB), 2000)
        selfies = [media.clean_image(await _read_image(form.get(f"selfie_{i}"), PHOTO_MAX_MB), 1280)
                   for i in range(len(challenges))]
        photo = media.profile_photo(await _read_image(form.get("photo"), PHOTO_MAX_MB))
    except media.BadFile as e:
        flash(request, "kyc.bad_file_" + str(e), "error")
        return redirect("/verify")
    doc_file = media.kyc_save(doc)
    selfie_files = [media.kyc_save(s) for s in selfies]
    photo_file = media.photo_save(photo)
    async with pool().acquire() as conn, conn.transaction():
        kid = await conn.fetchval(
            """INSERT INTO guide_kyc (guide_id, doc_type, doc_file, selfie_files, challenges, photo_file, consent_at)
               VALUES ($1,$2,$3,$4,$5,$6,now()) RETURNING id""",
            user["id"], doc_type, doc_file, selfie_files, challenges, photo_file,
        )
        for a in await conn.fetch("SELECT id FROM users WHERE role='admin'"):
            await notify(conn, a["id"], "kyc.to_review", f"/dashboard/kyc/{kid}")
    request.session.pop("kyc_ch", None)
    flash(request, "kyc.sent")
    return redirect("/verify")


# --- видеовизитка --------------------------------------------------------------------

@router.get("/profile/video")
async def video_page(request: Request):
    user = await require_user(request, "guide")
    db = pool()
    g = await db.fetchrow("SELECT * FROM guides WHERE user_id=$1", user["id"])
    latest = await db.fetchrow(
        "SELECT * FROM guide_videos WHERE guide_id=$1 AND status<>'replaced' ORDER BY id DESC LIMIT 1", user["id"]
    )
    live = await videos.current(db, user["id"])
    return await render(request, "verify/video.html", g=g, latest=latest, live=live,
                        max_mb=VIDEO_MAX_MB, min_sec=VIDEO_MIN_SEC, max_sec=VIDEO_MAX_SEC)


@router.post("/profile/video")
async def video_upload(request: Request):
    user = await require_user(request, "guide")
    form = await request.form()
    f, lang = form.get("video"), form.get("lang")
    g = await pool().fetchrow("SELECT languages FROM guides WHERE user_id=$1", user["id"])
    if lang not in (g["languages"] or []):
        flash(request, "video.bad_lang", "error")
        return redirect("/profile/video")
    ctype = (getattr(f, "content_type", "") or "").split(";")[0]
    if not hasattr(f, "read") or ctype not in media.VIDEO_TYPES:
        flash(request, "video.bad_type", "error")
        return redirect("/profile/video")
    if (f.size or 0) > VIDEO_MAX_MB * 1024 * 1024 or not f.size:
        flash(request, "video.too_big", "error")
        return redirect("/profile/video")
    tok = media.token()
    d = media.video_dir(tok)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"upload.{media.VIDEO_TYPES[ctype]}", "wb") as out:
        shutil.copyfileobj(f.file, out, 1024 * 1024)
    async with pool().acquire() as conn, conn.transaction():
        # Новая загрузка заменяет ту, что ещё в обработке или на проверке; одобренная висит до решения.
        for old in await conn.fetch(
            "SELECT id, token FROM guide_videos WHERE guide_id=$1 AND status IN ('processing','review')", user["id"]
        ):
            media.video_delete(old["token"])
            await conn.execute("UPDATE guide_videos SET status='replaced' WHERE id=$1", old["id"])
        await conn.execute(
            "INSERT INTO guide_videos (guide_id, token, lang) VALUES ($1,$2,$3)", user["id"], tok, lang
        )
    flash(request, "video.sent")
    return redirect("/profile/video")


@router.post("/profile/video/delete")
async def video_delete(request: Request):
    user = await require_user(request, "guide")
    async with pool().acquire() as conn, conn.transaction():
        for v in await conn.fetch(
            "SELECT id, token FROM guide_videos WHERE guide_id=$1 AND status IN ('approved','processing','review')",
            user["id"],
        ):
            media.video_delete(v["token"])
            await conn.execute("UPDATE guide_videos SET status='replaced' WHERE id=$1", v["id"])
            await conn.execute("DELETE FROM guide_lang_levels WHERE video_id=$1", v["id"])
    flash(request, "video.deleted")
    return redirect("/profile/video")


# --- раздача медиа: одобренное — всем, остальное — владельцу и модератору -----------------

PUBLIC_CACHE = {"Cache-Control": "public, max-age=86400"}
PRIVATE = {"Cache-Control": "private, no-store"}


@router.get("/media/photo/{name}")
async def photo(request: Request, name: str):
    db = pool()
    if await db.fetchval("SELECT 1 FROM guides WHERE photo=$1", name):
        headers = PUBLIC_CACHE
    else:
        user = await current_user(request)
        owner = user and await db.fetchval(
            "SELECT 1 FROM guide_kyc WHERE photo_file=$1 AND guide_id=$2", name, user["id"]
        )
        if not (user and (user["role"] == "admin" or owner)):
            raise HTTPException(404)
        headers = PRIVATE
    path = media.photo_path(name)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers=headers)


async def _video_access(request: Request, tok: str):
    v = await pool().fetchrow("SELECT * FROM guide_videos WHERE token=$1", tok)
    if not v:
        raise HTTPException(404)
    if v["status"] == "approved":
        return v, PUBLIC_CACHE
    user = await current_user(request)
    if user and (user["role"] == "admin" or user["id"] == v["guide_id"]):
        return v, PRIVATE
    raise HTTPException(404)


@router.get("/media/video/{tok}/{name}")
async def video_file(request: Request, tok: str, name: str):
    types = {"video.mp4": "video/mp4", "preview.mp4": "video/mp4", "poster.jpg": "image/jpeg"}
    if name not in types:
        raise HTTPException(404)
    _, headers = await _video_access(request, tok)
    path = media.video_dir(tok) / name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type=types[name], headers=headers)


@router.get("/media/video/{tok}/subs/{lang}.vtt")
async def video_subs(request: Request, tok: str, lang: str):
    v, headers = await _video_access(request, tok)
    subs = videos.subs_of(v)
    if lang not in subs:
        raise HTTPException(404)
    return Response(subs[lang], media_type="text/vtt; charset=utf-8", headers=headers)
