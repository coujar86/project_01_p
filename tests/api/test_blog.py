from __future__ import annotations
from sqlalchemy import func, select
from app.db.models import Blog
import pytest


async def _signup_and_login(client, user_payload):
    res = await client.post(
        "/auth/signup",
        data=user_payload,
        follow_redirects=False,
    )
    assert res.status_code == 303

    res = await client.post(
        "/auth/login",
        data={"email": user_payload["email"], "password": user_payload["password"]},
        follow_redirects=False,
    )
    assert res.status_code == 303


async def _latest_blog_id(db_session) -> int:
    result = await db_session.execute(select(func.max(Blog.id)))
    blog_id = result.scalar_one_or_none()
    assert blog_id is not None
    return int(blog_id)


@pytest.mark.asyncio
async def test_crud(client, db_session, user_payload, blog_payload):
    await _signup_and_login(client, user_payload)

    res = await client.post("/blogs/new", data=blog_payload, follow_redirects=False)
    assert res.status_code == 303
    assert res.headers.get("location") in ("/blogs", "http://test/blogs")

    blog_id = await _latest_blog_id(db_session)

    res = await client.get(f"/blogs/show/{blog_id}")
    assert res.status_code == 200
    assert blog_payload["title"] in res.text
    assert blog_payload["content"] in res.text

    update_payload = {"title": "update_title", "content": "update_content"}

    res = await client.put(
        f"/blogs/modify/{blog_id}",
        data=update_payload,
        follow_redirects=False,
    )
    assert res.status_code == 303

    res = await client.get(f"/blogs/show/{blog_id}")
    assert res.status_code == 200

    assert update_payload["title"] in res.text
    assert update_payload["content"] in res.text

    assert blog_payload["title"] not in res.text
    assert blog_payload["content"] not in res.text

    res = await client.delete(f"/blogs/delete/{blog_id}")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_blog_not_found(client, user_payload, blog_payload):
    await _signup_and_login(client, user_payload)
    blog_id = 9999999

    res = await client.get(f"/blogs/show/{blog_id}")
    assert res.status_code == 404
    assert res.json()["detail"] == "블로그 글 없음"

    res = await client.put(
        f"/blogs/modify/{blog_id}",
        data=blog_payload,
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "블로그 글 없음"

    res = await client.delete(f"/blogs/delete/{blog_id}")
    assert res.status_code == 404
    assert res.json()["detail"] == "블로그 글 없음"


@pytest.mark.asyncio
async def test_blog_forbidden(client, db_session, user_payload, blog_payload):
    await _signup_and_login(client, user_payload)

    res = await client.post("/blogs/new", data=blog_payload, follow_redirects=False)
    assert res.status_code == 303

    blog_id = await _latest_blog_id(db_session)

    other_user = {"name": "other", "email": "other@example.com", "password": "qwerty"}
    await _signup_and_login(client, other_user)

    res = await client.put(
        f"/blogs/modify/{blog_id}",
        data=blog_payload,
    )
    assert res.status_code == 403
    assert res.json()["detail"] == "권한 없음"

    res = await client.delete(f"/blogs/delete/{blog_id}")
    assert res.status_code == 403
    assert res.json()["detail"] == "권한 없음"
