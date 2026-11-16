# Responses and headers

## When a request is rejected

| Status | Cause | What the client receives |
| --- | --- | --- |
| `429 Too Many Requests` | A rule denied the request. | A `Retry-After` header with an estimate in whole seconds based on the denying rule's window. |
| `503 Service Unavailable` | An operational failure prevented the storage backend from processing the rule. | An error response. The endpoint does not run. |

Register FastAPI exception handlers for `RateLimitExceeded` and
`StorageUnavailable` to customize these responses. When overriding `429`, pass
through `exc.headers` to preserve `Retry-After`.

```python
from fastapi import Request
from fastapi.responses import JSONResponse

from fastapi_ratelimits import RateLimitExceeded


@app.exception_handler(RateLimitExceeded)
async def quota_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "quota_exceeded"},
        headers=exc.headers,
    )
```

## Add quota headers

Register `RateLimitHeadersMiddleware` before starting the app.

```python
from fastapi_ratelimits import RateLimitHeadersMiddleware

app.add_middleware(RateLimitHeadersMiddleware)
```

The middleware adds these headers to responses with a status below `400` when
at least one rule admitted the request. Streaming responses are supported.

| Header | Value |
| --- | --- |
| `X-RateLimit-Limit` | The selected rule's quota amount. |
| `X-RateLimit-Remaining` | The selected rule's remaining quota after admitting the request. |
| `X-RateLimit-Reset` | The selected rule's reset time as a Unix timestamp in seconds, rounded up. |

With several rules, the default formatter picks the rule with the lowest
fraction of quota remaining. Ties go to the first rule evaluated. Readings
can change as concurrent requests consume quota. The middleware consumes no
quota itself.

Pass `headers_func` to the middleware to format the tuple of
`RateLimitSnapshot` objects in rule evaluation order. The callback returns a
mapping of header names to string values.
