from __future__ import annotations
from contextvars import ContextVar, Token


request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
query_count_ctx: ContextVar[int] = ContextVar("query_count", default=0)
query_samples_ctx: ContextVar[list[tuple[float, str]] | None] = ContextVar(
    "query_samples", default=None
)


def get_request_id() -> str | None:
    return request_id_ctx.get()


def set_request_id(request_id: str | None) -> None:
    request_id_ctx.set(request_id)


def get_query_count() -> int:
    return query_count_ctx.get()


def reset_query_count() -> None:
    query_count_ctx.set(0)


def inc_query_count() -> int:
    val = query_count_ctx.get() + 1
    query_count_ctx.set(val)
    return val


def get_query_samples() -> list[tuple[float, str]]:
    samples = query_samples_ctx.get()
    return list(samples) if samples else []


def reset_query_samples() -> None:
    query_samples_ctx.set([])


def add_query_samples(duration_ms: float, stmt: str, *, limit: int) -> None:
    samples = query_samples_ctx.get() or []
    samples = [*samples, (duration_ms, stmt)]
    if limit > 0:
        samples = samples[-limit:]
    query_samples_ctx.set(samples)


def enter_request_scope(
    request_id: str,
) -> tuple[Token[str | None], Token[int], Token[list[tuple[float, str]] | None]]:
    rid_token = request_id_ctx.set(request_id)
    qc_token = query_count_ctx.set(0)
    qs_token = query_samples_ctx.set([])
    return (rid_token, qc_token, qs_token)


def exit_request_scope(
    rid_token: Token[str | None],
    qc_token: Token[int],
    qs_token: Token[list[tuple[float, str]] | None],
) -> None:
    request_id_ctx.reset(rid_token)
    query_count_ctx.reset(qc_token)
    query_samples_ctx.reset(qs_token)
