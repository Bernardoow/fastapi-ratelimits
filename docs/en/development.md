# Development

Run these commands with `uv` from the repository root.

## Run tests and code checks

```sh
uv sync --python 3.11 --extra redis
uv run --python 3.11 pytest -m 'not redis'
uv run --python 3.11 mypy
uv run --python 3.11 ruff check .
```

## Run Redis integration tests

Use a disposable local Redis server. Set `RATELIMITS_TEST_REDIS_URL` to a
client URI without the `async+` prefix.

```sh
RATELIMITS_TEST_REDIS_URL=redis://127.0.0.1:6379/0 uv run --python 3.11 --extra redis pytest
```

## Build the documentation

Build both editions in the order shown. The Portuguese build writes to
`site/pt-br/` under the English build's output.

```sh
uv run --locked --no-dev --group docs zensical build --clean --strict
uv run --locked --no-dev --group docs zensical build --clean --strict --config-file zensical.pt-br.toml
```
