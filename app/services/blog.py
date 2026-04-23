from typing import Literal
from langgraph.types import Command
from elasticsearch import AsyncElasticsearch
from fastapi import UploadFile, HTTPException

# from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.logging import get_logger
from app.core.config import get_settings
from app.db.crud import BlogCrud, OutboxCrud
from app.db.models import Blog
from app.db.schemas import BlogCreate, BlogUpdate, BlogRead
from app.search.ai.nlq_core import BlogNLQContext
from app.search.ai.nlq_graph import get_blog_nlq_graph
from app.search.blog_queries import BlogSearchFilters, ImageExt
from app.search import search_blogs_es, convert_blog_to_document
from app.utils import util
import aiofiles.os as aios
import aiofiles
import uuid
import os

logger = get_logger(__name__)
settings = get_settings()


# class AISearchResult(BaseModel):
#     search_results: list = Field(default_factory=list)
#     total_pages: int
#     current_page: int
#     review_required: bool
#     review_payload: dict | None = None
#     thread_id: str | None = None


class BlogService:
    @staticmethod
    async def get_pagination(
        db: AsyncSession, *, page: int, per_page: int
    ) -> tuple[int, int]:
        """전체 글 개수 기준으로 total_pages, current_page 계산"""
        total = await BlogCrud.count_all(db)
        total_pages, current_page = util.calc_pagination(
            total=total, page=page, per_page=per_page
        )
        return total_pages, current_page

    @staticmethod
    async def get_all_blogs(
        db: AsyncSession, *, page: int, per_page: int
    ) -> list[BlogRead]:
        """목록 페이지 조회"""
        blogs = await BlogCrud.get_page(db, page, per_page)
        return [BlogService._build_blog_read(blog, is_preview=True) for blog in blogs]

    @staticmethod
    async def get_blog_by_id(db: AsyncSession, *, id: int) -> BlogRead:
        """단일 페이지 글 조회"""
        blog = await BlogCrud.get_by_id(db, id)
        if blog is None:
            raise HTTPException(detail="블로그 글 없음", status_code=404)

        return BlogService._build_blog_read(blog, is_preview=False)

    @staticmethod
    async def search_blogs(
        es: AsyncElasticsearch,
        *,
        q: str,
        search_type: str,
        image_ext: ImageExt | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int,
    ) -> tuple[list, int, int]:
        if not 1 <= page <= settings.MAX_PAGE_SEARCH:
            raise HTTPException(detail="페이지 범위 오류", status_code=400)
        try:
            df = util.parse_query_date_start(date_from)
            dt = util.parse_query_date_end(date_to)

            if df and dt and df > dt:
                raise ValueError("df > dt")

            filters = BlogSearchFilters(image_ext=image_ext, date_from=df, date_to=dt)
            return await search_blogs_es(
                es, q=q, search_type=search_type, page=page, filters=filters
            )
        except ValueError:
            raise HTTPException(detail="입력 형식 오류", status_code=400)

    @staticmethod
    async def ai_search_blogs(
        es: AsyncElasticsearch,
        *,
        nlq: str,
        page: int,
        thread_id: str,
    ) -> dict:
        if not 1 <= page <= settings.MAX_PAGE_AI_SEARCH:
            raise HTTPException(detail="페이지 범위 오류", status_code=400)

        graph = get_blog_nlq_graph()
        config = {"configurable": {"thread_id": thread_id}}

        result = await graph.ainvoke(
            {"nlq": nlq, "page": page},
            config=config,
            context=BlogNLQContext(es=es),
        )

        interrupts = result.get("__interrupt__", [])
        if interrupts:
            interrupt_ = interrupts[0]
            review_payload = (
                interrupt_.value if hasattr(interrupt_, "value") else interrupt_
            )
            return {
                "search_results": [],
                "total_pages": 0,
                "current_page": page,
                "review_required": True,
                "review_payload": review_payload,
                "thread_id": thread_id,
            }

        error = result.get("error")
        if error:
            raise HTTPException(detail=error, status_code=400)

        return {
            "search_results": result.get("search_results", []),
            "total_pages": result.get("total_pages", 0),
            "current_page": result.get("current_page", page),
            "review_required": False,
            "review_payload": None,
            "thread_id": thread_id,
        }

    @staticmethod
    async def resume_ai_search_blogs(
        es: AsyncElasticsearch,
        *,
        human_decision: Literal["approve", "reject"],
        thread_id: str,
        page: int,
    ) -> dict:
        if not 1 <= page <= settings.MAX_PAGE_AI_SEARCH:
            raise HTTPException(detail="페이지 범위 오류", status_code=400)

        graph = get_blog_nlq_graph()
        config = {"configurable": {"thread_id": thread_id}}

        result = await graph.ainvoke(
            Command(resume=human_decision),
            config=config,
            context=BlogNLQContext(es=es),
        )

        interrupts = result.get("__interrupt__", [])
        if interrupts:
            interrupt_ = interrupts[0]
            review_payload = (
                interrupt_.value if hasattr(interrupt_, "value") else interrupt_
            )
            return {
                "search_results": [],
                "total_pages": 0,
                "current_page": page,
                "review_required": True,
                "review_payload": review_payload,
                "thread_id": thread_id,
            }

        error = result.get("error")
        if error:
            raise HTTPException(detail=error, status_code=400)

        return {
            "search_results": result.get("search_results", []),
            "total_pages": result.get("total_pages", 0),
            "current_page": result.get("current_page", page),
            "review_required": False,
            "review_payload": None,
            "thread_id": thread_id,
        }

    @staticmethod
    async def upload_file(
        author_id: int, imagefile: UploadFile | None = None
    ) -> str | None:
        """파일이 없거나 파일명이 비어 있으면 None, 아니면 업로드 후 경로 반환"""
        if not imagefile or not (imagefile.filename or "").strip():
            return None
        original = (imagefile.filename or "").strip()
        upload_image_loc = None
        is_large = False

        try:
            _, ext = os.path.splitext(original)
            ext = ext.lower()
            if ext not in settings.ALLOWED_EXT:
                raise HTTPException(detail="파일 형식 오류", status_code=400)

            user_dir = settings.upload_dir_path / str(author_id)
            await aios.makedirs(user_dir, exist_ok=True)

            upload_filename = f"{uuid.uuid4().hex}{ext}"
            upload_image_loc = user_dir / upload_filename

            async with aiofiles.open(upload_image_loc, "wb") as outfile:
                total_size = 0
                max_size = settings.UPLOAD_MAX_SIZE
                while True:
                    chunk = await imagefile.read(settings.UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break

                    total_size += len(chunk)
                    if total_size > max_size:
                        is_large = True
                        raise HTTPException(detail="파일 크기 초과", status_code=400)

                    await outfile.write(chunk)

            ret_image_loc = f"{settings.UPLOAD_PREFIX}{author_id}/{upload_filename}"
            return ret_image_loc

        except Exception as e:
            logger.critical(f"Unexpected upload error: {str(e)}")
            raise HTTPException(detail="알 수 없는 오류", status_code=500)
        finally:
            if is_large and upload_image_loc:
                await aios.remove(upload_image_loc)

    @staticmethod
    async def create_blog(
        db: AsyncSession,
        blog_data: BlogCreate,
    ) -> None:
        try:
            blog = await BlogCrud.create(db, blog_data)
            blog_with_author = await BlogCrud.get_by_id(db, blog.id)
            payload = convert_blog_to_document(blog_with_author)
            await OutboxCrud.create_event(db, "UPSERT", blog.id, payload)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def update_blog(
        db: AsyncSession,
        *,
        user_id: int,
        image_loc_old: str | None = None,
        blog_data: BlogUpdate,
    ) -> None:
        BlogService._check_blog_owner(user_id=user_id, author_id=blog_data.author_id)
        try:
            blog = await BlogCrud.update(db, blog_data)

            blog_with_author = await BlogCrud.get_by_id(db, blog.id)
            payload = convert_blog_to_document(blog_with_author)

            await OutboxCrud.create_event(db, "UPSERT", blog.id, payload)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        if image_loc_old and image_loc_old != blog_data.image_loc:
            await BlogService._delete_uploaded_image(image_loc_old)

    @staticmethod
    async def _delete_uploaded_image(image_loc: str | None) -> None:
        if (
            image_loc
            and isinstance(image_loc, str)
            and image_loc.startswith(settings.UPLOAD_PREFIX)
        ):
            rel = image_loc.removeprefix(settings.UPLOAD_PREFIX)
            file_path = settings.upload_dir_path / rel
            upload_root = settings.upload_dir_path.resolve()
            if upload_root not in file_path.parents and file_path != upload_root:
                return
            try:
                if await aios.path.exists(file_path):
                    await aios.remove(file_path)
            except OSError as e:
                pass

    @staticmethod
    async def delete_blog(db: AsyncSession, *, user_id: int, id: int) -> None:
        blog = await BlogCrud.get_by_id(db, id)
        if blog is None:
            raise HTTPException(detail="블로그 글 없음", status_code=404)

        BlogService._check_blog_owner(user_id=user_id, author_id=blog.author_id)
        image_loc = blog.image_loc
        try:
            blog = await BlogCrud.delete(db, blog)
            await OutboxCrud.create_event(db, "DELETE", id, None)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        await BlogService._delete_uploaded_image(image_loc)

    @staticmethod
    def _check_blog_owner(user_id: int, author_id: int) -> None:
        """사용자의 id가 블로그 글 작성자 id와 동일한지 확인"""
        if user_id != author_id:
            raise HTTPException(detail="권한 없음", status_code=403)

    @staticmethod
    def _build_blog_read(blog: Blog, is_preview: bool) -> BlogRead:
        """목록 페이지일 경우 content 글자수를 생략하여 표시, 단일 페이지일 경우 content를 그대로 표시"""
        if is_preview:
            content = util.truncate_text(blog.content)
        else:
            content = blog.content

        return BlogRead(
            id=blog.id,
            title=blog.title,
            author_id=blog.author_id,
            author=blog.author.name,
            email=blog.author.email,
            content=util.newline_to_br(content),
            image_loc=util.resolve_image_loc(blog.image_loc),
            modified_dt=blog.modified_dt,
        )
