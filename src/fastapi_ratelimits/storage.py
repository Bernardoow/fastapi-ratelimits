import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol, cast

from limits.aio.storage import MemoryStorage, RedisStorage, Storage
from limits.aio.storage.redis.redispy import RedispyBridge

_REDIS_SCHEMES = {"async+redis", "async+rediss", "async+redis+unix"}


class _RedisConnection(Protocol):
    async def aclose(self, *, close_connection_pool: bool) -> None: ...


@asynccontextmanager
async def open_storage(*, uri: str, options: Mapping[str, Any]) -> AsyncIterator[Storage]:
    scheme, separator, _ = uri.partition("://")
    if not separator:
        raise ValueError("storage_uri must be an async storage URI")

    if scheme == "async+memory":
        if options:
            raise ValueError("Memory storage does not take storage_options")
        memory = MemoryStorage()
        try:
            yield memory
        finally:
            if memory.timer is not None:
                memory.timer.cancel()
                await asyncio.gather(memory.timer, return_exceptions=True)
        return

    if scheme not in _REDIS_SCHEMES:
        raise ValueError("Use an async memory or Redis URI, or provide an async storage object")

    settings = dict(options)
    if settings.pop("implementation", "redispy") != "redispy" or "connection_pool" in settings:
        raise ValueError("Redis URI configuration uses a Redis-py client owned by the limiter")
    redis = RedisStorage(uri, implementation="redispy", **settings)
    try:
        yield redis
    finally:
        # limits has no backend-independent close method. This connection is owned here.
        connection = cast(RedispyBridge, redis.bridge).get_connection()
        await cast(_RedisConnection, connection).aclose(close_connection_pool=True)
