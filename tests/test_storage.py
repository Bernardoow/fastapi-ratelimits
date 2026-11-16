import pytest
from limits.aio.storage import MemoryStorage
from support import client_for

from fastapi_ratelimits import Limiter


class TestStorageConfiguration:
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
