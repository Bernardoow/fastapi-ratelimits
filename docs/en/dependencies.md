# FastAPI dependencies

`limiter.limit(...)` builds a dependency that checks the quota before FastAPI
calls the endpoint. Attach it with `Depends` at the point where you want the
rule to apply.

| Where to declare it | Which operations run the rule |
| --- | --- |
| `@app.get(..., dependencies=[Depends(rule)])` | That operation. The same pattern works with a router's route decorator. |
| `Annotated[None, Depends(rule)]` | The operation with that parameter. A successful check returns `None`. |
| `APIRouter(dependencies=[Depends(rule)])` | The router's operations, wherever that router is included. |
| `app.include_router(router, dependencies=[Depends(rule)])` | The operations registered by that particular inclusion. |
| `FastAPI(dependencies=[Depends(rule)])` | All FastAPI HTTP operations in the app, including its routers. |

## Apply rules at each level

With the [quickstart installation](quickstart.md), save this app as `app.py` and
run `python -m uvicorn app:app`.

```python title="app.py"
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
app = FastAPI(
    lifespan=limiter.lifespan,
    dependencies=[Depends(limiter.limit("10/minute"))],
)


@app.get("/ping")
async def ping() -> dict[str, bool]:
    return {"ok": True}


@app.get("/orders", dependencies=[Depends(limiter.limit("1/minute"))])
async def orders() -> list[str]:
    return []


@app.get("/reports")
async def reports(_quota: Annotated[None, Depends(limiter.limit("1/minute"))]) -> list[str]:
    return []


exports = APIRouter(
    prefix="/exports",
    dependencies=[Depends(limiter.limit("2/minute", group="exports"))],
)


@exports.get("/csv")
async def csv() -> dict[str, str]:
    return {"format": "csv"}


@exports.get("/pdf")
async def pdf() -> dict[str, str]:
    return {"format": "pdf"}


app.include_router(exports)

catalog = APIRouter()


@catalog.get("/a")
@catalog.get("/b")
async def catalog_entry() -> dict[str, bool]:
    return {"ok": True}


app.include_router(
    catalog, prefix="/internal", dependencies=[Depends(limiter.limit("1/minute"))]
)
app.include_router(catalog, prefix="/public")
```

On a fresh server, send each sequence from the same client, in the order shown.

| Requests | Expected statuses | What to observe |
| --- | --- | --- |
| `GET /ping` twice | `200`, `200` | This operation uses the app-level rule. |
| `GET /orders` twice | `200`, `429` | The decorator adds a stricter rule to that operation. |
| `GET /reports` twice | `200`, `429` | The parameter checks the rule before the handler. |
| `GET /exports/csv`, `GET /exports/pdf`, `GET /exports/csv` | `200`, `200`, `429` | The router rule shares one quota between export operations via `group`. |
| `GET /internal/a`, `GET /internal/b`, `GET /internal/a`, `GET /public/a` | `200`, `200`, `429`, `200` | Only the internal inclusion adds the one-request rule. Its operations have separate counters. |

For example, to see the shared export quota:

```sh
curl -i http://127.0.0.1:8000/exports/csv
curl -i http://127.0.0.1:8000/exports/pdf
curl -i http://127.0.0.1:8000/exports/csv
```

An app or router dependency controls **where the rule runs**. By default each
operation gets its own counter. Use [`group`](rules.md#share-a-quota-and-resolve-values-per-request)
when the operations should spend from the same quota. A denial from any
applicable rule returns `429` with `Retry-After`.

FastAPI normally reuses a dependency's result within a request. Reusing the
same callable returned by `limiter.limit(...)` at two levels can therefore
run the check only once. To enforce two windows on one operation, create two
rules, for example `limiter.limit("2/second")` and
`limiter.limit("10/minute")`.

## Use dependencies inside a rule

FastAPI resolves the client key, route ID, dynamic quota, and dynamic cost as
dependencies. They can read request parameters, receive values from other
dependencies, and use FastAPI's normal caching and overrides. See the
[account and export example](rules.md#share-a-quota-and-resolve-values-per-request).
