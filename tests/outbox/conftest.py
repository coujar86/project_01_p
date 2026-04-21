import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def doc_payload():
    return {
        "id": 1,
        "title": "제목 사과",
        "content": "내용 포도",
        "image_loc": "임의의 위치",
        "modified_dt": "2026-01-01T00:00:00",
        "author": {
            "id": 1,
            "name": "test",
            "email": "test@example.com",
        },
    }


@pytest.fixture
def outbox_session_factory(test_engine, create_tables):
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
