"""Demo login: a signed session cookie holding the user id. Roles are checked here, on the server."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.contracts.api import Me
from app.contracts.enums import Role
from app.db import fetch_one
from app.state import ConnDep, StateDep

COOKIE_NAME = "bn_session"
SESSION_MAX_AGE_S = 7 * 24 * 3600
_SALT = "boardnotes-session"


def sign_session(secret: str, user_id: str) -> str:
    return URLSafeTimedSerializer(secret, salt=_SALT).dumps({"uid": user_id})


def read_session(secret: str, token: str) -> str | None:
    """User id from a cookie value, or None if it is missing, tampered with or expired."""
    try:
        data = URLSafeTimedSerializer(secret, salt=_SALT).loads(token, max_age=SESSION_MAX_AGE_S)
    except BadSignature:  # also covers SignatureExpired
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, str) else None


async def load_profile(conn: ConnDep, user_id: str) -> Me | None:
    row = await fetch_one(conn, "select id, name, role, initials from profiles where id = %(id)s", {"id": user_id})
    return Me.model_validate(row) if row else None


async def current_user(request: Request, state: StateDep, conn: ConnDep) -> Me:
    token = request.cookies.get(COOKIE_NAME)
    user_id = read_session(state.settings.session_secret, token) if token else None
    me = await load_profile(conn, user_id) if user_id else None
    if me is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in")
    return me


CurrentUser = Annotated[Me, Depends(current_user)]


async def require_lecturer(user: CurrentUser) -> Me:
    if user.role != Role.LECTURER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Lecturers only")
    return user


Lecturer = Annotated[Me, Depends(require_lecturer)]
