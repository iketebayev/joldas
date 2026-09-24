"""Оплата в тестовом режиме: пишем платежи в базу, деньги не двигаются.
Интерфейс функций останется тем же при подключении реального провайдера."""
from datetime import date, timedelta

from ..config import DEPOSIT_PERCENT


def deposit_for(total: int) -> int:
    return round(total * DEPOSIT_PERCENT / 100)


async def pay_deposit(conn, assignment) -> None:
    await conn.execute(
        """INSERT INTO payments (kind, assignment_id, amount, status)
           VALUES ('deposit', $1, $2, 'paid_test')""",
        assignment["id"], deposit_for(assignment["total"]),
    )


async def refund_deposit(conn, assignment_id: int) -> int:
    """Возвращает сумму возврата (0, если депозита не было)."""
    paid = await conn.fetchval(
        """SELECT coalesce(sum(amount),0) FROM payments
           WHERE assignment_id=$1 AND kind='deposit' AND status='paid_test'""",
        assignment_id,
    )
    refunded = await conn.fetchval(
        "SELECT coalesce(sum(amount),0) FROM payments WHERE assignment_id=$1 AND kind='refund'",
        assignment_id,
    )
    amount = paid - refunded
    if amount > 0:
        await conn.execute(
            """INSERT INTO payments (kind, assignment_id, amount, status)
               VALUES ('refund', $1, $2, 'refunded_test')""",
            assignment_id, amount,
        )
    return amount


async def subscribe(conn, company_id: int, amount: int) -> None:
    until = date.today() + timedelta(days=30)
    await conn.execute(
        "UPDATE companies SET plan='season', plan_until=$2 WHERE user_id=$1", company_id, until
    )
    await conn.execute(
        """INSERT INTO payments (kind, company_id, amount, status)
           VALUES ('subscription', $1, $2, 'paid_test')""",
        company_id, amount,
    )
