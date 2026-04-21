from sqlalchemy import UniqueConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.models import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(100), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (UniqueConstraint("email", name="uk_users_email"),)

    blogs = relationship("Blog", back_populates="author", lazy="selectin")
