"""Outbox CRUD 및 워커 이벤트 처리 초안 테스트."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.crud.outbox import OutboxCrud
from app.db.models import Outbox
from app.worker.outbox_processor import _event_processing


@pytest.mark.asyncio
async def test_create_event_persists_pending(db_session):
    async with db_session.begin():
        ev = await OutboxCrud.create_event(
            db_session,
            "UPSERT",
            aggregate_id=42,
            payload={"id": 42, "title": "t"},
        )
        event_id = ev.id

    result = await db_session.execute(select(Outbox).where(Outbox.id == event_id))
    row = result.scalar_one()
    assert row.status == "PENDING"
    assert row.event_type == "UPSERT"
    assert row.aggregate_id == 42
    assert row.payload["title"] == "t"


@pytest.mark.asyncio
async def test_claim_events_sets_processing_and_returns_payload(db_session):
    async with db_session.begin():
        await OutboxCrud.create_event(
            db_session,
            "DELETE",
            aggregate_id=7,
            payload=None,
        )

    async with db_session.begin():
        claimed = await OutboxCrud.claim_events(db_session, batch_size=10)

    assert len(claimed) == 1
    _id, event_type, aggregate_id, payload = claimed[0]
    assert event_type == "DELETE"
    assert aggregate_id == 7
    assert payload is None

    result = await db_session.execute(select(Outbox).where(Outbox.id == _id))
    row = result.scalar_one()
    assert row.status == "PROCESSING"
    assert row.locked_at is not None


@pytest.mark.asyncio
async def test_mark_done_event(db_session):
    async with db_session.begin():
        ev = await OutboxCrud.create_event(
            db_session, "UPSERT", 1, {"id": 1, "title": "x"}
        )
        eid = ev.id

    async with db_session.begin():
        claimed = await OutboxCrud.claim_events(db_session, batch_size=10)
        ids = [c[0] for c in claimed]

    async with db_session.begin():
        n = await OutboxCrud.mark_done_event(db_session, ids)
    assert n == 1

    result = await db_session.execute(select(Outbox).where(Outbox.id == eid))
    row = result.scalar_one()
    assert row.status == "DONE"
    assert row.locked_at is None
    assert row.processed_at is not None


@pytest.mark.asyncio
async def test_mark_failed_event_increments_retry(db_session):
    async with db_session.begin():
        ev = await OutboxCrud.create_event(db_session, "UPSERT", 1, {"id": 1})
        eid = ev.id

    async with db_session.begin():
        await OutboxCrud.claim_events(db_session, batch_size=10)

    async with db_session.begin():
        n = await OutboxCrud.mark_failed_event(db_session, [eid])
    assert n == 1

    result = await db_session.execute(select(Outbox).where(Outbox.id == eid))
    row = result.scalar_one()
    assert row.status == "FAILED"
    assert row.retry_count == 1
    assert row.next_retry_at is not None


@pytest.mark.asyncio
async def test_event_processing_upsert_calls_index():
    es = AsyncMock()
    payload = {"id": 99, "title": "hello"}

    with patch(
        "app.worker.outbox_processor.upsert_es_document",
        new_callable=AsyncMock,
    ) as upsert:
        await _event_processing(es, "UPSERT", 99, payload)
        upsert.assert_awaited_once_with(es, payload)


@pytest.mark.asyncio
async def test_event_processing_delete_calls_delete():
    es = AsyncMock()

    with patch(
        "app.worker.outbox_processor.delete_es_document",
        new_callable=AsyncMock,
    ) as delete_doc:
        await _event_processing(es, "DELETE", 5, None)
        delete_doc.assert_awaited_once_with(es, 5)


@pytest.mark.asyncio
async def test_event_processing_upsert_requires_payload():
    es = AsyncMock()
    with pytest.raises(ValueError, match="UPSERT requires"):
        await _event_processing(es, "UPSERT", 1, None)


@pytest.mark.asyncio
async def test_event_processing_unknown_type():
    es = AsyncMock()
    with pytest.raises(ValueError, match="Unknown event_type"):
        await _event_processing(es, "UNKNOWN", 1, {})


@pytest.mark.asyncio
async def test_single_iteration_pipeline_writes_to_es(
    test_engine,
    create_tables,
    es_client,
    es_index,
):
    """워커 한 사이클(claim → ES 반영 → mark_done)을 테스트 DB·ES로 재현."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    Session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    doc = {
        "id": 1001,
        "title": "outbox pipeline",
        "content": "본문",
        "image_loc": "/x",
        "modified_dt": "2026-01-01T00:00:00",
        "author": {"id": 1, "name": "a", "email": "a@example.com"},
    }

    async with Session() as s:
        async with s.begin():
            await OutboxCrud.create_event(s, "UPSERT", doc["id"], doc)

    async with Session() as s:
        async with s.begin():
            claimed = await OutboxCrud.claim_events(s, batch_size=5)
    assert len(claimed) == 1

    _id, event_type, aggregate_id, payload = claimed[0]
    await _event_processing(es_client, event_type, aggregate_id, payload)
    await es_client.indices.refresh(index=es_index)

    got = await es_client.get(index=es_index, id=str(doc["id"]))
    assert got["_source"]["title"] == doc["title"]

    async with Session() as s:
        async with s.begin():
            await OutboxCrud.mark_done_event(s, [_id])

    async with Session() as s2:
        r2 = await s2.execute(select(Outbox).where(Outbox.id == _id))
        row = r2.scalar_one()
    assert row.status == "DONE"


@pytest.mark.asyncio
async def test_processing_loop_marks_done_after_success(
    test_engine,
    create_tables,
    monkeypatch,
):
    """AsyncSessionLocal을 테스트 엔진으로 치환해 _processing_loop 한 바퀴 검증."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    import app.worker.outbox_processor as op

    Session = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    monkeypatch.setattr(op, "AsyncSessionLocal", Session)
    monkeypatch.setattr(op, "SLEEP_SECONDS", 0.01)
    monkeypatch.setattr(op, "BATCH_SIZE", 5)

    es = AsyncMock()

    async with Session() as s:
        async with s.begin():
            ev = await OutboxCrud.create_event(
                s, "UPSERT", 2002, {"id": 2002, "title": "loop"}
            )
            eid = ev.id

    stop = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.15)
        stop.set()

    with patch.object(op, "upsert_es_document", new_callable=AsyncMock):
        await asyncio.gather(
            op._processing_loop(es, stop),
            stop_soon(),
        )

    async with Session() as s:
        r = await s.execute(select(Outbox).where(Outbox.id == eid))
        row = r.scalar_one()
    assert row.status == "DONE"
