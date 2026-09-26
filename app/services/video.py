"""Видеовизитки: решения модератора и бейджи уровня языка."""
import json

from . import media
from .notify import notify

REJECT_REASONS = ("bad_audio", "wrong_lang", "too_short", "inappropriate", "not_the_guide")


def clean_vtt(text: str) -> str | None:
    """Правка субтитров модератором: пусто — дорожку убрать; иначе обязателен заголовок WEBVTT."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return None
    if not text.startswith("WEBVTT"):
        text = "WEBVTT\n\n" + text
    return text[:20000] + "\n"


async def retire_others(conn, guide_id: int, keep_id: int) -> None:
    """У гида одна визитка на показе: прежние снимаются, файлы удаляются."""
    for old in await conn.fetch(
        "SELECT id, token FROM guide_videos WHERE guide_id=$1 AND id<>$2 AND status IN ('approved','review','processing')",
        guide_id, keep_id,
    ):
        media.video_delete(old["token"])
        await conn.execute("UPDATE guide_videos SET status='replaced' WHERE id=$1", old["id"])


async def approve(conn, v, admin_id: int | None, level: str, subtitles: dict) -> None:
    await retire_others(conn, v["guide_id"], v["id"])
    await conn.execute(
        """UPDATE guide_videos SET status='approved', level=$2, subtitles=$3::jsonb,
               reviewer_id=$4, reviewed_at=now() WHERE id=$1""",
        v["id"], level, json.dumps(subtitles, ensure_ascii=False), admin_id,
    )
    await conn.execute(
        """INSERT INTO guide_lang_levels (guide_id, lang, level, video_id) VALUES ($1,$2,$3,$4)
           ON CONFLICT (guide_id, lang) DO UPDATE SET level=EXCLUDED.level, video_id=EXCLUDED.video_id,
               verified_at=now()""",
        v["guide_id"], v["lang"], level, v["id"],
    )
    await notify(conn, v["guide_id"], "video.approved_note", "/profile/video")


async def reject(conn, v, admin_id: int, reason: str) -> None:
    media.video_delete(v["token"])
    await conn.execute(
        """UPDATE guide_videos SET status='rejected', reject_reason=$2, reviewer_id=$3, reviewed_at=now()
           WHERE id=$1""", v["id"], reason, admin_id,
    )
    await notify(conn, v["guide_id"], "video.rejected_note", "/profile/video")


def subs_of(v) -> dict:
    s = v["subtitles"]
    return s if isinstance(s, dict) else json.loads(s or "{}")


async def current(db, guide_id: int):
    """Одобренная визитка гида (или None) — для каталога и профиля."""
    return await db.fetchrow(
        "SELECT * FROM guide_videos WHERE guide_id=$1 AND status='approved' ORDER BY id DESC LIMIT 1", guide_id
    )
