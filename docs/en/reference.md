# API reference

Import these names directly from `fastapi_ratelimits`.

| Configuration | Examples |
| --- | --- |
| `Limiter(storage_uri=..., storage_options=..., strategy=...)` or `Limiter(storage=..., strategy=...)` | [Storage sources and strategies](storage.md) |
| `Limiter(redis_client=..., storage_options=...)` | [Use an existing Redis client or obtain one at startup](storage.md#share-your-applications-redis-client) |
| `Limiter(key_func=..., route_id_func=...)` | [Client key and route scope](rules.md#choose-the-client-key-and-route-scope) |
| `Limiter.lifespan(app)` | [Single and composed lifespans](quickstart.md) |
| `Limiter.limit(value, key_func=..., group=..., cost=..., skip_if=...)` | [Rule options](rules.md) and [FastAPI dependencies](dependencies.md) |
| `RateLimitHeadersMiddleware(headers_func=...)`, exceptions, and handlers | [Responses and headers](responses.md) |

## Limiter

Supply exactly one of `storage_uri`, `storage`, and `redis_client`. The
`redis_client` parameter accepts a `redis.asyncio.Redis` instance or a
synchronous function with the signature `(app: FastAPI) -> redis.asyncio.Redis`.
The limiter calls the function once per entry to its lifespan for that app.
It uses the returned client's pool, which the application owns and closes.

With `redis_client`, `storage_options` accepts `key_prefix` (default
`LIMITS`) and `wrap_exceptions`. Configure connection options such as
`socket_timeout` on the application's client or pool.

::: fastapi_ratelimits.Limiter
    options:
      members:
        - lifespan
        - limit

## Default identity and route helpers

::: fastapi_ratelimits.key_by_ip

::: fastapi_ratelimits.default_route_id

## Quota response headers

::: fastapi_ratelimits.RateLimitHeadersMiddleware

::: fastapi_ratelimits.RateLimitSnapshot

::: fastapi_ratelimits.default_rate_limit_headers

## Exceptions and handlers

::: fastapi_ratelimits.RateLimitExceeded

::: fastapi_ratelimits.rate_limit_exceeded_handler

::: fastapi_ratelimits.StorageUnavailable

::: fastapi_ratelimits.storage_unavailable_handler

## Warnings

::: fastapi_ratelimits.SynchronousCallbackWarning
