from typing import Sequence, AsyncIterator
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Blog
from app.db.schemas import BlogCreate, BlogUpdate


class BlogCrud:
    @staticmethod
    async def get_blogs_stream(
        db: AsyncSession, start_id: int = 0, chunk_size: int = 100
    ) -> AsyncIterator[Blog]:
        current_id = start_id
        while True:
            result = await db.execute(
                select(Blog)
                .options(selectinload(Blog.author))
                .where(Blog.id > current_id)
                .order_by(Blog.id.asc())
                .limit(chunk_size)
            )
            blogs = result.scalars().all()
            if not blogs:
                break

            for blog in blogs:
                yield blog
            current_id = blogs[-1].id

    @staticmethod
    async def count_all(db: AsyncSession) -> int:
        result = await db.execute(select(func.count(Blog.id)))
        return int(result.scalar_one())

    @staticmethod
    async def get_page(db: AsyncSession, page: int, per_page: int) -> Sequence[Blog]:
        offset = (page - 1) * per_page
        result = await db.execute(
            select(Blog)
            .options(selectinload(Blog.author))
            .order_by(Blog.modified_dt.desc())
            .offset(offset)
            .limit(per_page)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_id(db: AsyncSession, id: int) -> Blog | None:
        result = await db.execute(
            select(Blog).where(Blog.id == id).options(selectinload(Blog.author))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, blog_data: BlogCreate) -> Blog:
        blog = Blog(**blog_data.model_dump())
        db.add(blog)
        await db.flush()
        await db.refresh(blog)
        return blog

    @staticmethod
    async def update(
        db: AsyncSession,
        blog_data: BlogUpdate,
    ) -> Blog | None:
        blog = await db.get(Blog, blog_data.id)
        if blog:
            update_data = blog_data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(blog, key, value)
            await db.flush()
        return blog

    @staticmethod
    async def delete(db: AsyncSession, blog: Blog) -> Blog | None:
        await db.delete(blog)
        await db.flush()
        return blog
