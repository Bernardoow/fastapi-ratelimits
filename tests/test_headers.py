from collections.abc import AsyncIterator, Mapping

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI, Response
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from fastapi_ratelimits import Limiter, RateLimitHeadersMiddleware, RateLimitSnapshot


async def body() -> AsyncIterator[bytes]:
    yield b"hello"


class TestResponseHeaders:
    @pytest.mark.parametrize("kind", ["json", "response", "stream"])
    @pytest.mark.parametrize("enabled", [True, False])
    async def test_headers_on_final_response_without_extra_consumption(
        self, *, kind: str, enabled: bool
    ) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)
        if enabled:
            app.add_middleware(RateLimitHeadersMiddleware)

        @app.get("/", dependencies=[Depends(limiter.limit("2/minute"))], response_model=None)
        async def endpoint() -> dict[str, bool] | Response:
            if kind == "stream":
                return StreamingResponse(body())
            if kind == "response":
                return Response("hello", headers={"X-App": "preserved"})
            return {"ok": True}

        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                first = await c.get("/")
                second = await c.get("/")
                third = await c.get("/")
                assert [first.status_code, second.status_code, third.status_code] == [
                    200,
                    200,
                    429,
                ]
                assert "Retry-After" in third.headers
                assert "X-RateLimit-Remaining" not in third.headers
                if enabled:
                    assert first.headers["X-RateLimit-Limit"] == "2"
                    assert first.headers["X-RateLimit-Remaining"] == "1"
                    assert second.headers["X-RateLimit-Remaining"] == "0"
                    assert int(first.headers["X-RateLimit-Reset"]) > 0
                else:
                    assert "X-RateLimit-Limit" not in first.headers
                if kind == "response":
                    assert first.headers["X-App"] == "preserved"

    async def test_custom_headers_receive_ordered_resolved_rules(self) -> None:
        async def dynamic() -> str:
            return "10/minute"

        def header_builder(snapshots: tuple[RateLimitSnapshot, ...]) -> Mapping[str, str]:
            return {
                "X-Quota": "/".join(
                    f"{rule.scope}:{rule.limit}:{rule.cost}:{rule.remaining}" for rule in snapshots
                )
            }

        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)
        app.add_middleware(RateLimitHeadersMiddleware, headers_func=header_builder)

        @app.get(
            "/",
            operation_id="local",
            dependencies=[
                Depends(limiter.limit(dynamic, group="reports", cost=2)),
                Depends(limiter.limit("2/hour")),
            ],
        )
        async def endpoint() -> str:
            return "ok"

        with pytest.warns(UserWarning, match="async def"):
            async with LifespanManager(app):
                pass
        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                response = await c.get("/")
                assert response.headers["X-Quota"] == "reports:10:2:8/local:2:1:1"
                assert "X-RateLimit-Limit" not in response.headers
