from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from inspect import iscoroutine
from typing import TYPE_CHECKING, Any, Protocol, cast

from limits.aio.storage import MemoryStorage, RedisStorage, Storage
from limits.aio.storage.redis.redispy import RedispyBridge

if TYPE_CHECKING:
    from fastapi import FastAPI

try:
    from redis.asyncio import Redis as Redis
except ModuleNotFoundError as exc:
    if exc.name != "redis":
        raise
    Redis = Any  # type: ignore[misc,assignment]
    _REDIS_AVAILABLE = False
else:
    _REDIS_AVAILABLE = True

_REDIS_SCHEMES = {"async+redis", "async+rediss", "async+redis+unix"}
_EXTERNAL_REDIS_OPTIONS = {"key_prefix", "wrap_exceptions"}


class _RedisConnection(Protocol):
    async def aclose(self, *, close_connection_pool: bool) -> None: ...


def validate_redis_client_options(*, options: Mapping[str, Any]) -> None:
    unsupported = options.keys() - _EXTERNAL_REDIS_OPTIONS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(
            f"Unsupported storage_options with redis_client: {names}. "
            "Only key_prefix and wrap_exceptions are supported. "
            "Configure connection options on the application's Redis client."
        )


def storage_from_redis_client(
    *, source: Redis | Callable[[FastAPI], Redis], app: FastAPI, options: Mapping[str, Any]
) -> Storage:
    if not _REDIS_AVAILABLE:
        raise ImportError("Install fastapi-ratelimits[redis] to use redis_client")

    client = source(app) if not isinstance(source, Redis) and callable(source) else source
    if not isinstance(client, Redis):
        if iscoroutine(client):
            client.close()
        raise TypeError(
            "redis_client must be a redis.asyncio.Redis instance "
            "or a synchronous function returning one"
        )

    # With a pool supplied, limits uses it instead of the URI for connections.
    settings = dict(options, connection_pool=client.connection_pool)
    return RedisStorage("async+redis://", implementation="redispy", **settings)


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
