# Development

## Set up a clone

With Git, Make, and `uv` available, run `make setup` from the repository root.
It prepares the Python 3.11 environment with the development dependencies and
Redis client from `uv.lock`, then installs the Git hooks for the clone.

The hooks check the working-tree project metadata and lockfile before commits and
automatic merge commits. If the lockfile is out of date, run `uv lock`, stage
the updated `uv.lock` with the relevant `pyproject.toml` changes, and retry the
commit.

## Run tests and code checks

```sh
uv run --python 3.11 --no-sync pytest -m 'not redis'
uv run --python 3.11 --no-sync mypy
uv run --python 3.11 --no-sync ruff check .
```

## Run Redis integration tests

Use a disposable local Redis server. Set `RATELIMITS_TEST_REDIS_URL` to a
client URI without the `async+` prefix.

```sh
RATELIMITS_TEST_REDIS_URL=redis://127.0.0.1:6379/0 uv run --python 3.11 --no-sync pytest
```

## Build the documentation

Build both editions in the order shown. The Portuguese build writes to
`site/pt-br/` under the English build's output.

```sh
uv run --locked --no-dev --group docs zensical build --clean --strict
uv run --locked --no-dev --group docs zensical build --clean --strict --config-file zensical.pt-br.toml
```
