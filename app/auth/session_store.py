from redis.asyncio import Redis
from app.core.config import get_settings

settings = get_settings()


def _build_session_key(session_id: str) -> str:
    return f"session:{session_id}"


async def store_session(redis: Redis, session_id: str, user_id: int) -> None:
    key = _build_session_key(session_id)
    await redis.set(key, user_id, ex=settings.session_ttl)


async def refresh_session(redis: Redis, session_id: str) -> int | None:
    key = _build_session_key(session_id)

    user_id = await redis.get(key)
    if user_id:
        ttl = await redis.ttl(key)
        if ttl is not None and ttl < settings.session_ttl // 2:
            await redis.expire(key, settings.session_ttl)
        return int(user_id)

    return None


async def delete_session(redis: Redis, session_id: str) -> bool:
    key = _build_session_key(session_id)
    deleted = await redis.delete(key)
    return deleted > 0
