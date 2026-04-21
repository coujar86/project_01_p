from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import ClassVar, Literal
import os


_CURRENT_FILE = Path(__file__).resolve()
_APP_DIR = _CURRENT_FILE.parent.parent
_ROOT_DIR = _APP_DIR.parent

_env = os.getenv("ENV_FILE")
_ENV_FILE = Path(_env) if _env else (_ROOT_DIR / ".env.local")
# _ENV_FILE = Path(_env) if _env else (_ROOT_DIR / ".env.test")

if not _ENV_FILE.exists():
    raise RuntimeError(f"Env file not found: {_ENV_FILE}")


class Settings(BaseSettings):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        "INFO", alias="LOG_LEVEL"
    )
    upload_dir: str = Field(..., alias="UPLOAD_DIR")
    secret_key: str = Field(..., alias="SECRET_KEY")

    max_query_count: int = Field(1, alias="MAX_QUERY_COUNT")
    session_ttl: int = Field(3600, alias="SESSION_TTL")

    db_user: str = Field(..., alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")
    db_host: str = Field("localhost", alias="DB_HOST")
    db_port: int = Field(3306, alias="DB_PORT")
    db_name: str = Field(..., alias="DB_NAME")

    redis_host: str = Field("localhost", alias="REDIS_HOST")
    redis_port: int = Field(6379, alias="REDIS_PORT")
    redis_db: int = Field(0, alias="REDIS_DB")

    db_slow_query_ms: int = Field(50, alias="DB_SLOW_QUERY_MS")
    db_statement_maxlen: int = Field(10, alias="DB_STATEMENT_MAXLEN")
    db_query_sample_limit: int = Field(100, alias="DB_QUERY_SAMPLE_LIMIT")

    elasticsearch_host: str = Field("localhost", alias="ELASTICSEARCH_HOST")
    elasticsearch_port: int = Field(9200, alias="ELASTICSEARCH_PORT")
    elasticsearch_schema: str = Field("http", alias="ELASTICSEARCH_SCHEMA")

    elasticsearch_index_blogs: str = Field("blogs", alias="ELASTICSEARCH_INDEX_BLOGS")
    elasticsearch_timeout: int = Field(5, alias="ELASTICSEARCH_TIMEOUT")
    elasticsearch_max_retries: int = Field(3, alias="ELASTICSEARCH_MAX_RETRIES")

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    embedding_model: str = Field("text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dims: int = Field(1536, alias="EMBEDDING_DIMS")

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def database_url(self) -> str:
        return f"mysql+aiomysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def elasticsearch_url(self) -> str:
        return f"{self.elasticsearch_schema}://{self.elasticsearch_host}:{self.elasticsearch_port}"

    @property
    def upload_dir_path(self) -> Path:
        p = Path(self.upload_dir)
        if not p.is_absolute():
            p = self.APP_DIR / p
        return p.resolve()

    BLOGS_PER_PAGE: ClassVar[int] = 10
    MAX_PAGE_SEARCH: ClassVar[int] = 3
    MAX_PAGE_AI_SEARCH: ClassVar[int] = 2

    ROOT_DIR: ClassVar[Path] = _ROOT_DIR
    APP_DIR: ClassVar[Path] = _APP_DIR
    TEMPLATES_DIR: ClassVar[Path] = _APP_DIR / "templates"
    STATIC_DIR: ClassVar[Path] = _APP_DIR / "static"

    UPLOAD_CHUNK_SIZE: ClassVar[int] = 1024 * 1024  # 1MB
    UPLOAD_MAX_SIZE: ClassVar[int] = 10 * 1024 * 1024  # 10MB

    UPLOAD_PREFIX: ClassVar[str] = "/static/uploads/"
    ALLOWED_EXT: ClassVar[frozenset[str]] = frozenset({".jpeg", ".jpg", ".png"})
    ALLOWED_EXT_ES: ClassVar[frozenset[str]] = frozenset({"jpeg", "jpg", "png"})

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
