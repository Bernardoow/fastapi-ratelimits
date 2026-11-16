import inspect
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .callbacks import is_async_callable, warn_if_sync

_SNAPSHOTS = "fastapi_ratelimits.snapshots"


@dataclass(frozen=True, slots=True)
class RateLimitSnapshot:
    """The quota observed immediately after an admitted rule consumed its cost."""

    limit: int
    remaining: int
    reset_at: float
    cost: int
    scope: str
    shared: bool


HeadersFactory = Callable[
    [tuple[RateLimitSnapshot, ...]], Mapping[str, str] | Awaitable[Mapping[str, str]]
]


async def default_rate_limit_headers(
    snapshots: tuple[RateLimitSnapshot, ...],
) -> Mapping[str, str]:
    if not snapshots:
        return {}
    rule = min(snapshots, key=lambda item: item.remaining / item.limit)
    return {
        "X-RateLimit-Limit": str(rule.limit),
        "X-RateLimit-Remaining": str(rule.remaining),
        "X-RateLimit-Reset": str(math.ceil(rule.reset_at)),
    }


def request_snapshots(*, scope: Scope) -> list[RateLimitSnapshot] | None:
    snapshots: list[RateLimitSnapshot] | None = scope.get(_SNAPSHOTS)
    return snapshots


class RateLimitHeadersMiddleware:
    """Add quota headers to final HTTP responses, including streaming responses."""

    def __init__(
        self, app: ASGIApp, *, headers_func: HeadersFactory = default_rate_limit_headers
    ) -> None:
        warn_if_sync(headers_func)
        self._app = app
        self._headers_func = headers_func
        self._async_headers = is_async_callable(headers_func)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        snapshots: list[RateLimitSnapshot] = []
        scope[_SNAPSHOTS] = snapshots

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start" and message["status"] < 400 and snapshots:
                values = tuple(snapshots)
                headers = (
                    self._headers_func(values)
                    if self._async_headers
                    else await run_in_threadpool(self._headers_func, values)
                )
                if inspect.isawaitable(headers):
                    headers = await headers
                response_headers = MutableHeaders(scope=message)
                for name, value in headers.items():
                    response_headers[name] = value
            await send(message)

        await self._app(scope, receive, send_with_headers)
