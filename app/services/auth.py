from redis.asyncio import Redis
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext
from app.auth.session_store import delete_session, store_session
from app.auth.dependencies import create_session_id
from app.db.crud.user import UserCrud
from app.db.schemas import UserRead, UserCreate, UserLogin


class AuthService:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    @staticmethod
    def _get_hashed_password(password: str) -> str:
        return AuthService.pwd_context.hash(password)

    @staticmethod
    def _verify_password(plain_password: str, hashed_password: str) -> bool:
        return AuthService.pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    async def signup(db: AsyncSession, user: UserCreate) -> None:
        if await UserCrud.get_by_email(db, user.email):
            raise HTTPException(detail="이미 존재하는 이메일", status_code=409)

        hashed_pw = AuthService.pwd_context.hash(user.password)
        user_info = UserCreate(name=user.name, email=user.email, password=hashed_pw)
        try:
            await UserCrud.create(db, db_user=user_info)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def login(
        db: AsyncSession, redis: Redis, user: UserLogin
    ) -> tuple[UserRead, str]:
        db_user = await UserCrud.get_by_email(db, user.email)

        if not db_user:
            raise HTTPException(detail="유저 정보 없음", status_code=401)

        if not AuthService._verify_password(user.password, db_user.password):
            raise HTTPException(detail="입력 정보 틀림", status_code=401)

        session_id = create_session_id()
        await store_session(redis, session_id, db_user.id)

        return (
            UserRead(id=db_user.id, name=db_user.name, email=db_user.email),
            session_id,
        )

    @staticmethod
    async def logout(redis: Redis, session_id: str | None) -> None:
        if not session_id:
            return
        await delete_session(redis, session_id)
