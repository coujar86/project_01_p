from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logging import get_logger
from app.core.config import get_settings
from app.core.context import (
    enter_request_scope,
    exit_request_scope,
    get_query_count,
    get_query_samples,
)
import uuid

logger = get_logger(__name__)
settings = get_settings()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        rid_token, qc_token, qs_token = enter_request_scope(request_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
        except Exception:
            logger.exception("Request failed:", extra={"request_id": request_id})
            raise
        finally:
            try:
                query_count = get_query_count()
                if query_count >= settings.max_query_count:
                    samples = get_query_samples()
                    top = sorted(samples, key=lambda x: x[0], reverse=True)[:5]
                    top_repr = [
                        {"duration_ms": round(d, 2), "statement": s} for d, s in top
                    ]
                    logger.warning(
                        "possible N+1: too many queries in a single request",
                        extra={
                            "request_id": request_id,
                            "path": request.url.path,
                            "method": request.method,
                            "query_count": query_count,
                            "top_queries": top_repr,
                        },
                    )
            except Exception:
                logger.exception(
                    "Post-request query metrics logging failed",
                    extra={"request_id": request_id},
                )
            exit_request_scope(rid_token, qc_token, qs_token)

        return response
