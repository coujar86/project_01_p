from datetime import datetime
from sqlalchemy import (
    BigInteger,
    SmallInteger,
    String,
    TIMESTAMP,
    JSON,
    Index,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.db.models import Base


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(40), server_default=text("'PENDING'"), nullable=False
    )

    retry_count: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("0"), nullable=False
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_status_retry_id", "status", "next_retry_at", "id"),
        Index("idx_processed_at", "processed_at"),
    )
