# fastapi-ratelimits

Asynchronous rate limiting for HTTP APIs built with FastAPI. Define limits as
FastAPI dependencies and share counters across workers with Redis. Requires
Python 3.11 or newer.

[English documentation](https://bernardoow.github.io/fastapi-ratelimits/)
· [Documentação em português](https://bernardoow.github.io/fastapi-ratelimits/pt-br/)

## Get started

From the repository checkout, install the package with `pip install .`.
Use `pip install '.[redis]'` for Redis support.

```python
from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders():
    return {"orders": []}
```

In this single-process example, each client IP gets two requests per minute to `GET /orders`. The
[Quickstart](https://bernardoow.github.io/fastapi-ratelimits/quickstart/) shows
how to run the app and see the `429` response.

## Development

```sh
uv sync --python 3.11 --extra redis
uv run --python 3.11 pytest -m 'not redis'
uv run --python 3.11 mypy
uv run --python 3.11 ruff check .
```

For Redis integration tests, use a disposable local server. Set
`RATELIMITS_TEST_REDIS_URL` to a client URI without the `async+` prefix.

```sh
RATELIMITS_TEST_REDIS_URL=redis://127.0.0.1:6379/0 uv run --python 3.11 --extra redis pytest
```

Build both documentation editions in this order. The Portuguese build writes
to `site/pt-br/` under the English build's output.

```sh
uv run --locked --no-dev --group docs zensical build --clean --strict
uv run --locked --no-dev --group docs zensical build --clean --strict --config-file zensical.pt-br.toml
```

Set **Settings → Pages → Source** to **GitHub Actions** on the repository to
enable automatic publication from `main`.
