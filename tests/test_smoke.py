import pytest


@pytest.mark.asyncio
async def test_debug_db(client):
    res = await client.get("/debug/db")

    assert res.status_code == 200
    assert res.json() == {"ok": True, "ping": 1}


@pytest.mark.asyncio
async def test_debug_redis(client):
    res = await client.get("/debug/redis")

    assert res.status_code == 200
    assert res.json() == {"ok": "test_value"}


@pytest.mark.asyncio
async def test_debug_es(client, es_client, es_index):
    res = await client.get("/debug/es_hb")
    assert res.status_code == 200

    body = res.json()
    assert body["status"] == "es healthy"
    assert body["es_idx"] == es_index

    assert await es_client.indices.exists(index=es_index)
