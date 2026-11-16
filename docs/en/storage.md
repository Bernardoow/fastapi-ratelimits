# Storage and strategies

Pass exactly one of `storage_uri` and `storage` to `Limiter`. With a URI,
the limiter owns the storage and manages it through its lifespan. With
`storage=...`, the application owns the instance and its cleanup.

## Try memory, Redis, and all three strategies

Save this example as `app.py`. It starts with in-memory storage and the
default strategy. To use Redis, run `pip install '.[redis]'` from the
repository checkout in the [quickstart](quickstart.md) environment and have
a Redis server available.

```python title="app.py"
import os

from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

uri = os.environ.get("RATE_LIMIT_URI", "async+memory://")
strategy = os.environ.get("RATE_LIMIT_STRATEGY", "fixed-window")
options: dict[str, str | float | bool] = {}

if uri.startswith(("async+redis://", "async+rediss://", "async+redis+unix://")):
    options = {
        "key_prefix": os.environ.get("RATE_LIMIT_PREFIX", "orders-demo"),
        "socket_connect_timeout": 1.0,
        "socket_timeout": 0.5,
    }
    if uri.startswith("async+rediss://"):
        options["ssl_ca_certs"] = os.environ["REDIS_CA_FILE"]
        options["ssl_cert_reqs"] = "required"
        options["ssl_check_hostname"] = True

limiter = Limiter(storage_uri=uri, storage_options=options or None, strategy=strategy)
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> list[str]:
    return []
```

### In-memory storage

Run `python -m uvicorn app:app` with no environment variables. Each process
has separate counters. They reset when its lifespan ends. Memory storage
takes no `storage_options`.

### Redis

Use one of these commands with a server that already listens on the chosen
transport. Replace the TLS hostname and CA path or the Unix socket path with
your environment's values.

```sh
RATE_LIMIT_URI=async+redis://127.0.0.1:6379/0 python -m uvicorn app:app

RATE_LIMIT_URI=async+rediss://redis.example.com:6380/0 \
    REDIS_CA_FILE=/path/to/ca.pem python -m uvicorn app:app

RATE_LIMIT_URI='async+redis+unix:///run/redis/redis.sock?db=0' python -m uvicorn app:app
```

The TCP and TLS URIs select database `0` in the URL path. The Unix socket URI
selects it with `?db=0`. For an authenticated server, provide the URI through
your application's secret configuration, with any username or password
URL-encoded. Keep TLS certificate and hostname verification enabled.

The example sets `key_prefix` to separate the app's Redis keys from other
applications, `socket_connect_timeout` to bound connection setup, and
`socket_timeout` to bound socket operations. The default Redis prefix is
`LIMITS`. You can also set `storage_options={"wrap_exceptions": True}` to
enable upstream error wrapping, or specify `"implementation": "redispy"`,
which is already the default for this URI API. For a different Redis client
implementation or an existing connection pool, pass a storage instance
instead.

See [async Redis storage in limits](https://limits.readthedocs.io/en/stable/api.html#limits.aio.storage.RedisStorage)
for the backend options and
[redis-py connection options](https://redis.readthedocs.io/en/v7.2.1/connections.html)
for the connection parameters, including TLS and pooling.

To run multiple workers against one quota, add `--workers 2` to the Redis
command. All workers should use the same Redis database, key prefix,
strategy, and rule configuration.

### Select a strategy

The strategy applies to every rule made by a limiter. Memory and Redis
support each choice below.

| Value of `RATE_LIMIT_STRATEGY` | How the app counts quota |
| --- | --- |
| `fixed-window` (default) | The first request starts a window of fixed duration. Capacity returns when that window expires. |
| `moving-window` | Tracks timestamps to enforce the quota across the most recent full window. |
| `sliding-window-counter` | Estimates recent usage by weighting the previous window's count and adding the current window's count. |

```sh
RATE_LIMIT_STRATEGY=fixed-window python -m uvicorn app:app
RATE_LIMIT_STRATEGY=moving-window python -m uvicorn app:app
RATE_LIMIT_STRATEGY=sliding-window-counter python -m uvicorn app:app
```

Run one command at a time. To check a fresh counter, make the following
requests in quick succession. Expect `200`, `200`, then `429`. To rerun the
example with Redis, wait for the quota window to expire or set a fresh
`RATE_LIMIT_PREFIX`.

```sh
for i in 1 2 3; do
    curl -i http://127.0.0.1:8000/orders
done
```

For different strategies in one app, create separate limiters and
[enter each lifespan](quickstart.md#use-an-existing-lifespan). Strategy names
separate their counters, even in the same storage with the same prefix.
See [how the strategies count](https://limits.readthedocs.io/en/stable/strategies.html)
for timing examples.

## Supply storage your application owns

Use `storage=` with an instance of `limits.aio.storage.Storage`. Set any
options and prefix on the instance. The chosen strategy must be supported by
that backend. See [async backends in limits](https://limits.readthedocs.io/en/stable/async.html)
for other storage implementations and their requirements.

This app uses an application-owned Redis connection pool. Save it as
`app.py` and install the Redis extra. The application closes the pool after
the limiter stops.

```python title="app.py"
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from limits.aio.storage import RedisStorage
from redis.asyncio import ConnectionPool

from fastapi_ratelimits import Limiter

uri = os.environ["REDIS_URL"]
pool = ConnectionPool.from_url(uri)
storage = RedisStorage(
    f"async+{uri}",
    implementation="redispy",
    connection_pool=pool,
    key_prefix="owned-orders-demo",
)
limiter = Limiter(storage=storage)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        async with limiter.lifespan(app):
            yield
    finally:
        await pool.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> list[str]:
    return []
```

Set `REDIS_URL` to a reachable `redis://` or `rediss://` URL and start the app.

```sh
REDIS_URL=redis://127.0.0.1:6379/0 python -m uvicorn app:app
```

With a fresh counter, the three earlier requests return `200`, `200`, and
`429` again.
