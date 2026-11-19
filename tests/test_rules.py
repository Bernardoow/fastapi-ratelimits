from typing import Annotated

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI, Header
from httpx import ASGITransport, AsyncClient

from fastapi_ratelimits import Limiter, RateLimitHeadersMiddleware


class TestRules:
    async def test_skip_if_uses_fastapi_dependencies_and_only_skips_its_rule(self) -> None:
        calls: list[str] = []

        async def contract(x_contract: Annotated[str, Header()]) -> str:
            calls.append(x_contract)
            return x_contract

        async def is_exempt(current: Annotated[str, Depends(contract)]) -> bool:
            return current == "exempt"

        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)
        app.add_middleware(RateLimitHeadersMiddleware)
        conditional = Depends(limiter.limit("1/hour", group="contract", skip_if=is_exempt))
        operation = Depends(limiter.limit("2/hour", group="operation"))

        @app.get("/combined", dependencies=[conditional, operation])
        @app.get("/contract", dependencies=[conditional])
        async def endpoint(current: Annotated[str, Depends(contract)]) -> str:
            return current

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            headers = {"x-contract": "exempt"}
            response = await client.get("/combined", headers=headers)
            assert response.status_code == 200
            assert response.headers["X-RateLimit-Limit"] == "2"
            assert calls == ["exempt"]
            assert (await client.get("/combined", headers=headers)).status_code == 200
            assert (await client.get("/combined", headers=headers)).status_code == 429

            response = await client.get("/contract", headers=headers)
            assert response.status_code == 200
            assert "X-RateLimit-Limit" not in response.headers

            async def metered_contract() -> str:
                return "metered"

            app.dependency_overrides[contract] = metered_contract
            assert (await client.get("/contract")).status_code == 200
            assert (await client.get("/contract")).status_code == 429

    @pytest.mark.parametrize("result", ["false", 1, None])
    async def test_skip_if_provider_must_return_a_bool(self, *, result: object) -> None:
        async def condition() -> object:
            return result

        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)

        @app.get("/", dependencies=[Depends(limiter.limit("1/hour", skip_if=condition))])
        async def endpoint() -> str:
            return "ok"

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            with pytest.raises(ValueError, match="skip_if provider must return a bool"):
                await client.get("/")

    def test_rejects_invalid_static_skip_if(self) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        with pytest.raises(ValueError, match="skip_if must be a bool or a callable"):
            limiter.limit("1/hour", skip_if="false")

    def test_rejects_invalid_static_cost_even_when_skipped(self) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        with pytest.raises(ValueError, match="positive integer"):
            limiter.limit("1/hour", cost=0, skip_if=True)

    async def test_static_skip_if_keeps_provider_input_validation(self) -> None:
        async def cost(x_items: Annotated[int, Header()]) -> int:
            return x_items

        limiter = Limiter(storage_uri="async+memory://")
        app = FastAPI(lifespan=limiter.lifespan)

        skipped = Depends(limiter.limit("1/hour", cost=cost, skip_if=True))

        @app.get("/skipped", dependencies=[skipped])
        @app.get("/metered", dependencies=[Depends(limiter.limit("1/hour", skip_if=False))])
        async def endpoint() -> str:
            return "ok"

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            assert (await client.get("/skipped")).status_code == 422
            assert (await client.get("/skipped", headers={"x-items": "0"})).status_code == 200
            assert (await client.get("/metered")).status_code == 200
            assert (await client.get("/metered")).status_code == 429

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
