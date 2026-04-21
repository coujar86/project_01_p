from datetime import datetime
from sqlalchemy import ForeignKey, Index, TIMESTAMP, BigInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.models import Base


class Blog(Base):
    __tablename__ = "blogs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", name="fk_blogs_author_id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    image_loc: Mapped[str | None] = mapped_column(String(400), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    author = relationship("User", back_populates="blogs", lazy="selectin")

    __table_args__ = (
        Index("idx_author_id", "author_id"),
        Index("idx_modified_id", "modified_dt", "id"),
    )
