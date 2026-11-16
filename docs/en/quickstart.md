# Quickstart

Give each client IP two requests per minute to `GET /orders`. This example uses
in-memory storage and runs in one process.

## Install from the repository

Use an active Python 3.11 or newer virtual environment.

```sh
git clone https://github.com/Bernardoow/fastapi-ratelimits.git
cd fastapi-ratelimits
pip install . uvicorn
```

## Add a rule

Save the example in `app.py`.

```python
from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> dict[str, list[str]]:
    return {"orders": []}
```

Start the server with Uvicorn.

```sh
python -m uvicorn app:app
```

From another terminal, send three requests close together.

```sh
for i in 1 2 3; do
    curl -i http://127.0.0.1:8000/orders
done
```

The first two requests return `200 OK`. The third returns `429 Too Many Requests`
with `Retry-After` in seconds. Restart the server to reset the in-memory counters.

## Use an existing lifespan

Enter `limiter.lifespan(app)` inside the app's lifespan function before it starts
serving requests. If you have more than one limiter, enter each context. The
app below uses a fixed window on every operation and a tighter moving window
on `/orders`. An `AsyncExitStack` closes both contexts at shutdown.

Save this version as `app.py` and run `python -m uvicorn app:app`.

```python title="app.py"
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

baseline = Limiter(storage_uri="async+memory://")
orders_quota = Limiter(storage_uri="async+memory://", strategy="moving-window")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(baseline.lifespan(app))
        await stack.enter_async_context(orders_quota.lifespan(app))
        yield


app = FastAPI(
    lifespan=lifespan,
    dependencies=[Depends(baseline.limit("10/minute"))],
)


@app.get("/orders", dependencies=[Depends(orders_quota.limit("1/minute"))])
async def orders() -> list[str]:
    return []


@app.get("/status")
async def status() -> dict[str, bool]:
    return {"ok": True}
```

Two requests to `/orders` return `200` and `429`. A request to `/status`
still returns `200` under the app-level rule.

See [FastAPI dependencies](dependencies.md) for more ways to apply rules and
[Redis](storage.md#redis) to share counters across workers.
