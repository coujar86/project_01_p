import pytest


@pytest.fixture
def user_payload():
    return {"name": "test", "email": "test@example.com", "password": "qwerty"}


@pytest.fixture
def blog_payload():
    return {
        "title": "test title",
        "content": "test content",
        # "imagefile": None,
    }
