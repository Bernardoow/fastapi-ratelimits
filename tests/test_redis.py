import asyncio
import os
import socket
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from support import client_for

from fastapi_ratelimits import Limiter, StorageStartupError, StorageUnavailable


@pytest.fixture
def redis_uri() -> str:
    uri = os.environ.get("RATELIMITS_TEST_REDIS_URL")
    if not uri:
        pytest.skip("Set RATELIMITS_TEST_REDIS_URL to a disposable Redis server")
    return uri


@pytest.mark.redis
class TestRedis:
    async def test_instances_share_quota_and_redis_keys_start_with_configured_prefix(
        self, *, redis_uri: str
    ) -> None:
        redis = pytest.importorskip("redis.asyncio")
        prefix = f"fastapi-ratelimits-test-{uuid4().hex}"
        async with AsyncExitStack() as stack:
            clients = [
                await stack.enter_async_context(
                    client_for(
                        Limiter(
                            storage_uri=f"async+{redis_uri}",
                            storage_options={"key_prefix": namespace},
                        )
                    )
                )
                for namespace in (prefix, prefix, f"{prefix}-isolated")
            ]
            responses = await asyncio.gather(*(clients[i % 2].get("/") for i in range(8)))
            assert sorted(response.status_code for response in responses) == [200] * 2 + [429] * 6
            assert all(
                int(r.headers["Retry-After"]) > 0 for r in responses if r.status_code == 429
            )
            assert (await clients[2].get("/")).status_code == 200
            async with redis.Redis.from_url(redis_uri) as connection:
                assert len(await connection.keys(f"{prefix}:*")) == 1
                assert len(await connection.keys(f"{prefix}-isolated:*")) == 1

    @pytest.mark.parametrize("custom_handler", [False, True])
    async def test_connection_failure_returns_503_without_running_endpoint(
        self, *, custom_handler: bool
    ) -> None:
        pytest.importorskip("redis.asyncio")
        executed = []
        with socket.socket() as unserved:
            unserved.bind(("127.0.0.1", 0))
            port = unserved.getsockname()[1]
            limiter = Limiter(
                storage_uri=f"async+redis://127.0.0.1:{port}",
                storage_options={"socket_connect_timeout": 0.1},
            )
            app = FastAPI(lifespan=limiter.lifespan)

            if custom_handler:

                @app.exception_handler(StorageUnavailable)
                async def unavailable(request: Request, exc: StorageUnavailable) -> JSONResponse:
                    return JSONResponse({"custom": True}, status_code=503)

            @app.get("/", dependencies=[Depends(limiter.limit("1/minute"))])
            async def endpoint() -> str:
                executed.append(True)
                return "ok"

            async with LifespanManager(app):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    response = await client.get("/")
            assert response.status_code == 503
            assert response.json() == (
                {"custom": True}
                if custom_handler
                else {"detail": "Rate limit storage unavailable"}
            )
            assert not executed

    async def test_unreachable_redis_fails_opt_in_startup(self) -> None:
        pytest.importorskip("redis.asyncio")
        with socket.socket() as unserved:
            unserved.bind(("127.0.0.1", 0))
            port = unserved.getsockname()[1]
            limiter = Limiter(
                storage_uri=f"async+redis://127.0.0.1:{port}",
                storage_options={"socket_connect_timeout": 0.1},
                check_storage_on_startup=True,
            )
            app = FastAPI(lifespan=limiter.lifespan)

            with pytest.raises(StorageStartupError, match="storage check failed during startup"):
                async with LifespanManager(app):
                    pytest.fail("The app started with Redis unavailable")

    async def test_storage_checks_leave_redis_quota_intact(self, *, redis_uri: str) -> None:
        pytest.importorskip("redis.asyncio")
        limiter = Limiter(
            storage_uri=f"async+{redis_uri}",
            storage_options={"key_prefix": f"fastapi-ratelimits-test-{uuid4().hex}"},
            check_storage_on_startup=True,
        )
        app = FastAPI(lifespan=limiter.lifespan)

        @app.get("/", dependencies=[Depends(limiter.limit("2/minute"))])
        async def endpoint() -> str:
            return "ok"

        async with (
            LifespanManager(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            assert (await client.get("/")).status_code == 200
            assert await limiter.check_storage(app) is True
            assert (await client.get("/")).status_code == 200
            assert (await client.get("/")).status_code == 429

    async def test_application_owned_redis_survives_limiter_shutdown(
        self, *, redis_uri: str
    ) -> None:
        from limits.aio.storage import RedisStorage

        redis = pytest.importorskip("redis.asyncio")
        prefix = f"fastapi-ratelimits-test-{uuid4().hex}"
        async with redis.Redis.from_url(redis_uri) as connection:
            storage = RedisStorage(
                f"async+{redis_uri}",
                implementation="redispy",
                key_prefix=prefix,
                connection_pool=connection.connection_pool,
            )
            async with client_for(Limiter(storage=storage)) as client:
                assert (await client.get("/")).status_code == 200
                assert (await client.get("/")).status_code == 200
            async with client_for(Limiter(storage=storage)) as client:
                assert (await client.get("/")).status_code == 429
            assert await connection.ping()

    @pytest.mark.parametrize("strategy", ["moving-window", "sliding-window-counter"])
    async def test_alternative_strategies_keep_redis_prefix(
        self, *, redis_uri: str, strategy: str
    ) -> None:
        redis = pytest.importorskip("redis.asyncio")
        prefix = f"fastapi-ratelimits-test-{uuid4().hex}"
        limiter = Limiter(
            storage_uri=f"async+{redis_uri}",
            storage_options={"key_prefix": prefix},
            strategy=strategy,
        )
        async with client_for(limiter, value="2/second") as client:
            for count in (1, 2, 3):
                response = await client.get("/")
                assert response.status_code == (429 if count == 3 else 200)
            assert int(response.headers["Retry-After"]) > 0
            async with redis.Redis.from_url(redis_uri) as connection:
                assert await connection.keys(f"{prefix}:*")
            max_wait = 1.05 if strategy == "moving-window" else 2.05
            await asyncio.sleep(max_wait)
            assert (await client.get("/")).status_code == 200

    async def test_redis_client_shares_pool_without_closing_it(self, *, redis_uri: str) -> None:
        redis = pytest.importorskip("redis.asyncio")
        prefix = f"fastapi-ratelimits-test-{uuid4().hex}"
        async with redis.Redis.from_url(redis_uri, max_connections=1) as connection:
            limiter = Limiter(redis_client=connection, storage_options={"key_prefix": prefix})
            connection_id = await connection.client_id()
            async with client_for(limiter) as client:
                async with connection.client() as reserved:
                    assert await reserved.client_id() == connection_id
                    assert (await client.get("/")).status_code == 503
                assert [(await client.get("/")).status_code for _ in range(3)] == [200, 200, 429]
            assert await connection.client_id() == connection_id
            async with client_for(limiter) as client:
                assert (await client.get("/")).status_code == 429

    async def test_redis_client_prefix_isolates_quota(self, *, redis_uri: str) -> None:
        redis = pytest.importorskip("redis.asyncio")
        prefix = f"fastapi-ratelimits-test-{uuid4().hex}"

        async def key() -> str:
            return prefix

        async with redis.Redis.from_url(redis_uri) as connection:
            default = Limiter(redis_client=connection, key_func=key)
            custom = Limiter(
                redis_client=connection,
                key_func=key,
                storage_options={"key_prefix": prefix},
            )
            async with client_for(default) as first:
                assert [(await first.get("/")).status_code for _ in range(3)] == [200, 200, 429]
            async with client_for(custom) as second:
                assert (await second.get("/")).status_code == 200
            assert len(await connection.keys(f"LIMITS:*{prefix}*")) == 1
            assert len(await connection.keys(f"{prefix}:*")) == 1

    async def test_resolves_redis_client_once_per_lifespan(self, *, redis_uri: str) -> None:
        redis = pytest.importorskip("redis.asyncio")
        prefix = f"fastapi-ratelimits-test-{uuid4().hex}"
        resolved_for: list[FastAPI] = []

        def provider(app: FastAPI) -> redis.Redis:
            resolved_for.append(app)
            return app.state.redis

        limiter = Limiter(redis_client=provider, storage_options={"key_prefix": prefix})

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with redis.Redis.from_url(redis_uri, max_connections=1) as connection:
                app.state.redis = connection
                async with limiter.lifespan(app):
                    yield

        async def endpoint() -> str:
            return "ok"

        first = FastAPI(lifespan=lifespan)
        second = FastAPI(lifespan=lifespan)
        for app in (first, second):
            app.get("/", dependencies=[Depends(limiter.limit("2/minute"))])(endpoint)
        assert resolved_for == []

        async with (
            LifespanManager(first),
            LifespanManager(second),
            AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as first_http,
            AsyncClient(
                transport=ASGITransport(app=second), base_url="http://test"
            ) as second_http,
        ):
            async with first.state.redis.client():
                assert await limiter.check_storage(first) is False
                assert await limiter.check_storage(second) is True
                assert (await first_http.get("/")).status_code == 503
                assert (await second_http.get("/")).status_code == 200
            assert (await first_http.get("/")).status_code == 200
            assert (await second_http.get("/")).status_code == 429
            assert resolved_for == [first, second]

        async with LifespanManager(first):
            assert resolved_for == [first, second, first]

    async def test_different_strategies_do_not_share_counters(self, *, redis_uri: str) -> None:
        pytest.importorskip("redis.asyncio")
        options = {"key_prefix": f"fastapi-ratelimits-test-{uuid4().hex}"}
        fixed = Limiter(storage_uri=f"async+{redis_uri}", storage_options=options)
        moving = Limiter(
            storage_uri=f"async+{redis_uri}", storage_options=options, strategy="moving-window"
        )
        async with client_for(fixed) as first, client_for(moving) as second:
            assert [(await first.get("/")).status_code for _ in range(3)] == [200, 200, 429]
            assert [(await second.get("/")).status_code for _ in range(3)] == [200, 200, 429]

    async def test_headers_and_owned_connection_shutdown(self, *, redis_uri: str) -> None:
        redis = pytest.importorskip("redis.asyncio")
        namespace = f"fastapi-ratelimits-test-{uuid4().hex}"
        limiter = Limiter(
            storage_uri=f"async+{redis_uri}",
            storage_options={
                "key_prefix": namespace,
                "client_name": namespace,
                "auto_close_connection_pool": False,
            },
        )
        async with redis.Redis.from_url(redis_uri) as observer:
            with pytest.warns(DeprecationWarning, match="auto_close_connection_pool"):
                async with client_for(limiter, headers_enabled=True) as client:
                    response = await client.get("/")
                    assert response.headers["X-RateLimit-Remaining"] == "1"
                    assert (await client.get("/")).headers["X-RateLimit-Remaining"] == "0"
                    assert (await client.get("/")).status_code == 429
                    assert any(item["name"] == namespace for item in await observer.client_list())
            assert all(item["name"] != namespace for item in await observer.client_list())
