from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from fastapi_ratelimits import Limiter, RateLimitHeadersMiddleware


@asynccontextmanager
async def client_for(
    limiter: Limiter, *, value: str = "2/minute", headers_enabled: bool = False
) -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=limiter.lifespan)
    if headers_enabled:
        app.add_middleware(RateLimitHeadersMiddleware)

    @app.get("/", dependencies=[Depends(limiter.limit(value))])
    async def endpoint() -> str:
        return "ok"

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client
