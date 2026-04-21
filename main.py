from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core import lifespan, exc_handler
from app.core.middlewares import RequestIdMiddleware, MethodOverrideMiddleware
from app.core.logging import setup_logging
from app.core.config import get_settings
from app.routers import blog, auth, debug


setup_logging()
settings = get_settings()

app = FastAPI(lifespan=lifespan.lifespan)
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")

app.include_router(blog.router)
app.include_router(auth.router)
app.include_router(debug.router)

app.add_middleware(MethodOverrideMiddleware)
app.add_middleware(RequestIdMiddleware)

app.add_exception_handler(StarletteHTTPException, exc_handler.http_exception_handler)
app.add_exception_handler(SQLAlchemyError, exc_handler.sqlalchemy_exception_handler)
app.add_exception_handler(
    RequestValidationError, exc_handler.validation_exception_handler
)
