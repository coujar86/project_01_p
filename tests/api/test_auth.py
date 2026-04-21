from __future__ import annotations
import pytest


@pytest.mark.asyncio
async def test_signup_failed(client, user_payload):
    res = await client.post(
        "/auth/signup",
        data=user_payload,
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers.get("location") in ("/blogs", "http://test/blogs")

    dup = await client.post(
        "/auth/signup", data={**user_payload, "name": "test2"}, follow_redirects=False
    )
    assert dup.status_code == 409
    assert dup.json()["detail"] == "이미 존재하는 이메일"

    res = await client.post(
        "/auth/signup",
        data={**user_payload, "email": "not_email"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client, user_payload):
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

    cookies = res.cookies
    assert "session_id" in cookies

    res = await client.get("/auth/logout", follow_redirects=False)
    assert res.status_code == 303

    cookies = res.cookies
    assert "session_id" not in cookies


@pytest.mark.asyncio
async def test_login_unknown_user_returns_401(client, user_payload):
    res = await client.post(
        "/auth/signup",
        data=user_payload,
        follow_redirects=False,
    )
    assert res.status_code == 303

    res = await client.post(
        "/auth/login",
        data={**user_payload, "email": "not_user@example.com"},
        follow_redirects=False,
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "유저 정보 없음"

    res = await client.post(
        "/auth/login",
        data={**user_payload, "password": "wrong_pw"},
        follow_redirects=False,
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "입력 정보 틀림"
