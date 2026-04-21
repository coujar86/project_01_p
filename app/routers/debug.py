from redis.asyncio import Redis
from fastapi import Request, APIRouter, Depends
from elasticsearch import AsyncElasticsearch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.database import get_db, get_redis
from app.db.models import User, Blog
from app.db.crud import OutboxCrud
from app.core.client import check_es_health, get_es
from app.search import sync_blogs_mysql_to_es, BLOG_ALIAS
from app.search.blog_sync import convert_blog_to_document
from app.utils.test import create_dummies


logger = get_logger(__name__)
router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/redis")
async def test_redis(redis: Redis = Depends(get_redis)):
    await redis.set("test_key", "test_value", ex=10)
    val = await redis.get("test_key")
    return {"ok": val}


@router.get("/db")
async def ping_db(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    one = result.scalar_one()
    return {"ok": True, "ping": one}


@router.get("/nplus1")
async def debug_nplus1(db: AsyncSession = Depends(get_db)):
    blogs = (await db.scalars(select(Blog).limit(20))).all()

    result = []
    for b in blogs:
        result.append(
            {
                "blog_id": b.id,
                "author_email": b.author.email,
            }
        )
    return {"count": len(result)}


@router.get("/multi")
async def debug_multi_query(db: AsyncSession = Depends(get_db)):
    await db.execute(select(User).limit(1))
    await db.execute(select(User).limit(1))
    await db.execute(select(User).limit(1))
    return {"queries": "OK"}


@router.get("/es_hb")
async def debug_es_heartbead(es: AsyncElasticsearch = Depends(get_es)):
    settings = get_settings()
    es_healthy = await check_es_health(es)
    if es_healthy:
        return {
            "status": "es healthy",
            "es_idx": settings.elasticsearch_index_blogs,
        }
    return {"status": "es failed"}


@router.get("/es_sync")
async def debug_es_sync(
    db: AsyncSession = Depends(get_db), es: AsyncElasticsearch = Depends(get_es)
):
    success_count = await sync_blogs_mysql_to_es(db, es=es, index_name=BLOG_ALIAS)

    return {
        "status": "success",
        "message": f"Successfully synced {success_count} blogs to Elasticsearch",
        "index": BLOG_ALIAS,
    }


@router.get("/dummy")
async def dummy(db: AsyncSession = Depends(get_db)):
    n = 1000
    blog_ids = await create_dummies(db, n)
    if blog_ids:
        result = await db.execute(
            select(Blog).where(Blog.id.in_(blog_ids)).options(joinedload(Blog.author))
        )
        blogs_with_author = list(result.unique().scalars().all())
        for blog in blogs_with_author:
            payload = convert_blog_to_document(blog)
            await OutboxCrud.create_event(db, "UPSERT", blog.id, payload)
    await db.commit()
    return {"inserted": n}
