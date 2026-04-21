from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User
from app.db.schemas.auth import UserCreate


class UserCrud:
    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, db_user: UserCreate) -> User:
        db_user = User(**db_user.model_dump())
        db.add(db_user)
        await db.flush()
        return db_user
