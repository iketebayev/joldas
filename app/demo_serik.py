"""Демо-гид Серик: фото профиля и видеовизитка из хранилища.

Запуск в контейнере воркера (там ffmpeg и распознавание речи):
    docker compose exec worker python -m app.demo_serik /data/media/import/serik.jpg /data/media/import/serik.mp4

Создаёт гида, если его нет, ставит фото и статус «личность подтверждена» (демо-гид, как остальные
из сида), обрабатывает видео и отправляет его модератору. Уровень языка и правку субтитров
выставляет модератор в /dashboard/verify — как для любого гида.
Ролик в демо короче 30 секунд, поэтому проверка длины здесь пропущена.
"""
import asyncio
import json
import shutil
import sys
from pathlib import Path

from .auth import hash_password
from .config import DEMO_PASSWORD
from .db import close_pool, init_pool, pool
from .services import media
from .services.notify import notify
from .worker import process

EMAIL = "serik@demo.kz"
BIO = ("Гид из Актау, веду туры на французском и английском. Люблю каспийское побережье, "
       "подземные мечети Шакпак-ата и Бекет-ата и закаты на Бозжыре.")


async def main(photo: str, video: str):
    await init_pool(apply_schema=False)
    db = pool()
    uid = await db.fetchval("SELECT id FROM users WHERE email=$1", EMAIL)
    if not uid:
        region = await db.fetchval("SELECT id FROM regions WHERE code='mangystau'")
        sites = await db.fetch(
            "SELECT id FROM sites WHERE slug = ANY($1::text[])",
            ["bozjyra", "tuzbair", "kyzylkup", "shakpak_ata", "beket_ata", "sherkala"],
        )
        async with db.acquire() as conn, conn.transaction():
            uid = await conn.fetchval(
                """INSERT INTO users (role, name, email, phone, password_hash, ui_lang, is_demo)
                   VALUES ('guide', 'Серик Жаксыбеков', $1, '+70000000900', $2, 'ru', TRUE) RETURNING id""",
                EMAIL, hash_password(DEMO_PASSWORD),
            )
            await conn.execute(
                """INSERT INTO guides (user_id, region_id, languages, specializations, site_ids,
                       day_rate, experience_years, bio) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                uid, region, ["fr", "en", "ru", "kk"], ["sacred", "hiking", "photo"],
                [s["id"] for s in sites], 35000, 6, BIO,
            )
    old = await db.fetchval("SELECT photo FROM guides WHERE user_id=$1", uid)
    name = media.photo_save(media.profile_photo(Path(photo).read_bytes()))
    await db.execute("UPDATE guides SET photo=$2, id_verified_at=now() WHERE user_id=$1", uid, name)
    media.photo_delete(old if old != name else None)

    tok = media.token()
    d = media.video_dir(tok)
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(video, d / ("upload" + Path(video).suffix.lower()))
    r = await asyncio.to_thread(process, tok, False)
    async with db.acquire() as conn, conn.transaction():
        for v in await conn.fetch(
            "SELECT id, token FROM guide_videos WHERE guide_id=$1 AND status IN ('processing','review')", uid
        ):
            media.video_delete(v["token"])
            await conn.execute("UPDATE guide_videos SET status='replaced' WHERE id=$1", v["id"])
        vid = await conn.fetchval(
            """INSERT INTO guide_videos (guide_id, token, lang, status, duration, size_bytes, mean_volume,
                   speech_ratio, detected_lang, detected_prob, subtitles)
               VALUES ($1,$2,$3,'review',$4,$5,$6,$7,$8,$9,$10::jsonb) RETURNING id""",
            uid, tok, r["lang"], r["duration"], r["size"], r["volume"],
            min(1.0, r["spoken"] / max(r["duration"], 1)), r["lang"], r["prob"],
            json.dumps(r["subs"], ensure_ascii=False),
        )
        for a in await conn.fetch("SELECT id FROM users WHERE role='admin'"):
            await notify(conn, a["id"], "video.to_review", f"/dashboard/video/{vid}")
    print(f"guide {uid}, photo {name}, video {vid} → review ({r['lang']} {r['prob']:.2f}, {r['duration']:.0f}s)")
    await close_pool()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
