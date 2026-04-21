from elasticsearch import AsyncElasticsearch
from app.db.crud.outbox import OutboxCrud
from app.search import upsert_es_document, delete_es_document
import asyncio
from collections.abc import Callable
from sqlalchemy.ext.asyncio import AsyncSession


BATCH_SIZE = 2


async def _event_processing(
    es: AsyncElasticsearch, event_type: str, aggregate_id: int, payload: dict | None
) -> None:
    if event_type == "UPSERT":
        if not payload:
            raise ValueError("UPSERT requires non-empty payload dict")
        await upsert_es_document(es, payload)
    elif event_type == "DELETE":
        await delete_es_document(es, aggregate_id)
    else:
        raise ValueError(f"Unknown event_type: {event_type}")


async def process_once(
    es: AsyncElasticsearch,
    session_factory: Callable[[], AsyncSession],
    batch_size: int = BATCH_SIZE,
) -> dict[str, list[int]]:
    async with session_factory() as session:
        async with session.begin():
            claimed = await OutboxCrud.claim_events(session, batch_size=batch_size)

    if not claimed:
        return {"done_ids": [], "failed_ids": []}

    done_ids = []
    failed_ids = []

    for id_, event_type, aggregate_id, payload in claimed:
        try:
            await _event_processing(es, event_type, aggregate_id, payload)
            done_ids.append(id_)
        except Exception:
            failed_ids.append(id_)

    async with session_factory() as session:
        async with session.begin():
            if done_ids:
                await OutboxCrud.mark_done_event(session, done_ids)
            if failed_ids:
                await OutboxCrud.mark_failed_event(session, failed_ids)

    return {"done_ids": done_ids, "failed_ids": failed_ids}


def make_test_stop() -> asyncio.Event:
    return asyncio.Event()
