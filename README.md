# fastapi-ratelimits

Apply rate limits with FastAPI’s `Depends` and reuse your app’s dependencies
to decide who gets which quota.

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Header

from fastapi_ratelimits import Limiter


async def get_account(x_account: Annotated[str, Header(min_length=1)]) -> str:
    return x_account


async def order_quota(account: Annotated[str, Depends(get_account)]) -> str:
    return "10/minute" if account == "demo-pro" else "2/minute"


limiter = Limiter(storage_uri="async+memory://", key_func=get_account)
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit(order_quota))])
async def orders() -> list[str]:
    return []
```

With `X-Account: demo-basic`, `GET /orders` allows two requests per minute.
With `X-Account: demo-pro`, it allows ten. Each account has its own quota.
In your app, use your authentication dependency in place of the demo header.
Create a separate `Limiter` for each FastAPI application. The same app can
restart its limiter's lifespan.

## Reuse a limiter across routers

Use one `Limiter` for the application and pass a full rule such as
`"10/minute"` or `"1/second"` to `limiter.limit(...)` wherever you need a quota.

```python
from fastapi import APIRouter, Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
orders = APIRouter(prefix="/orders", dependencies=[Depends(limiter.limit("10/minute"))])
reports = APIRouter(prefix="/reports")


@orders.get("")
async def list_orders() -> list[int]:
    return [1, 2]


@orders.get("/{order_id}")
async def get_order(order_id: int) -> dict[str, int]:
    return {"id": order_id}


@reports.get("/summary")
async def report_summary() -> dict[str, int]:
    return {"report_count": 1}


@reports.get("/export", dependencies=[Depends(limiter.limit("1/second"))])
async def export_report() -> dict[str, str]:
    return {"format": "csv"}


app = FastAPI(lifespan=limiter.lifespan)
app.include_router(orders)
app.include_router(reports)
```

Each operation in the orders router allows ten requests per minute per IP.
`GET /reports/export` allows one request per second per IP. See the
[multi-file example](docs/en/dependencies.md#reuse-a-limiter-across-routers)
for sharing the limiter when routers live in separate modules.

Install with `pip install fastapi-ratelimits` on Python 3.11 or newer.
See the [documentation](https://bernardoow.github.io/fastapi-ratelimits/)
for setup, Redis, and more examples.

To work on the library, read the [Development guide](https://bernardoow.github.io/fastapi-ratelimits/development/).
