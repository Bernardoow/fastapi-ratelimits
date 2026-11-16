import math
import time

from fastapi import HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from limits import RateLimitItem
from starlette.responses import Response


class RateLimitExceeded(HTTPException):
    def __init__(self, *, limit: RateLimitItem, reset_at: float, cost: int, scope: str) -> None:
        self.limit = limit
        self.reset_at = reset_at
        self.cost = cost
        self.scope = scope
        super().__init__(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(1, math.ceil(reset_at - time.time())))},
        )


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, RateLimitExceeded):
        raise exc
    return await http_exception_handler(request, exc)


class StorageUnavailable(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=503, detail="Rate limit storage unavailable")


async def storage_unavailable_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, StorageUnavailable):
        raise exc
    return await http_exception_handler(request, exc)
