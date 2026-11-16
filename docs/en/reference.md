# API reference

Import these names directly from `fastapi_ratelimits`.

## Limiter

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
