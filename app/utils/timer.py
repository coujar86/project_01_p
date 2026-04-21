import time
import logging
from contextlib import ContextDecorator, AsyncContextDecorator
from typing import Optional
from app.core.context import request_id_ctx


logger = logging.getLogger("perf.elapsed")


class ElapsedTime(ContextDecorator, AsyncContextDecorator):
    """
    Usage:
        with ElapsedTime("service.blog.list"):
            ...

        async with ElapsedTime("service.blog.list"):
            ...

        @ElapsedTime("service.blog.list")
        async def func(...):
            ...
    """

    def __init__(
        self,
        label: str = "execution",
        *,
        warn_ms: Optional[float] = None,
        log_level: int = logging.INFO,
    ):
        """
        :param label: 로그에 찍힐 구간 이름
        :param warn_ms: 이 시간(ms) 초과 시 WARNING으로 로그
        :param log_level: 기본 로그 레벨
        """
        self.label = label
        self.warn_ms = warn_ms
        self.log_level = log_level

    # ---------- sync ----------
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._log()

    # ---------- async ----------
    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__exit__(exc_type, exc, tb)

    # ---------- internal ----------
    def _log(self):
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        request_id = request_id_ctx.get()

        level = self.log_level
        if self.warn_ms is not None and elapsed_ms >= self.warn_ms:
            level = logging.WARNING

        logger.log(
            level,
            "elapsed time",
            extra={
                "label": self.label,
                "elapsed_ms": round(elapsed_ms, 2),
                "request_id": request_id,
            },
        )
