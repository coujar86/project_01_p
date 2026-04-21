from __future__ import annotations
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from app.db.crud.outbox import OutboxCrud
from app.db.models import Outbox
from app.worker.outbox_for_test import process_once
import pytest


@pytest.mark.asyncio
async def test_process_once_empty_queue(outbox_session_factory, es_client):
    result = await process_once(
        es=es_client,
        session_factory=outbox_session_factory,
        batch_size=2,
    )
    assert result == {"done_ids": [], "failed_ids": []}


@pytest.mark.asyncio
async def test_process_once_upsert_marks_done(
    outbox_session_factory, es_client, es_index, doc_payload
):
    doc = doc_payload
    async with outbox_session_factory() as s:
        async with s.begin():
            ev = await OutboxCrud.create_event(s, "UPSERT", doc["id"], doc)
            eid = ev.id

    result = await process_once(es=es_client, session_factory=outbox_session_factory)
    assert result["failed_ids"] == []
    assert result["done_ids"] == [eid]

    await es_client.indices.refresh(index=es_index)
    got = await es_client.get(index=es_index, id=str(doc["id"]))
    assert got["_source"]["title"] == doc["title"]

    async with outbox_session_factory() as s:
        r = await s.execute(select(Outbox).where(Outbox.id == eid))
        row = r.scalar_one()
    assert row.status == "DONE"
    assert row.processed_at is not None


@pytest.mark.asyncio
async def test_process_once_delete_marks_done(outbox_session_factory, es_client):
    async with outbox_session_factory() as s:
        async with s.begin():
            ev = await OutboxCrud.create_event(
                s, "DELETE", aggregate_id=99, payload=None
            )
            eid = ev.id

    with patch(
        "app.worker.outbox_for_test.delete_es_document", new_callable=AsyncMock
    ) as delete_doc:
        result = await process_once(
            es=es_client, session_factory=outbox_session_factory
        )

    delete_doc.assert_awaited_once_with(es_client, 99)
    assert result == {"done_ids": [eid], "failed_ids": []}

    async with outbox_session_factory() as s:
        r = await s.execute(select(Outbox).where(Outbox.id == eid))
        row = r.scalar_one()
    assert row.status == "DONE"


@pytest.mark.asyncio
async def test_process_once_processing_error_marks_failed(outbox_session_factory):
    es = AsyncMock()

    async with outbox_session_factory() as s:
        async with s.begin():
            ev = await OutboxCrud.create_event(
                s, "UPSERT", 1, None
            )  # 처리 시 ValueError
            eid = ev.id

    result = await process_once(es=es, session_factory=outbox_session_factory)
    assert result == {"done_ids": [], "failed_ids": [eid]}

    async with outbox_session_factory() as s:
        r = await s.execute(select(Outbox).where(Outbox.id == eid))
        row = r.scalar_one()
    assert row.status == "FAILED"
    assert row.retry_count == 1


@pytest.mark.asyncio
async def test_process_once_mixed_done_and_failed(outbox_session_factory):
    es = AsyncMock()

    async with outbox_session_factory() as s:
        async with s.begin():
            ok_ev = await OutboxCrud.create_event(
                s, "UPSERT", 1, {"id": 1, "title": "ok"}
            )
            bad_ev = await OutboxCrud.create_event(s, "UPSERT", 2, None)
            ok_id, bad_id = ok_ev.id, bad_ev.id

    with patch("app.worker.outbox_for_test.upsert_es_document", new_callable=AsyncMock):
        result = await process_once(
            es=es, session_factory=outbox_session_factory, batch_size=10
        )

    assert set(result["done_ids"]) == {ok_id}
    assert set(result["failed_ids"]) == {bad_id}

    async with outbox_session_factory() as s:
        r = await s.execute(select(Outbox).where(Outbox.id.in_((ok_id, bad_id))))
        rows = {row.id: row for row in r.scalars().all()}
    assert rows[ok_id].status == "DONE"
    assert rows[bad_id].status == "FAILED"


@pytest.mark.asyncio
async def test_process_once_respects_batch_size(outbox_session_factory):
    es = AsyncMock()

    async with outbox_session_factory() as s:
        async with s.begin():
            ids = []
            for i in range(4):
                ev = await OutboxCrud.create_event(
                    s, "UPSERT", i, {"id": i, "title": str(i)}
                )
                ids.append(ev.id)

    with patch("app.worker.outbox_for_test.upsert_es_document", new_callable=AsyncMock):
        result = await process_once(
            es=es, session_factory=outbox_session_factory, batch_size=2
        )

    assert len(result["done_ids"]) == 2
    assert result["failed_ids"] == []

    async with outbox_session_factory() as s:
        r = await s.execute(
            select(Outbox).where(Outbox.id.in_(ids)).order_by(Outbox.id)
        )
        rows = list(r.scalars().all())

    done = [row for row in rows if row.status == "DONE"]
    pending = [row for row in rows if row.status == "PENDING"]
    assert len(done) == 2
    assert len(pending) == 2


# python -m pytest tests/outbox/test_outbox.py -v
# pytest tests/outbox/test_outbox.py
