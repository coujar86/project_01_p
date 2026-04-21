from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import User, Blog
from app.core.logging import get_logger
from faker import Faker


logger = get_logger(__name__)
fake = Faker("ko_KR")


async def create_dummies(db: AsyncSession, n: int = 1000) -> list[int]:
    """더미 블로그 n개 생성 후 생성된 블로그 id 목록 반환"""
    user = await db.scalar(select(User).limit(1))
    if user is None:
        user = User(
            name="seed_user",
            email="seed_user@gmail.com",
            password_hash="xxx",
        )
        db.add(user)
        await db.flush()

    blogs = []
    for _ in range(n):
        title = fake.sentence(nb_words=6)
        content = "\n".join(fake.paragraphs(nb=3))

        blogs.append(
            Blog(
                title=title,
                content=content,
                image_loc=None,
                author_id=user.id,
            )
        )
    db.add_all(blogs)
    await db.flush()

    ids = [b.id for b in blogs]
    logger.info(f"Created dummies: {len(ids)} items")
    return ids
