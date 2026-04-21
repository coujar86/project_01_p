from app.core.config import get_settings
import logging
import sys

settings = get_settings()


def setup_logging() -> None:
    # Idempotent guard
    if getattr(setup_logging, "_configured", False):
        return

    # Read log level (default = INFO)
    level_name = getattr(settings, "log_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    format = "%(asctime)s %(levelname)s %(name)s [pid=%(process)d] %(message)s"

    root_logger = logging.getLogger()
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    logging.basicConfig(
        level=level,
        format=format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Noise control
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    # Custom level setup (example)
    # logging.getLogger("app.exceptions").setLevel(logging.WARNING)

    setup_logging._configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
