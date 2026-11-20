.PHONY: setup

setup:
	uv sync --directory . --project . --python 3.11 --frozen --extra redis
	uv run --directory . --project . --python 3.11 --no-sync pre-commit install --install-hooks
