# Storage and strategies

Choose one storage source for `Limiter`. With `storage_uri`, the limiter
creates and closes its own storage. Use `redis_client` to share the connection
pool of your application's async Redis client, or `storage` to supply a
configured async storage instance. The application manages resources it supplies.

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
implementation, pass a storage instance.

See [async Redis storage in limits](https://limits.readthedocs.io/en/stable/api.html#limits.aio.storage.RedisStorage)
for the backend options and
[redis-py connection options](https://redis.readthedocs.io/en/v7.2.1/connections.html)
for the connection parameters, including TLS and pooling.

Redis-py can reconnect on a later command. If the application retries a
startup probe, configure connection and socket timeouts and bound the number
of attempts. Retrying `PING` preserves quota counters. Retrying a quota
command can apply the write again if Redis executed it and the response was lost.

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

## Check storage readiness

Set `check_storage_on_startup=True` on `Limiter` to check the configured
storage during the limiter's lifespan, before the app serves requests. This
option works with every storage source and defaults to `False`. Startup fails
with `StorageStartupError` if the check returns `False` or raises a recognized
storage error. In the latter case, the original exception is available as the
cause.

```python
from fastapi import FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+redis://localhost:6379/0", check_storage_on_startup=True)
app = FastAPI(lifespan=limiter.lifespan)
```

Import `StorageStartupError` from `fastapi_ratelimits` to catch an error from
this startup check.

For a readiness probe or your own startup policy, call
`await limiter.check_storage(app)` during that application's active limiter
lifespan. The method returns the result of `Storage.check()` and propagates
exceptions from the backend. Calling it without an active limiter lifespan
for that app raises `RuntimeError`.

On Redis, the check uses `PING` and preserves quota counters. A successful
check confirms that Redis responded at that moment. Evaluating quota rules
also depends on the commands used by each strategy. The in-memory storage
returns `True`.

## Share your application's Redis client

If your app already has a `redis.asyncio.Redis` instance named `client`,
pass it directly to the limiter. The limiter uses the client's existing
pool. The application closes the client and its pool after the limiter exits.

```python
from fastapi_ratelimits import Limiter

limiter = Limiter(redis_client=client, storage_options={"key_prefix": "orders"})
```

The default key prefix is `LIMITS`. Set `key_prefix` to isolate quotas for
apps sharing a database. Configure connection settings such as
`socket_timeout` when creating the client or pool. Passing connection
settings in `storage_options` with `redis_client` raises a configuration error.

### Create the Redis client at startup

If you declare routes before creating the client, pass a synchronous
function that returns the application's client. The limiter calls it once
on each entry to `limiter.lifespan(app)`. This example sets `app.state.redis`
before entering the limiter's lifespan. The outer context closes the Redis
client and its pool after the limiter exits.

```python title="app.py"
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from redis.asyncio import Redis

from fastapi_ratelimits import Limiter

limiter = Limiter(redis_client=lambda app: app.state.redis)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with Redis.from_url(os.environ["REDIS_URL"], socket_timeout=0.5) as client:
        app.state.redis = client
        async with limiter.lifespan(app):
            yield


app = FastAPI(lifespan=lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> list[str]:
    return []
```

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
