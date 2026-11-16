# Quickstart

Give each client IP two requests per minute to `GET /orders`. This example uses
in-memory storage and runs in one process.

## Install from the repository

Run the following commands in an active Python 3.11 or newer virtual environment.

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
async def orders():
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

If the app already has a lifespan function, enter `limiter.lifespan(app)`
inside it. Put the application's existing setup and cleanup around `yield`.

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with limiter.lifespan(app):
        yield


app = FastAPI(lifespan=lifespan)
```

Use `FastAPI(lifespan=lifespan)` in place of the original `FastAPI(...)` line,
before attaching routes. When you run multiple workers, use a
[shared Redis backend](storage.md#redis).
