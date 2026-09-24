"""Рейтинг — байесовское среднее, уровень опыта — по заказам и рейтингу."""
from ..config import BAYES_C, BAYES_DEFAULT_MEAN, LEVEL_EXPERIENCED, LEVEL_EXPERT


def level_for(completed: int, rating: float | None) -> str:
    r = rating or 0
    if completed >= LEVEL_EXPERT[0] and r >= LEVEL_EXPERT[1]:
        return "expert"
    if completed >= LEVEL_EXPERIENCED[0] and r >= LEVEL_EXPERIENCED[1]:
        return "experienced"
    return "novice"


def bayes(total: float, n: int, mean: float) -> float | None:
    if n == 0:
        return None
    return (BAYES_C * mean + total) / (BAYES_C + n)


async def _mean(conn, role: str) -> float:
    m = await conn.fetchval(
        "SELECT avg(overall) FROM reviews WHERE target_role=$1 AND NOT hidden", role
    )
    return float(m) if m is not None else BAYES_DEFAULT_MEAN


async def recompute_all(conn) -> None:
    """Средняя по площадке меняется с каждым отзывом, поэтому пересчитываем всех —
    пользователей немного, это дёшево и держит рейтинги согласованными."""
    for role in ("guide", "client"):
        mean = await _mean(conn, role)
        rows = await conn.fetch(
            """SELECT target_id, sum(overall) AS s, count(*) AS n
               FROM reviews WHERE target_role=$1 AND NOT hidden GROUP BY target_id""",
            role,
        )
        await conn.execute(
            """UPDATE users SET rating=NULL, reviews_count=0
               WHERE role = ANY($1::text[])""",
            ["guide"] if role == "guide" else ["company", "tourist"],
        )
        for r in rows:
            rating = bayes(float(r["s"]), r["n"], mean)
            await conn.execute(
                "UPDATE users SET rating=$2, reviews_count=$3 WHERE id=$1",
                r["target_id"], round(rating, 2), r["n"],
            )

    await conn.execute(
        """UPDATE guides g SET completed_count = (
               SELECT count(*) FROM assignments a WHERE a.guide_id=g.user_id AND a.status='done')"""
    )
    for g in await conn.fetch(
        "SELECT g.user_id, g.completed_count, u.rating FROM guides g JOIN users u ON u.id=g.user_id"
    ):
        rating = float(g["rating"]) if g["rating"] is not None else None
        await conn.execute(
            "UPDATE guides SET level=$2 WHERE user_id=$1",
            g["user_id"], level_for(g["completed_count"], rating),
        )
