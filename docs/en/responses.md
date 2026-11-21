# Responses and headers

## Know the default responses

| Status | Cause | Default response |
| --- | --- | --- |
| `429 Too Many Requests` | A rule denied the request. | `{"detail":"Rate limit exceeded"}` and `Retry-After`, an estimate in whole seconds based on the denying rule's window. |
| `503 Service Unavailable` | An operational storage failure prevented a rule from completing. | `{"detail":"Rate limit storage unavailable"}`. The endpoint does not run. |

FastAPI handles `RateLimitExceeded` and `StorageUnavailable` as HTTP
exceptions by default. You can register
`rate_limit_exceeded_handler` and `storage_unavailable_handler` explicitly
to keep that behavior, or register your own handlers to change the body.
Preserve `exc.headers` when customizing `429` so clients still receive
`Retry-After`.

## Document rate limit errors in OpenAPI

Pass `responses=rate_limit_responses()` to a protected operation to show
`429` and `503` in OpenAPI and Swagger UI. The function describes the default
JSON bodies and the `Retry-After` header on `429`.

For a router where all operations share a rate limit dependency, declare the
responses on the router. With a configured `limiter`, use this setup.

```python
from fastapi import APIRouter, Depends

from fastapi_ratelimits import rate_limit_responses

router = APIRouter(
    dependencies=[Depends(limiter.limit("2/minute"))],
    responses=rate_limit_responses(),
)
```

For custom handlers that change the JSON body, pass the corresponding JSON
Schema as `schema_429` or `schema_503`. Each argument replaces only the body
schema for that status. See the operation below for an example using both.

## Add quota headers

Enable `RateLimitHeadersMiddleware` for responses with a status below
`400` when at least one rule admitted the request, including streaming
responses. The default formatter selects the rule with the lowest fraction
of quota remaining. If fractions tie, the first evaluated rule wins.

| Default header | Value |
| --- | --- |
| `X-RateLimit-Limit` | The selected rule's quota amount. |
| `X-RateLimit-Remaining` | The selected rule's remaining quota after admission. |
| `X-RateLimit-Reset` | The selected rule's reset time as a Unix timestamp in seconds, rounded up. |

Provide `headers_func` to customize the headers. The callback receives a
tuple of `RateLimitSnapshot` objects in evaluation order and returns a
mapping of header names to strings. Each snapshot records `limit`,
`remaining`, `reset_at`, `cost`, `scope`, and whether the quota is shared
through `group` (`shared`). These are observations at the time the rule ran.
Concurrent requests can change the remaining quota before a client reads the
header.

## Run the default and custom configurations

With the [quickstart installation](quickstart.md), save this as `app.py`.
The demo can use an intentionally failing storage to reproduce a `503`
without a Redis server.

```python title="app.py"
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from limits.aio.storage import MemoryStorage

from fastapi_ratelimits import (
    Limiter,
    RateLimitExceeded,
    RateLimitHeadersMiddleware,
    RateLimitSnapshot,
    StorageUnavailable,
    default_rate_limit_headers,
    rate_limit_exceeded_handler,
    rate_limit_responses,
    storage_unavailable_handler,
)


class UnavailableStorage(MemoryStorage):
    async def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        raise ConnectionError("Simulated storage outage")


async def quota_exceeded(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "quota_exceeded"},
        headers=exc.headers,
    )


async def unavailable(_request: Request, exc: StorageUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "quota_temporarily_unavailable"},
    )


async def quota_headers(snapshots: tuple[RateLimitSnapshot, ...]) -> dict[str, str]:
    headers = dict(await default_rate_limit_headers(snapshots))
    snapshot = snapshots[0]
    headers["X-Quota-Cost"] = str(snapshot.cost)
    if snapshot.shared:
        headers["X-Quota-Scope"] = snapshot.scope
    return headers


if os.environ.get("SIMULATE_OUTAGE") == "1":
    limiter = Limiter(storage=UnavailableStorage())
else:
    limiter = Limiter(storage_uri="async+memory://")

app = FastAPI(lifespan=limiter.lifespan)
mode = os.environ.get("RESPONSE_MODE")
responses = rate_limit_responses()
if mode == "custom":
    app.add_exception_handler(RateLimitExceeded, quota_exceeded)
    app.add_exception_handler(StorageUnavailable, unavailable)
    app.add_middleware(RateLimitHeadersMiddleware, headers_func=quota_headers)
    error_schema = {
        "type": "object",
        "properties": {"error": {"type": "string"}},
        "required": ["error"],
    }
    responses = rate_limit_responses(schema_429=error_schema, schema_503=error_schema)
else:
    if mode == "builtin":
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
        app.add_exception_handler(StorageUnavailable, storage_unavailable_handler)
    app.add_middleware(RateLimitHeadersMiddleware)


@app.get(
    "/orders",
    dependencies=[Depends(limiter.limit("2/minute", group="orders", cost=2))],
    responses=responses,
)
async def orders() -> list[str]:
    return []
```

Run one of these commands at a time.

```sh
python -m uvicorn app:app
RESPONSE_MODE=custom python -m uvicorn app:app
RESPONSE_MODE=custom SIMULATE_OUTAGE=1 python -m uvicorn app:app
```

For each server run, send two requests from the same client.

```sh
curl -i http://127.0.0.1:8000/orders
curl -i http://127.0.0.1:8000/orders
```

| Mode | First response | Second response |
| --- | --- | --- |
| Default | `200` with `X-RateLimit-Limit: 2` and `X-RateLimit-Remaining: 0`. | `429` with the default body and `Retry-After`. |
| Custom | The same `200` headers, plus `X-Quota-Cost: 2` and `X-Quota-Scope: orders`. | `429` with `{"error":"quota_exceeded"}` and `Retry-After`. |
| Simulated storage failure | `503` with `{"error":"quota_temporarily_unavailable"}`. | The same `503` body. |

To see the default `503` body, rerun the last mode with only
`SIMULATE_OUTAGE=1`. To use the library's explicit exception handlers, set
`RESPONSE_MODE=builtin`.
