from fastapi import Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from app.core.templates import templates


def _sqlalchemy_error_detail(exc: SQLAlchemyError) -> str:
    parts: list[str] = [str(exc)]
    orig = getattr(exc, "orig", None)
    if orig is not None:
        parts.append(f"원인: {orig}")
    return " | ".join(parts)


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "status_code": exc.status_code,
            "detail": exc.detail,
        },
        status_code=exc.status_code,
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "status_code": 500,
            "detail": _sqlalchemy_error_detail(exc),
        },
        status_code=500,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={
            "status_code": 422,
            "detail": exc.errors(),
        },
        status_code=422,
    )
