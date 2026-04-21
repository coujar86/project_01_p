from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class ImageExt(str, Enum):
    jpeg = "jpeg"
    jpg = "jpg"
    png = "png"
    none = "none"


class BlogSearchFilters(BaseModel):
    image_ext: ImageExt | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None

    @field_validator("image_ext", mode="before")
    @classmethod
    def normalize_image_ext(cls, value: str | ImageExt | None) -> str | ImageExt | None:
        if value == "":
            return None
        return value


class ParsedAIBlogSearch(BaseModel):
    q: str
    search_type: Literal["title_content", "author"] = "title_content"
    filters: BlogSearchFilters = Field(default_factory=BlogSearchFilters)


def _build_common_filters(filters: BlogSearchFilters | None = None) -> list[dict]:
    """이미지 확장자 및 날짜 범위를 처리하는 공통 필터 로직"""
    if not filters:
        return []

    filter_opt = []

    if filters.image_ext == ImageExt.none:
        filter_opt.append({"bool": {"must_not": [{"exists": {"field": "image_ext"}}]}})
    elif filters.image_ext is not None:
        filter_opt.append({"term": {"image_ext": filters.image_ext.value}})

    if filters.date_from or filters.date_to:
        date_range = {}
        if filters.date_from:
            date_range["gte"] = filters.date_from.isoformat()
        if filters.date_to:
            date_range["lte"] = filters.date_to.isoformat()
        filter_opt.append({"range": {"modified_dt": date_range}})

    return filter_opt


def _build_search_must_query(
    q: str, search_type: Literal["title_content", "author"]
) -> dict:
    """검색 타입에 따른 Must 절 생성"""
    if search_type == "title_content":
        return {
            "bool": {
                "should": [
                    {"match_phrase": {"title": {"query": q, "boost": 4}}},
                    {
                        "multi_match": {
                            "query": q,
                            "fields": ["title^2", "content"],
                            "type": "best_fields",
                            "minimum_should_match": "75%",
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }
    elif search_type == "author":
        return {
            "term": {
                "author.name": {
                    "value": q,
                    "case_insensitive": True,
                }
            }
        }
    # raise ValueError(f"지원하지 않는 검색 타입입니다: {search_type}")


def build_blog_query(
    *,
    q: str,
    search_type: Literal["title_content", "author"] = "title_content",
    filters: BlogSearchFilters | None = None,
) -> dict:
    return {
        "bool": {
            "must": [_build_search_must_query(q, search_type)],
            "filter": _build_common_filters(filters),
        }
    }


def build_ai_query(
    *,
    q: str,
    search_type: Literal["title_content", "author"] = "title_content",
    filters: BlogSearchFilters | None = None,
) -> dict:
    bool_query = {"filter": _build_common_filters(filters)}
    bool_query["must"] = [_build_search_must_query(q, search_type)]
    return {"bool": bool_query}


def build_knn_filter(filters: BlogSearchFilters | None = None) -> list[dict]:
    return _build_common_filters(filters)
