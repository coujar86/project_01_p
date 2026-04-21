from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class MethodOverrideMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            query = request.query_params
            if query and query["_method"]:
                method_override = query["_method"].upper()
                if method_override in ("PUT", "DELETE"):
                    request.scope["method"] = method_override

        response = await call_next(request)
        return response
