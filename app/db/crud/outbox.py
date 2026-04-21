from sqlalchemy import select, update, delete, literal_column, or_, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Outbox


class OutboxCrud:
    @staticmethod
    async def create_event(
        db: AsyncSession,
        event_type: str,
        aggregate_id: int,
        payload: dict | None = None,
    ) -> Outbox:
        """새로운 이벤트 생성"""
        outbox_event = Outbox(
            event_type=event_type, aggregate_id=aggregate_id, payload=payload
        )
        db.add(outbox_event)
        await db.flush()
        return outbox_event

    @staticmethod
    async def claim_events(
        db: AsyncSession, batch_size: int = 10
    ) -> list[tuple[int, str, int, dict | None]]:
        """batch_size 이하의 이벤트 선점 및 이벤트 id 리스트 반환"""
        result = await db.execute(
            select(Outbox)
            .where(
                Outbox.locked_at.is_(None),
                or_(
                    Outbox.status == "PENDING",
                    and_(
                        Outbox.status == "FAILED",
                        or_(
                            Outbox.next_retry_at.is_(None),
                            Outbox.next_retry_at <= func.now(),
                        ),
                    ),
                ),
            )
            .order_by(Outbox.id.asc())
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )

        events = result.scalars().all()
        if not events:
            return []

        claimed = [(e.id, e.event_type, e.aggregate_id, e.payload) for e in events]
        event_ids = [e.id for e in events]
        await db.execute(
            update(Outbox)
            .where(Outbox.id.in_(event_ids))
            .values(status="PROCESSING", locked_at=func.now(), next_retry_at=None)
        )
        await db.flush()
        return claimed

    @staticmethod
    async def mark_done_event(db: AsyncSession, event_ids: list[int]) -> int:
        """이벤트를 완료하면 status를 DONE으로 설정"""
        if not event_ids:
            return 0

        result = await db.execute(
            update(Outbox)
            .where(Outbox.id.in_(event_ids), Outbox.status == "PROCESSING")
            .values(
                status="DONE",
                locked_at=None,
                next_retry_at=None,
                processed_at=func.now(),
            )
        )
        await db.flush()
        return result.rowcount

    @staticmethod
    async def mark_failed_event(
        db: AsyncSession, event_ids: list[int], base: int = 1, max_delay: int = 60
    ) -> int:
        """이벤트를 실패하면 status를 FAILED으로 설정하고 재시도 기준 설정"""
        if not event_ids:
            return 0

        delay_minutes = func.least(base * func.pow(2, Outbox.retry_count), max_delay)
        result = await db.execute(
            update(Outbox)
            .where(Outbox.id.in_(event_ids), Outbox.status == "PROCESSING")
            .values(
                status="FAILED",
                locked_at=None,
                retry_count=Outbox.retry_count + 1,
                next_retry_at=func.timestampadd(
                    literal_column("MINUTE"), delay_minutes, func.now()
                ),
            )
        )
        await db.flush()
        return result.rowcount

    @staticmethod
    async def reset_blocked_event(db: AsyncSession, stale_minutes: int = 5) -> int:
        """status가 PROCESSING이고 locked_at이 stale_minutes 이상인 이벤트 회수"""
        result = await db.execute(
            update(Outbox)
            .where(
                Outbox.status == "PROCESSING",
                Outbox.locked_at.isnot(None),
                Outbox.locked_at
                < func.timestampadd(
                    literal_column("MINUTE"), -stale_minutes, func.now()
                ),
            )
            .values(
                status="FAILED",
                locked_at=None,
                retry_count=Outbox.retry_count + 1,
                next_retry_at=func.now(),
            )
        )
        await db.flush()
        return result.rowcount

    @staticmethod
    async def clean_done_event(db: AsyncSession, stale_minutes: int = 60) -> int:
        """status가 DONE이고 processed_at이 stale_minutes 이상인 이벤트 제거"""
        result = await db.execute(
            delete(Outbox).where(
                Outbox.status == "DONE",
                Outbox.processed_at.isnot(None),
                Outbox.processed_at
                < func.timestampadd(
                    literal_column("MINUTE"), -stale_minutes, func.now()
                ),
            )
        )
        await db.flush()
        return result.rowcount

    @staticmethod
    async def clean_failed_event(db: AsyncSession, max_retry: int = 5) -> int:
        """status가 FAILED이고 retry_count가 max_retry 이상인 이벤트 제거"""
        result = await db.execute(
            delete(Outbox).where(
                Outbox.status == "FAILED", Outbox.retry_count >= max_retry
            )
        )
        await db.flush()
        return result.rowcount
