# Storage and strategies

Configure exactly one of `storage_uri` or `storage` when creating a `Limiter`.

## In-memory storage

Use `Limiter(storage_uri="async+memory://")` for local development or when each
application instance should have independent counters. Counters are local to
the instance and reset when its lifespan ends. The memory URI takes no
`storage_options`.

## Redis

To share quotas across processes, point each worker at the same Redis database
and use the same key prefix, strategy, and rules. Install the Redis extra from
the repository checkout.

```sh
pip install '.[redis]'
```

```python
from fastapi_ratelimits import Limiter

limiter = Limiter(
    storage_uri="async+redis://localhost:6379/0",
    storage_options={"key_prefix": "orders-api", "socket_timeout": 0.5},
    strategy="moving-window",
)
```

In this example, Redis keys start with `orders-api:`. URI configuration supports
TCP (`async+redis`), TLS (`async+rediss`), and Unix sockets (`async+redis+unix`).
`Limiter.lifespan` manages resources created from a URI.

## Supply your own storage

Pass an instance of `limits.aio.storage.Storage` as `Limiter(storage=my_storage)`.
When using this form, configure the options and key prefix on your storage
instance and manage its lifespan in your application.

## Choose a strategy

The strategy applies to every rule created by a `Limiter`. In-memory storage
and Redis support all three. A supplied backend must support the chosen
strategy.

| Strategy | How it counts requests |
| --- | --- |
| `fixed-window` (default) | Counts requests in a fixed period. A client can use its quota near the end of one period and again as the next one starts. |
| `moving-window` | Tracks timestamps to count requests within the last full window. |
| `sliding-window-counter` | Estimates usage using a weighted count from the current and previous windows. |

Use separate `Limiter` instances for different strategies. Their counters are
separate even if they use the same backend and prefix. If multiple instances
serve one app, enter each limiter's lifespan in the app's lifespan function.
