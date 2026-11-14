"""Demo login, current user, logout and health (D-1)."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.auth import COOKIE_NAME, SESSION_MAX_AGE_S, CurrentUser, load_profile, sign_session
from app.contracts.api import DemoLogin, Me
from app.db import fetch_one
from app.state import ConnDep, StateDep

router = APIRouter()


@router.get("/health", tags=["meta"])
async def health(conn: ConnDep) -> dict[str, str]:
    await fetch_one(conn, "select 1")
    return {"status": "ok"}


@router.post("/auth/demo-login", tags=["auth"])
async def demo_login(body: DemoLogin, request: Request, response: Response, state: StateDep, conn: ConnDep) -> Me:
    me = await load_profile(conn, body.user_id)
    if me is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown demo user")
    response.set_cookie(
        COOKIE_NAME,
        sign_session(state.settings.session_secret, me.id),
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )
    return me


@router.get("/auth/me", tags=["auth"])
async def me(user: CurrentUser) -> Me:
    return user


@router.post("/auth/logout", tags=["auth"], status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")
