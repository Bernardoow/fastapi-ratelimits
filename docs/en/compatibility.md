# Compatibility

fastapi-ratelimits requires Python 3.11 or newer, FastAPI 0.95.1 or newer, and
`limits>=5.8,<6`. The FastAPI requirement lets you keep an older version that
works with your application's Python and dependencies. When the current stable
FastAPI release raises its minimum Python version, the next fastapi-ratelimits
release adopts that minimum.

## Existing FastAPI applications

Keep a Pydantic version that works with your FastAPI version. On Python 3.11,
FastAPI 0.100.0 passed the suite with Pydantic 2.0.3. With Pydantic 2.14.3,
that FastAPI version can fail while registering routes that use
`Annotated[str, Header()]`. It expects the header's `in_` attribute, which the
generic `FieldInfo` from Pydantic lacks.

FastAPI fixed a request-parameter denial-of-service vulnerability in 0.163.2.
Check whether your version is affected in the [FastAPI security advisory](https://github.com/fastapi/fastapi/security/advisories/GHSA-f56c-v883-vx8r).

## How compatibility is tested

GitHub Actions runs the suite with Redis on Python 3.11 through 3.15. On each
Python version, it uses the development lockfile, the minimum declared runtime
dependencies, and the latest compatible versions. The matrix runs on pull
requests, on pushes to `main`, and before publication to PyPI.
