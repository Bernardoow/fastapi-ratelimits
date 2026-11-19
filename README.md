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

Install with `pip install fastapi-ratelimits` on Python 3.11 or newer.
See the [documentation](https://bernardoow.github.io/fastapi-ratelimits/)
for setup, Redis, and more examples.

To work on the library, read the [Development guide](https://bernardoow.github.io/fastapi-ratelimits/development/).
