import pytest


@pytest.fixture
def doc_payload_v1():
    return {
        "id": 1,
        "title": "사과",
        "content": "내용 포도",
        "image_loc": "/static/uploads/1/a.png",
        "image_ext": "png",
        "modified_dt": "2026-01-01T00:00:00",
        "author": {"id": 1, "name": "test", "email": "test@example.com"},
    }


@pytest.fixture
def doc_payload_v2():
    return {
        "id": 2,
        "title": "사과바나나체리",
        "content": "내용 초코 바닐라",
        "modified_dt": "2026-01-02T00:00:00",
        "author": {"id": 1, "name": "test", "email": "test@example.com"},
    }


@pytest.fixture
def doc_payload_v3():
    return {
        "id": 3,
        "title": "사과바나나체리",
        "content": "내용 초코 바닐라",
        "modified_dt": "2026-01-02T00:00:00",
        "author": {"id": 2, "name": "other", "email": "other@example.com"},
    }
