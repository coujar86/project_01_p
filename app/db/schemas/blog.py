from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class BlogBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., max_length=4000)
    image_loc: str | None = None
    author_id: int

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value


class BlogCreate(BlogBase):
    pass


class BlogUpdate(BlogBase):
    id: int


class BlogRead(BaseModel):
    id: int
    title: str
    author_id: int
    author: str
    email: str | None = None
    content: str
    modified_dt: datetime
    image_loc: str | None = None
