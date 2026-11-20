from unittest.mock import AsyncMock

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from limits.aio.storage import MemoryStorage
from support import client_for

from fastapi_ratelimits import Limiter, StorageStartupError


class TestStorageConfiguration:
    async def test_accepts_redis_client_as_only_storage_source(self) -> None:
        redis = pytest.importorskip("redis.asyncio")
        async with redis.Redis() as connection:
            async with client_for(Limiter(redis_client=connection)):
                pass
            with pytest.raises(ValueError, match="exactly one"):
                Limiter(storage_uri="async+redis://", redis_client=connection)
            with pytest.raises(ValueError, match="exactly one"):
                Limiter(storage=MemoryStorage(), redis_client=connection)

    @pytest.mark.parametrize("option", ["connection_pool", "socket_timeout"])
    def test_rejects_connection_options_with_redis_client(self, *, option: str) -> None:
        redis = pytest.importorskip("redis.asyncio")
        with pytest.raises(ValueError, match=rf"{option}.*application's Redis client"):
            Limiter(redis_client=redis.Redis(), storage_options={option: 1})

    async def test_rejects_incompatible_redis_client(self) -> None:
        redis = pytest.importorskip("redis")
        with redis.Redis() as connection:
            with pytest.raises(TypeError, match="redis.asyncio.Redis"):
                async with client_for(Limiter(redis_client=connection)):
                    pytest.fail("A synchronous Redis client must not start")

    async def test_rejects_incompatible_client_from_provider(self) -> None:
        pytest.importorskip("redis.asyncio")

        def provider(app: FastAPI) -> object:
            return object()

        limiter = Limiter(redis_client=provider)
        with pytest.raises(TypeError, match="redis.asyncio.Redis"):
            async with client_for(limiter):
                pytest.fail("An invalid Redis client provider must fail during startup")

    def test_requires_one_async_storage_source(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            Limiter()
        with pytest.raises(ValueError, match="exactly one"):
            Limiter(storage_uri="async+memory://", storage=MemoryStorage())
        with pytest.raises(ValueError, match="storage_options"):
            Limiter(storage=MemoryStorage(), storage_options={})
        with pytest.raises(ValueError, match="async"):
            Limiter(storage_uri="memory://")

    async def test_supplied_memory_retains_counters_across_app_lifespans(self) -> None:
        storage = MemoryStorage()
        async with client_for(Limiter(storage=storage)) as client:
            assert (await client.get("/")).status_code == 200
            assert (await client.get("/")).status_code == 200
        async with client_for(Limiter(storage=storage)) as client:
            assert (await client.get("/")).status_code == 429

    async def test_supplied_storage_fault_blocks_request(self) -> None:
        class OfflineStorage(MemoryStorage):
            async def incr(self, key: str, expiry: int, amount: int = 1) -> int:
                raise ConnectionError("Storage disconnected")

        async with client_for(Limiter(storage=OfflineStorage())) as client:
            assert (await client.get("/")).status_code == 503


class TestStorageReadiness:
    async def test_checks_active_storage_on_demand(
        self, *, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        storage = MemoryStorage()
        failure = ConnectionError("Storage disconnected")
        check = AsyncMock(side_effect=[False, True, failure])
        monkeypatch.setattr(storage, "check", check)
        limiter = Limiter(storage=storage)
        app = FastAPI(lifespan=limiter.lifespan)

        with pytest.raises(RuntimeError, match="Limiter.lifespan"):
            await limiter.check_storage(app)
        async with LifespanManager(app):
            check.assert_not_awaited()
            with pytest.raises(RuntimeError, match="Limiter.lifespan"):
                await limiter.check_storage(FastAPI())
            assert await limiter.check_storage(app) is False
            assert await limiter.check_storage(app) is True
            with pytest.raises(ConnectionError) as error:
                await limiter.check_storage(app)
            assert error.value is failure
        with pytest.raises(RuntimeError, match="Limiter.lifespan"):
            await limiter.check_storage(app)
        assert check.await_count == 3

    @pytest.mark.parametrize(
        ("outcome", "error_type"),
        [
            (False, StorageStartupError),
            (TimeoutError("Probe timed out"), StorageStartupError),
            (ValueError("Declared by MemoryStorage"), StorageStartupError),
            (TypeError("Unexpected check error"), TypeError),
        ],
    )
    async def test_startup_check_failure_releases_app_state(
        self,
        *,
        monkeypatch: pytest.MonkeyPatch,
        outcome: bool | Exception,
        error_type: type[Exception],
    ) -> None:
        storage = MemoryStorage()
        check = AsyncMock(side_effect=[outcome, True])
        monkeypatch.setattr(storage, "check", check)
        limiter = Limiter(storage=storage, check_storage_on_startup=True)
        app = FastAPI(lifespan=limiter.lifespan)

        with pytest.raises(error_type) as error:
            async with LifespanManager(app):
                pytest.fail("The app started with a failed storage check")
        if error_type is StorageStartupError:
            assert str(error.value) == "Rate limit storage check failed during startup"
            assert error.value.__cause__ is (outcome if isinstance(outcome, Exception) else None)
        else:
            assert error.value is outcome
        with pytest.raises(RuntimeError, match="Limiter.lifespan"):
            await limiter.check_storage(app)

        check.assert_awaited_once_with()
        async with LifespanManager(app):
            assert check.await_count == 2


class TestStrategies:
    @pytest.mark.parametrize(
        "strategy", ["fixed-window", "moving-window", "sliding-window-counter"]
    )
    async def test_selects_strategy_with_memory_uri_and_supplied_storage(
        self, *, strategy: str
    ) -> None:
        for limiter in (
            Limiter(storage_uri="async+memory://", strategy=strategy),
            Limiter(storage=MemoryStorage(), strategy=strategy),
        ):
            async with client_for(limiter) as client:
                assert [(await client.get("/")).status_code for _ in range(3)] == [200, 200, 429]

    def test_unknown_strategy_is_a_configuration_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown.*strategy"):
            Limiter(storage_uri="async+memory://", strategy="unsupported")

    async def test_incompatible_storage_fails_during_startup(
        self, *, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        storage = MemoryStorage()
        monkeypatch.setattr(storage, "get_moving_window", None)
        with pytest.raises(
            ValueError, match="moving-window.*does not support|does not support.*moving-window"
        ):
            async with client_for(Limiter(storage=storage, strategy="moving-window")):
                pytest.fail("An incompatible strategy must not start")
