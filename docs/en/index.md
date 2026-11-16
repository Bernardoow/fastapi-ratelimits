# fastapi-ratelimits

Control how often clients can call your FastAPI endpoints. Add rate limits as
FastAPI dependencies and store counters in memory or Redis using the asynchronous
strategies from [limits](https://limits.readthedocs.io/en/stable/async.html).
Requires Python 3.11 or newer.

[Set up your first limit](quickstart.md){ .md-button .md-button--primary }

- [FastAPI dependencies](dependencies.md) shows where to declare `Depends`
  for operations, routers, and the whole app.
- [Rules and identity](rules.md) explains quotas per route, shared quotas, and
  dynamic costs.
- [Storage and strategies](storage.md) covers Redis across workers and choosing
  a rate limit strategy.
- [Responses and headers](responses.md) shows how to handle `429` and `503`
  and expose quota information to clients.
- [API reference](reference.md) documents the public Python interface.
