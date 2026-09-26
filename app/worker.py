"""Воркер видеовизиток: перекодирование, постер, превью, проверка звука, язык и субтитры.

Запуск: python -m app.worker (отдельный контейнер). Берёт видео со статусом processing,
после обработки ставит review — дальше решает модератор.
"""
import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path

from .config import VIDEO_MAX_SEC, VIDEO_MIN_SEC
from .db import close_pool, init_pool, pool
from .services import media
from .services.notify import notify

log = logging.getLogger("worker")
_model = None


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=600)


def duration(path: Path) -> float:
    r = _run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path))
    return float(r.stdout.strip() or 0)


def mean_volume(path: Path) -> float | None:
    r = _run("ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-")
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def transcode(src: Path, d: Path) -> None:
    """H.264 + AAC, faststart — играет везде, включая Safari на iPhone. Вертикаль до 720×1280."""
    scale = "scale='if(gt(iw,ih),min(1280,iw),min(720,iw))':-2"
    steps = [
        ["ffmpeg", "-y", "-i", str(src), "-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
         "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-movflags", "+faststart", str(d / "video.mp4")],
        ["ffmpeg", "-y", "-ss", "1", "-i", str(d / "video.mp4"), "-frames:v", "1", "-vf", "scale=360:-2",
         "-q:v", "4", str(d / "poster.jpg")],
        # Превью при наведении: 4 секунды без звука, маленькое.
        ["ffmpeg", "-y", "-t", "4", "-i", str(d / "video.mp4"), "-an", "-vf", "scale=240:-2", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "30", "-movflags", "+faststart", str(d / "preview.mp4")],
    ]
    for cmd in steps:
        r = _run(*cmd)
        if r.returncode:
            raise RuntimeError(r.stderr[-400:])


def _ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02}:{int(m):02}:{s:06.3f}"


def to_vtt(segments) -> str:
    lines = ["WEBVTT", ""]
    for s in segments:
        lines += [f"{_ts(s['start'])} --> {_ts(s['end'])}", s["text"].strip(), ""]
    return "\n".join(lines)


def speech(path: Path) -> dict:
    """Язык речи, доля речи и субтитры: на языке оригинала и английские (перевод Whisper)."""
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, info = _model.transcribe(str(path), vad_filter=True)
    orig = [{"start": s.start, "end": s.end, "text": s.text} for s in segs]
    subs = {info.language: to_vtt(orig)} if orig else {}
    if orig and info.language != "en":
        segs, _ = _model.transcribe(str(path), task="translate", vad_filter=True)
        subs["en"] = to_vtt([{"start": s.start, "end": s.end, "text": s.text} for s in segs])
    spoken = sum(s["end"] - s["start"] for s in orig)
    return {"lang": info.language, "prob": info.language_probability, "spoken": spoken, "subs": subs}


def process(tok: str, check_length: bool = True) -> dict:
    d = media.video_dir(tok)
    src = next(d.glob("upload.*"))
    dur = duration(src)
    if check_length and not (VIDEO_MIN_SEC - 1 <= dur <= VIDEO_MAX_SEC + 1):
        raise ValueError(f"duration:{dur:.0f}")
    transcode(src, d)
    out = {"duration": dur, "size": (d / "video.mp4").stat().st_size,
           "volume": mean_volume(d / "video.mp4"), **speech(d / "video.mp4")}
    src.unlink(missing_ok=True)
    return out


async def handle_one() -> bool:
    db = pool()
    v = await db.fetchrow(
        "SELECT * FROM guide_videos WHERE status='processing' ORDER BY id LIMIT 1"
    )
    if not v:
        return False
    log.info("video %s: start", v["id"])
    try:
        r = await asyncio.to_thread(process, v["token"])
    except Exception as e:  # битый файл, не та длина, ffmpeg упал
        err = str(e)[:300]
        log.warning("video %s: failed %s", v["id"], err)
        async with db.acquire() as conn:
            await conn.execute("UPDATE guide_videos SET status='failed', error=$2 WHERE id=$1", v["id"], err)
            key = "video.failed_length" if err.startswith("duration") else "video.failed"
            await notify(conn, v["guide_id"], key, "/profile/video")
        media.video_delete(v["token"])
        return True
    async with db.acquire() as conn:
        await conn.execute(
            """UPDATE guide_videos SET status='review', duration=$2, size_bytes=$3, mean_volume=$4,
                   speech_ratio=$5, detected_lang=$6, detected_prob=$7, subtitles=$8::jsonb WHERE id=$1""",
            v["id"], r["duration"], r["size"], r["volume"], min(1.0, r["spoken"] / max(r["duration"], 1)),
            r["lang"], r["prob"], json.dumps(r["subs"], ensure_ascii=False),
        )
        for a in await conn.fetch("SELECT id FROM users WHERE role='admin'"):
            await notify(conn, a["id"], "video.to_review", f"/dashboard/video/{v['id']}")
    log.info("video %s: ready for review (%s, %.0fs)", v["id"], r["lang"], r["duration"])
    return True


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    await init_pool(apply_schema=False)
    try:
        while True:
            try:
                busy = await handle_one()
            except Exception as e:  # БД ещё не готова и т. п. — ждём и пробуем снова
                log.warning("worker loop: %s", e)
                busy = False
            if not busy:
                await asyncio.sleep(5)
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
