import asyncio
import threading
import warnings
from typing import Annotated

import pytest
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, Depends, FastAPI, Header, Request
from httpx import ASGITransport, AsyncClient

from fastapi_ratelimits import Limiter


class TestKeyDependencies:
    async def test_annotated_key_with_default_on_included_router(self) -> None:
        async def key(x_user: Annotated[str, Header()] = "anonymous") -> str:
            return x_user

        limiter = Limiter(storage_uri="async+memory://", key_func=key)
        router = APIRouter()

        @router.get("/items", dependencies=[Depends(limiter.limit("1/minute"))])
        async def items() -> str:
            return "ok"

        app = FastAPI(lifespan=limiter.lifespan)
        app.include_router(router, prefix="/api")
        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            assert (await client.get("/api/items")).status_code == 200
            assert (await client.get("/api/items")).status_code == 429
            assert (await client.get("/api/items", headers={"x-user": "alice"})).status_code == 200

    async def test_native_cache_overrides_and_per_rule_keys(self) -> None:
        calls: list[str] = []

        async def user(x_user: Annotated[str, Header()]) -> str:
            calls.append(x_user)
            return x_user

        async def key(current: Annotated[str, Depends(user)]) -> str:
            return current

        limiter = Limiter(storage_uri="async+memory://", key_func=key)
        app = FastAPI(lifespan=limiter.lifespan)

        @app.get("/me", dependencies=[Depends(limiter.limit("1/minute"))])
        async def me(current: Annotated[str, Depends(user)]) -> str:
            return current

        async def alternate_key(request: Request) -> str:
            return request.headers["x-other"]

        @app.get(
            "/other", dependencies=[Depends(limiter.limit("1/minute", key_func=alternate_key))]
        )
        async def other() -> str:
            return "ok"

        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                assert (await c.get("/me", headers={"x-user": "alice"})).status_code == 200
                assert calls == ["alice"]
                assert (await c.get("/me", headers={"x-user": "alice"})).status_code == 429
                assert (await c.get("/me", headers={"x-user": "bob"})).status_code == 200

                async def override() -> str:
                    return "carol"

                app.dependency_overrides[user] = override
                assert (await c.get("/me")).json() == "carol"
                assert (await c.get("/me")).status_code == 429
                assert (await c.get("/other", headers={"x-other": "a"})).status_code == 200
                assert (await c.get("/other", headers={"x-other": "b"})).status_code == 200

    async def test_sync_key_warns_at_configuration_without_blocking_loop(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def key() -> str:
            entered.set()
            if not release.wait(2):
                raise TimeoutError("Event loop did not progress")
            return "shared"

        with pytest.warns(UserWarning, match="async def"):
            limiter = Limiter(storage_uri="async+memory://", key_func=key)
        app = FastAPI(lifespan=limiter.lifespan)

        @app.get("/", dependencies=[Depends(limiter.limit("1/minute"))])
        async def endpoint() -> str:
            return "ok"

        async with LifespanManager(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                with warnings.catch_warnings(record=True) as observed:
                    task = asyncio.create_task(c.get("/"))
                    try:
                        async with asyncio.timeout(1):
                            while not entered.is_set():
                                await asyncio.sleep(0.001)
                    finally:
                        release.set()
                    assert (await task).status_code == 200
                    assert not observed

    async def test_route_id_provider_can_override_the_default_scope(self) -> None:
        async def logical_route(request: Request) -> str:
            return request.headers["x-operation"]

        limiter = Limiter(storage_uri="async+memory://", route_id_func=logical_route)
        app = FastAPI(lifespan=limiter.lifespan)

        @app.get("/one", dependencies=[Depends(limiter.limit("1/minute"))])
        @app.get("/two", dependencies=[Depends(limiter.limit("1/minute"))])
        async def endpoint() -> str:
            return "ok"

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            assert (
                await client.get("/one", headers={"x-operation": "exports"})
            ).status_code == 200
            assert (
                await client.get("/two", headers={"x-operation": "exports"})
            ).status_code == 429
            assert (
                await client.get("/two", headers={"x-operation": "reports"})
            ).status_code == 200
