from typing import AsyncIterator
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.crud.blog import BlogCrud
from app.core.logging import get_logger
from app.utils.util import extract_image_ext


logger = get_logger(__name__)


async def _blogs_stream_action(
    blogs_stream: AsyncIterator, index_name: str
) -> AsyncIterator[dict]:
    """블로그 스트림을 Elasticsearch bulk 문서 형식으로 변환"""
    success = 0
    failed = 0

    async for blog in blogs_stream:
        if not blog.author:
            failed += 1
            logger.warning(f"Skipping blog {blog.id}: author not found")
            continue

        success += 1
        yield {
            "_op_type": "index",
            "_index": index_name,
            "_id": blog.id,
            "_source": {
                "id": blog.id,
                "title": blog.title,
                "content": blog.content,
                "image_loc": blog.image_loc,
                "image_ext": extract_image_ext(blog.image_loc),
                "modified_dt": blog.modified_dt.isoformat(),
                "author": {
                    "id": blog.author.id,
                    "name": blog.author.name,
                    "email": blog.author.email,
                },
            },
        }

    logger.info(f"Stream processing: {success} processed, {failed} skipped")


async def sync_blogs_mysql_to_es(
    session: AsyncSession, *, es: AsyncElasticsearch, index_name: str
) -> int:
    """MySQL 블로그 데이터 전체를 ES 인덱스로 복사하여 동기화"""
    logger.info(f"Starting sync from MySQL to Elasticsearch index: {index_name}")

    try:
        blogs_stream = BlogCrud.get_blogs_stream(session, start_id=0, chunk_size=100)
        success, errors_data = await async_bulk(
            es, _blogs_stream_action(blogs_stream, index_name), raise_on_error=False
        )

        if errors_data:
            error = len(errors_data)
            logger.warning(
                f"Sync completed with {error} errors out of {success + error} total items"
            )
            if errors_data:
                logger.error(f"First error: {errors_data[0]}")
        else:
            logger.info(f"Sync completed successfully: {success} items indexed")

        return success

    except Exception as e:
        logger.error(f"Sync failed: {str(e)}", exc_info=True)
        raise
