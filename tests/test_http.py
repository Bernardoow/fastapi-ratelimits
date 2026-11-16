import asyncio
from contextlib import AsyncExitStack

import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from fastapi_ratelimits import Limiter, RateLimitExceeded


class TestStaticLimit:
    @pytest.mark.parametrize("sync_endpoint", [False, True])
    async def test_limits_requests_before_endpoint(self, *, sync_endpoint: bool) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)
        executed: list[str] = []

        def endpoint() -> dict[str, bool]:
            executed.append("called")
            return {"ok": True}

        async def async_endpoint() -> dict[str, bool]:
            return endpoint()

        app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])(
            endpoint if sync_endpoint else async_endpoint
        )
        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            assert (await client.get("/orders")).status_code == 200
            assert (await client.get("/orders")).status_code == 200
            blocked = await client.get("/orders")
            assert blocked.status_code == 429
            assert int(blocked.headers["Retry-After"]) > 0
            assert executed == ["called", "called"]

    async def test_uses_peer_ip_and_effective_operation_id_with_included_routers(self) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)
        router = APIRouter()

        @router.get("/items", dependencies=[Depends(limiter.limit("1/minute"))])
        async def items() -> str:
            return "ok"

        app.include_router(router, prefix="/one")
        app.include_router(router, prefix="/two")
        app.get(
            "/alias-a", operation_id="shared-id", dependencies=[Depends(limiter.limit("1/minute"))]
        )(items)
        app.get(
            "/alias-b", operation_id="shared-id", dependencies=[Depends(limiter.limit("1/minute"))]
        )(items)

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(LifespanManager(app))
            client, other = [
                await stack.enter_async_context(
                    AsyncClient(
                        transport=ASGITransport(app=app, client=(ip, 1234)), base_url="http://test"
                    )
                )
                for ip in ("192.0.2.1", "192.0.2.2")
            ]
            assert (await client.get("/one/items")).status_code == 200
            assert (await client.get("/two/items")).status_code == 200
            spoofed = await client.get("/one/items", headers={"X-Forwarded-For": "192.0.2.2"})
            assert spoofed.status_code == 429
            assert (await other.get("/one/items")).status_code == 200
            assert (await client.get("/alias-a")).status_code == 200
            assert (await client.get("/alias-b")).status_code == 429

    async def test_admitted_errors_consume_quota_and_window_resets(self) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)

        @app.exception_handler(RateLimitExceeded)
        async def blocked(request: Request, exc: RateLimitExceeded) -> JSONResponse:
            return JSONResponse({"quota": exc.limit.amount}, status_code=429, headers=exc.headers)

        @app.get("/", dependencies=[Depends(limiter.limit("1/second"))])
        async def endpoint() -> str:
            raise HTTPException(500, detail="endpoint error")

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            assert (await client.get("/")).status_code == 500
            rejection = await client.get("/")
            assert rejection.status_code == 429
            assert rejection.json() == {"quota": 1}
            await asyncio.sleep(1.05)
            assert (await client.get("/")).status_code == 500
