import pytest


@pytest.mark.asyncio
async def test_es_crud(es_client, es_index, doc_payload_v1):
    doc_id = str(doc_payload_v1["id"])

    # upsert
    await es_client.index(
        index=es_index,
        id=doc_id,
        document=doc_payload_v1,
        refresh=True,
    )

    res = await es_client.get(index=es_index, id=doc_id)
    assert res["_source"]["title"] == doc_payload_v1["title"]
    assert res["_source"]["author"]["name"] == "test"

    # search
    res = await es_client.search(
        index=es_index,
        query={"match": {"title": "사과"}},
    )
    assert res["hits"]["total"]["value"] == 1

    res = await es_client.search(
        index=es_index,
        query={"match": {"title": "레몬"}},
    )
    assert res["hits"]["total"]["value"] == 0

    # delete
    await es_client.delete(index=es_index, id=doc_id, refresh=True)
    assert not await es_client.exists(index=es_index, id=doc_id)


# pytest tests/es/test_es.py
