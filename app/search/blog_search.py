from typing import Literal
from elasticsearch import AsyncElasticsearch
from app.core.config import get_settings
from app.core.logging import get_logger
from app.search.blog_queries import (
    BlogSearchFilters,
    ParsedAIBlogSearch,
    build_blog_query,
    build_ai_query,
    build_knn_filter,
)
from app.search.blog_sync import embedding_text
from app.utils import util

logger = get_logger(__name__)
settings = get_settings()

ES_PAGE_SIZE = settings.BLOGS_PER_PAGE
ES_SOURCE_FIELDS = [
    "id",
    "title",
    "content",
    "image_loc",
    "image_ext",
    "modified_dt",
    "author",
]


def _parse_blog_search_items(hits: list[dict]) -> list[dict]:
    """ES 검색 결과(hits 리스트)를 서비스용 리스트로 변환"""
    items = []
    for hit in hits:
        source_data = hit.get("_source")
        if not source_data:
            continue

        raw_image_loc = source_data.get("image_loc")
        image_loc = util.resolve_image_loc(raw_image_loc)

        raw_content = source_data.get("content", "")
        truncated_content = util.truncate_text(raw_content)

        item = {
            "id": source_data.get("id"),
            "title": source_data.get("title"),
            "content": truncated_content,
            "image_loc": image_loc,
            "image_ext": source_data.get("image_ext"),
            "modified_dt": source_data.get("modified_dt"),
            "author": source_data.get("author", {}).get("name"),
        }
        items.append(item)

    return items


async def _search_execute(
    es: AsyncElasticsearch, query: dict, page: int, knn: dict | None = None
) -> dict[str, int | list[dict]]:
    """ES 검색 실행 및 결과 파싱"""
    from_ = (page - 1) * ES_PAGE_SIZE
    body = {
        "query": query,
        "from": from_,
        "size": ES_PAGE_SIZE,
        "track_total_hits": True,
        "_source": ES_SOURCE_FIELDS,
    }
    if knn:
        body["knn"] = knn

    response = await es.search(index=settings.elasticsearch_index_blogs, body=body)

    hits = response.get("hits", {}).get("hits", [])
    total = response.get("hits", {}).get("total", {}).get("value", 0)
    items = _parse_blog_search_items(hits)
    # logger.error(f"{items}")
    return {"total": total, "items": items}


async def search_blogs_es(
    es: AsyncElasticsearch,
    *,
    q: str,
    search_type: Literal["title_content", "author"] = "title_content",
    page: int,
    filters: BlogSearchFilters | None = None,
) -> tuple[list[dict], int, int]:
    query = build_blog_query(q=q, search_type=search_type, filters=filters)
    result = await _search_execute(es, query, page)

    total = result["total"]
    blogs = result["items"]

    total_pages, current_page = util.calc_pagination(
        total=total, page=page, per_page=ES_PAGE_SIZE
    )
    return blogs, total_pages, current_page


async def ai_search_blogs_es(
    es: AsyncElasticsearch,
    *,
    parsed: ParsedAIBlogSearch,
    page: int,
) -> tuple[list[dict], int, int]:
    if not parsed.q:
        raise ValueError("검색어 추출 불가")

    knn = None
    if parsed.search_type == "title_content":
        embedding_vector = await embedding_text(parsed.q)
        required_size = util.calc_required_size(page=page, per_page=ES_PAGE_SIZE)
        knn_filter = build_knn_filter(parsed.filters)
        knn = {
            "field": "embedding",
            "query_vector": embedding_vector,
            "k": required_size,
            "num_candidates": required_size * 4,
            "filter": knn_filter,
        }

    query = build_ai_query(
        q=parsed.q, search_type=parsed.search_type, filters=parsed.filters
    )
    result = await _search_execute(es, query, page, knn)

    total = result["total"]
    blogs = result["items"]

    total_pages, current_page = util.calc_pagination(
        total=total, page=page, per_page=ES_PAGE_SIZE
    )
    return blogs, total_pages, current_page
