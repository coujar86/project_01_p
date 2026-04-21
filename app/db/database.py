from redis.asyncio import Redis
from fastapi import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy import event
from app.core.logging import get_logger
from app.core.config import get_settings
from app.core.context import (
    get_request_id,
    inc_query_count,
    add_query_samples,
)
import time


logger = get_logger(__name__)
settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=0,
    pool_recycle=200,
    pool_timeout=10,
    echo=False,
)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    duration_ms = (time.perf_counter() - context._query_start_time) * 1000

    inc_query_count()

    normalized = " ".join(statement.split())
    stmt = normalized
    if len(stmt) > settings.db_statement_maxlen:
        stmt = stmt[: settings.db_statement_maxlen] + ".."

    add_query_samples(duration_ms, stmt, limit=settings.db_query_sample_limit)

    if duration_ms >= settings.db_slow_query_ms:
        request_id = get_request_id()
        stmt_full = normalized
        if len(stmt_full) > settings.db_statement_maxlen:
            stmt_full = stmt_full[: settings.db_statement_maxlen] + ".."
        logger.warning(
            "slow query detected",
            extra={
                "request_id": request_id,
                "duration_ms": round(duration_ms, 2),
                "statement": stmt_full,
                "rowcount": getattr(cursor, "rowcount", None),
            },
        )


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_redis(request: Request) -> Redis:
    return request.app.state.redis
