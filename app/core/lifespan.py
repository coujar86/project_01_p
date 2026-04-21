import redis.asyncio as redis
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.core.logging import get_logger
from app.core.config import get_settings
from app.core.client import create_es_client, check_es_health
from app.search import ensure_blog_index
from app.db.database import engine

logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):

    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)

    es_client = create_es_client()
    app.state.es = es_client

    es_healthy = await check_es_health(es_client)
    app.state.es_healthy = es_healthy

    if es_healthy:
        logger.info("Elasticsearch connected successfully")
        await ensure_blog_index(es_client)
    else:
        logger.error("Elasticsearch connection failed")

    yield

    await app.state.redis.aclose()
    await engine.dispose()
    await es_client.close()
