import bcrypt
from fastapi import HTTPException, Request

from .db import pool


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


async def current_user(request: Request):
    uid = request.session.get("uid")
    if not uid:
        return None
    return await pool().fetchrow("SELECT * FROM users WHERE id=$1", uid)


class LoginRequired(Exception):
    pass


async def require_user(request: Request, *roles: str):
    user = await current_user(request)
    if user is None:
        raise LoginRequired()
    if roles and user["role"] not in roles:
        raise HTTPException(status_code=403)
    return user
