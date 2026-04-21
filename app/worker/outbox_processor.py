from elasticsearch import AsyncElasticsearch
from app.core.logging import get_logger
from app.core.client import create_es_client
from app.db.crud.outbox import OutboxCrud
from app.db.database import AsyncSessionLocal
from app.search import (
    embedding_text,
    upsert_es_document,
    delete_es_document,
)
import asyncio
import signal
import time


SLEEP_SECONDS = 5
BATCH_SIZE = 10
RESET_SECONDS = 15
CLEANUP_SECONDS = 30

logger = get_logger(__name__)


async def _event_processing(
    es: AsyncElasticsearch, event_type: str, aggregate_id: int, payload: dict | None
) -> None:
    if event_type == "UPSERT":
        if not payload:
            raise ValueError("UPSERT requires non-empty payload dict")
        text = f"title: {payload['title']}\ncontent: {payload['content']}"
        embedding_vector = await embedding_text(text)
        await upsert_es_document(es, {**payload, "embedding": embedding_vector})
    elif event_type == "DELETE":
        await delete_es_document(es, aggregate_id)
    else:
        raise ValueError(f"Unknown event_type: {event_type}")


async def _processing_loop(es: AsyncElasticsearch, stop_: asyncio.Event):
    while not stop_.is_set():
        async with AsyncSessionLocal() as session:
            async with session.begin():
                claimed = await OutboxCrud.claim_events(session, batch_size=BATCH_SIZE)

        if not claimed:
            try:
                await asyncio.wait_for(stop_.wait(), timeout=SLEEP_SECONDS)
            except TimeoutError:
                pass
            continue

        done_ids = []
        failed_ids = []

        for id_, event_type, aggregate_id, payload in claimed:
            try:
                await _event_processing(es, event_type, aggregate_id, payload)
                done_ids.append(id_)
            except Exception as e:
                logger.exception(
                    f"[FAILED EVENT] id={id_}, type={event_type}, aggregate_id={aggregate_id}"
                )
                failed_ids.append(id_)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                if done_ids:
                    logger.error(f"[MARK DONE] ids={done_ids}")
                    await OutboxCrud.mark_done_event(session, done_ids)
                if failed_ids:
                    logger.error(f"[MARK FAILED] ids={failed_ids}")
                    await OutboxCrud.mark_failed_event(session, failed_ids)


async def _house_keeping_loop(stop_: asyncio.Event):
    last_reset = time.monotonic()
    last_cleanup = last_reset
    while not stop_.is_set():
        try:
            if time.monotonic() - last_reset >= RESET_SECONDS:
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        reset_num = await OutboxCrud.reset_blocked_event(session)
                last_reset = time.monotonic()
            if time.monotonic() - last_cleanup >= CLEANUP_SECONDS:
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        clean_done_num = await OutboxCrud.clean_done_event(session)
                        clean_failed_num = await OutboxCrud.clean_failed_event(session)
                        if clean_failed_num:
                            logger.error(f"[CLEAN FAILED] removed={clean_failed_num}")
                last_cleanup = time.monotonic()
            try:
                await asyncio.wait_for(stop_.wait(), timeout=SLEEP_SECONDS)
            except TimeoutError:
                pass
        except Exception as e:
            logger.error(f"[HOUSEKEEPING ERROR] error={e}", exc_info=False)


def _make_stop() -> asyncio.Event:
    stop_ = asyncio.Event()

    def _set_stop(*_):
        stop_.set()

    try:
        signal.signal(signal.SIGINT, _set_stop)
        signal.signal(signal.SIGTERM, _set_stop)
    except (ValueError, OSError):
        pass

    return stop_


async def main():
    stop_event = _make_stop()
    es = create_es_client()
    try:
        await asyncio.gather(
            _processing_loop(es, stop_event),
            _house_keeping_loop(stop_event),
        )
    finally:
        await es.close()


if __name__ == "__main__":
    logger.warning("=== loop start ===")
    asyncio.run(main())

# python -m app.worker.outbox_processor
# uvicorn main:app --port=8080 --reload
