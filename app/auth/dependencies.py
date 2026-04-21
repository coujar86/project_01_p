from fastapi import HTTPException, Request, Response, Depends
from app.core.config import get_settings
from app.db.database import get_redis
from app.auth.session_store import refresh_session
import uuid

settings = get_settings()


def create_session_id() -> str:
    return str(uuid.uuid4())


async def get_user_id(request: Request, redis=Depends(get_redis)) -> int:
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(detail="인증 실패, session_id", status_code=401)

    user_id = await refresh_session(redis, session_id)
    if not user_id:
        raise HTTPException(detail="인증 실패, user_id", status_code=401)

    return user_id


async def get_user_id_optional(
    request: Request, redis=Depends(get_redis)
) -> int | None:
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None

    user_id = await refresh_session(redis, session_id)
    return user_id


def set_auth_cookies(response: Response, session_id: str) -> None:
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
        max_age=settings.session_ttl,
    )
