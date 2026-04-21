from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_search_blogs_failed(client):
    with patch(
        "app.routers.blog.BlogService.search_blogs", new_callable=AsyncMock
    ) as mock_search_blogs:
        # q 없음
        res1 = await client.get("/blogs/search", follow_redirects=False)
        assert res1.status_code == 303

        # q 공백만
        res2 = await client.get(
            "/blogs/search", params={"q": "   "}, follow_redirects=False
        )
        assert res2.status_code == 303
        mock_search_blogs.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_blogs(client, es_client, es_index, doc_payload_v1):
    doc = doc_payload_v1
    try:
        await es_client.index(
            index=es_index,
            id=str(doc["id"]),
            document=doc,
            refresh=True,
        )

        params = {"q": "  사과  ", "search_type": "title_content", "page": 1}
        res = await client.get("/blogs/search", params=params)

        assert res.status_code == 200
        assert re.search(r'<h2 class="fw-bold">\s*사과\s*</h2>', res.text)

        assert 'value="사과"' in res.text

        assert re.search(
            r'id="search_title_content"[^>]*value="title_content"[^>]*checked',
            res.text,
        )
    finally:
        await es_client.delete(index=es_index, id=str(doc["id"]), refresh=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image_ext,date_from,date_to,should_match",
    [
        ("png", None, None, True),  # [1]
        ("png", "2025-12-31", None, True),  # [2]
        ("png", None, "2026-01-01", True),  # [3]
        ("jpg", None, None, False),  # [4]
        ("png", "2026-01-06", None, False),  # [5]
        ("png", None, "2025-12-31", False),  # [6]
    ],
)
async def test_search_blogs_filters_es(
    client,
    es_client,
    es_index,
    doc_payload_v1,
    image_ext: str,
    date_from: str | None,
    date_to: str | None,
    should_match: bool,
):
    doc_id = doc_payload_v1["id"]
    doc = doc_payload_v1

    try:
        await es_client.index(
            index=es_index,
            id=str(doc_id),
            document=doc,
            refresh=True,
        )

        params = {
            "q": "사과",
            "search_type": "title_content",
            "image_ext": image_ext,
            "page": 1,
        }

        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to

        res = await client.get("/blogs/search", params=params)
        assert res.status_code == 200

        title = str(doc_payload_v1["title"])
        title_h2_re = rf'<h2 class="fw-bold">\s*{re.escape(title)}\s*</h2>'
        matched = re.search(title_h2_re, res.text) is not None
        assert matched is should_match
    finally:
        await es_client.delete(index=es_index, id=str(doc_id), refresh=True)


# pytest tests/es/test_blog_search.py
