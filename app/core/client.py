from __future__ import annotations
from fastapi import Request
from elasticsearch import AsyncElasticsearch
from app.core.config import get_settings

settings = get_settings()


def create_es_client() -> AsyncElasticsearch:
    return AsyncElasticsearch(
        hosts=[settings.elasticsearch_url],
        request_timeout=settings.elasticsearch_timeout,
        retry_on_timeout=True,
        max_retries=settings.elasticsearch_max_retries,
    )


def get_es(request: Request) -> AsyncElasticsearch:
    return request.app.state.es


async def check_es_health(es: AsyncElasticsearch) -> bool:
    try:
        return await es.ping()
    except Exception:
        return False
