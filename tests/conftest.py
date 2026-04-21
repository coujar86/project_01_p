from __future__ import annotations

import os
import httpx
import pytest_asyncio
import fakeredis.aioredis

from elasticsearch import AsyncElasticsearch
from dotenv import load_dotenv
from typing import AsyncGenerator
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import Base
from app.search.index import BLOG_INDEX_CONFIG
from app.routers import blog, auth, debug


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.test"))

settings = get_settings()


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(blog.router)
    app.include_router(auth.router)
    app.include_router(debug.router)
    return app


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables(test_engine):
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session(test_engine, create_tables) -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.connect() as conn:
        trans = await conn.begin()

        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            autoflush=False,
        )

        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest_asyncio.fixture(scope="session")
async def es_client():
    es = AsyncElasticsearch(settings.elasticsearch_url)
    await es.ping()
    yield es
    await es.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def es_index(es_client):
    index = settings.elasticsearch_index_blogs

    await es_client.indices.delete(index=index, ignore=[404])
    await es_client.indices.create(index=index, body=BLOG_INDEX_CONFIG)
    yield index
    await es_client.indices.delete(index=index, ignore=[404])


@pytest_asyncio.fixture
async def fake_redis():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest_asyncio.fixture
async def client(
    db_session, fake_redis, es_client
) -> AsyncGenerator[httpx.AsyncClient, None]:
    app = create_test_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.state.redis = fake_redis
    app.state.es = es_client

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
