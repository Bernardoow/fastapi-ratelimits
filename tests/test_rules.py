from typing import Annotated

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI, Header
from httpx import ASGITransport, AsyncClient

from fastapi_ratelimits import Limiter


class TestRules:
    async def test_shared_scope_and_first_refusal_preserve_prior_consumption(self) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)
        first = Depends(limiter.limit("2/minute", group="first"))
        second = Depends(limiter.limit("1/hour", group="second"))
        third = Depends(limiter.limit("1/day", group="third"))

        @app.get("/seed", dependencies=[second])
        @app.get("/combined", dependencies=[first, second, third])
        @app.get("/first", dependencies=[first])
        @app.get("/third", dependencies=[third])
        @app.get(
            "/third-local", operation_id="third", dependencies=[Depends(limiter.limit("1/day"))]
        )
        async def endpoint() -> str:
            return "ok"

        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                assert (await c.get("/seed")).status_code == 200
                refusal = await c.get("/combined")
                assert refusal.status_code == 429
                assert 3500 <= int(refusal.headers["Retry-After"]) <= 3600
                assert (await c.get("/first")).status_code == 200
                assert (await c.get("/first")).status_code == 429
                assert (await c.get("/third")).status_code == 200
                assert (await c.get("/third")).status_code == 429
                assert (await c.get("/third-local")).status_code == 200

    async def test_dynamic_limit_and_cost_share_fastapi_dependencies(self) -> None:
        calls: list[str] = []

        async def plan(x_plan: Annotated[str, Header()]) -> str:
            calls.append(x_plan)
            return x_plan

        async def key(current: Annotated[str, Depends(plan)]) -> str:
            return current

        async def quota(current: Annotated[str, Depends(plan)]) -> str:
            return "5/minute" if current == "pro" else "2/minute"

        async def cost(x_items: Annotated[int, Header()]) -> int:
            return x_items

        limiter = Limiter(storage_uri="async+memory://", key_func=key)
        app = FastAPI(lifespan=limiter.lifespan)
        dynamic = Depends(limiter.limit(quota, cost=cost, group="export"))

        @app.get("/pdf", dependencies=[dynamic])
        @app.get("/csv", dependencies=[dynamic, Depends(limiter.limit("4/hour", cost=2))])
        async def endpoint() -> str:
            return "ok"

        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                assert (
                    await c.get("/pdf", headers={"x-plan": "free", "x-items": "2"})
                ).status_code == 200
                assert calls == ["free"]
                assert (
                    await c.get("/csv", headers={"x-plan": "free", "x-items": "1"})
                ).status_code == 429

                async def override() -> str:
                    return "pro"

                app.dependency_overrides[plan] = override
                assert (await c.get("/csv", headers={"x-items": "2"})).status_code == 200
                with pytest.raises(ValueError, match="positive integer"):
                    await c.get("/pdf", headers={"x-items": "0"})
                assert (await c.get("/csv", headers={"x-items": "3"})).status_code == 200
                assert (await c.get("/pdf", headers={"x-items": "1"})).status_code == 429

    def test_rejects_invalid_static_rule_configuration(self) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        for value in ("0/minute", "1/minute;2/hour", "invalid"):
            with pytest.raises(ValueError):
                limiter.limit(value)
        for cost in (False, 0, -1):
            with pytest.raises(ValueError, match="positive integer"):
                limiter.limit("1/minute", cost=cost)
