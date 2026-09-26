"""Верификация личности гида: решения модератора и удаление исходников."""
from ..config import KYC_PENDING_DAYS
from . import media
from .notify import notify

# Что модератор обязан подтвердить, прежде чем одобрить.
CHECKS = ("doc_valid", "name_match", "liveness", "face_match", "photo_match")
REJECT_REASONS = ("doc_unreadable", "doc_invalid", "face_mismatch", "liveness_failed", "photo_bad", "name_mismatch")


def _purge_files(row) -> None:
    media.kyc_delete(row["doc_file"], *(row["selfie_files"] or []))


async def approve(conn, kyc, admin_id: int, checks: list[str]) -> None:
    """Статус «Личность подтверждена», фото — в профиль, сканы документа и селфи — удалить."""
    _purge_files(kyc)
    old_photo = await conn.fetchval("SELECT photo FROM guides WHERE user_id=$1", kyc["guide_id"])
    if old_photo and old_photo != kyc["photo_file"]:
        media.photo_delete(old_photo)
    await conn.execute(
        """UPDATE guide_kyc SET status='approved', checks=$2, reviewer_id=$3, reviewed_at=now(),
               doc_file=NULL, selfie_files=NULL, purged_at=now() WHERE id=$1""",
        kyc["id"], checks, admin_id,
    )
    await conn.execute(
        "UPDATE guides SET id_verified_at=now(), photo=$2 WHERE user_id=$1", kyc["guide_id"], kyc["photo_file"]
    )
    await notify(conn, kyc["guide_id"], "kyc.approved_note", "/verify")


async def reject(conn, kyc, admin_id: int, reason: str) -> None:
    _purge_files(kyc)
    media.photo_delete(kyc["photo_file"])
    await conn.execute(
        """UPDATE guide_kyc SET status='rejected', reject_reason=$2, reviewer_id=$3, reviewed_at=now(),
               doc_file=NULL, selfie_files=NULL, photo_file=NULL, purged_at=now() WHERE id=$1""",
        kyc["id"], reason, admin_id,
    )
    await notify(conn, kyc["guide_id"], "kyc.rejected_note", "/verify")


async def purge_stale(conn) -> int:
    """Заявки без решения дольше KYC_PENDING_DAYS: файлы удаляются, заявка закрывается."""
    rows = await conn.fetch(
        f"""SELECT * FROM guide_kyc WHERE status='pending'
            AND created_at < now() - interval '{int(KYC_PENDING_DAYS)} days'"""
    )
    for r in rows:
        _purge_files(r)
        media.photo_delete(r["photo_file"])
        await conn.execute(
            """UPDATE guide_kyc SET status='rejected', reject_reason='expired', doc_file=NULL,
                   selfie_files=NULL, photo_file=NULL, purged_at=now() WHERE id=$1""", r["id"],
        )
    return len(rows)
