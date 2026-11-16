from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, TypeVar
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from limits import RateLimitItem, parse_many
from limits.aio.storage import Storage
from limits.aio.strategies import STRATEGIES, RateLimiter
from limits.errors import StorageError

from .callbacks import warn_if_sync
from .defaults import default_route_id, key_by_ip
from .exceptions import RateLimitExceeded, StorageUnavailable
from .headers import RateLimitSnapshot, request_snapshots
from .storage import open_storage

T = TypeVar("T")
ValueProvider = Callable[..., T | Awaitable[T] | Iterator[T] | AsyncIterator[T]]
_STRATEGIES: Mapping[str, Callable[[Storage], RateLimiter]] = STRATEGIES
_STRATEGY_METHODS = {
    "moving-window": ("acquire_entry", "get_moving_window"),
    "sliding-window-counter": ("acquire_sliding_window_entry", "get_sliding_window"),
}


def _resolve_through_fastapi(source: T | ValueProvider[T]) -> ValueProvider[T]:
    if callable(source):
        return source

    async def constant() -> T:
        return source

    return constant


def _parse_rule(value: str) -> RateLimitItem:
    if not isinstance(value, str):
        raise ValueError("A limit must be a rate limit string")
    items = parse_many(value)
    if len(items) != 1 or items[0].amount <= 0 or items[0].multiples <= 0:
        raise ValueError("Provide one rate limit with a positive amount and window per rule")
    return items[0]


def _validate_cost(cost: int) -> None:
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 1:
        raise ValueError("cost must be a positive integer")


class Limiter:
    """Configure an asynchronous quota strategy and create FastAPI dependencies."""

    def __init__(
        self,
        *,
        storage_uri: str | None = None,
        storage: Storage | None = None,
        storage_options: Mapping[str, Any] | None = None,
        strategy: str = "fixed-window",
        key_func: ValueProvider[str] = key_by_ip,
        route_id_func: ValueProvider[str] = default_route_id,
    ) -> None:
        if (storage_uri is None) == (storage is None):
            raise ValueError("Configure exactly one of storage_uri or storage")
        if storage_uri is not None and not storage_uri.startswith("async+"):
            raise ValueError("storage_uri must select an async+ storage")
        if storage is not None and not isinstance(storage, Storage):
            raise TypeError("storage must be an asynchronous limits storage")
        if storage is not None and storage_options is not None:
            raise ValueError("Configure storage_options only with storage_uri")
        if strategy not in _STRATEGIES:
            raise ValueError(f"Unknown rate limit strategy: {strategy!r}")
        self._storage_uri = storage_uri
        self._storage = storage
        self._storage_options = dict(storage_options or {})
        self._strategy_name = strategy
        warn_if_sync(key_func)
        warn_if_sync(route_id_func)
        self._key_func = key_func
        self._route_id_func = route_id_func
        self._active: dict[FastAPI, RateLimiter] = {}

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """Start the limiter for an application and release any resources it owns."""
        if app in self._active:
            raise RuntimeError("Limiter.lifespan is already active for this application")
        async with AsyncExitStack() as stack:
            storage = self._storage
            if storage is None:
                assert self._storage_uri is not None
                storage = await stack.enter_async_context(
                    open_storage(uri=self._storage_uri, options=self._storage_options)
                )
            if any(
                not callable(getattr(storage, method, None))
                for method in _STRATEGY_METHODS.get(self._strategy_name, ())
            ):
                raise ValueError(
                    f"{type(storage).__name__} does not support the {self._strategy_name} strategy"
                )
            self._active[app] = _STRATEGIES[self._strategy_name](storage)
            try:
                yield
            finally:
                del self._active[app]

    def limit(
        self,
        value: str | ValueProvider[str],
        *,
        key_func: ValueProvider[str] | None = None,
        group: str | None = None,
        cost: int | ValueProvider[int] = 1,
    ) -> Callable[..., Coroutine[Any, Any, None]]:
        """Build one rule for Depends, scoped to the route or an explicit group."""
        static_item = None if callable(value) else _parse_rule(value)
        if not callable(cost):
            _validate_cost(cost)
        if group is not None and (not isinstance(group, str) or not group):
            raise ValueError("group must be a nonempty string")

        for provider in (key_func, value, cost):
            if callable(provider):
                warn_if_sync(provider)
        key_dependency = self._key_func if key_func is None else key_func
        scope_dependency = (
            self._route_id_func if group is None else _resolve_through_fastapi(group)
        )
        value_dependency: ValueProvider[str] = _resolve_through_fastapi(value)
        cost_dependency: ValueProvider[int] = _resolve_through_fastapi(cost)
        scope_type = "route" if group is None else "group"

        async def check(
            request: Request,
            *,
            key: str = Depends(key_dependency),
            scope: str = Depends(scope_dependency),
            resolved_limit: str = Depends(value_dependency),
            resolved_cost: int = Depends(cost_dependency),
        ) -> None:
            if not isinstance(key, str) or not key:
                raise ValueError("key_func must return a nonempty string")
            if not isinstance(scope, str) or not scope:
                raise ValueError("route_id_func must return a nonempty string")
            item = static_item if static_item is not None else _parse_rule(resolved_limit)
            _validate_cost(resolved_cost)
            identifiers = (
                self._strategy_name,
                scope_type,
                quote(scope, safe=""),
                quote(key, safe=""),
            )
            strategy = self._active.get(request.app)
            if strategy is None:
                raise RuntimeError("Use Limiter.lifespan before serving requests")
            backend_errors = strategy.storage.base_exceptions
            if isinstance(backend_errors, type):
                backend_errors = (backend_errors,)
            failures: tuple[type[Exception], ...] = (
                StorageError,
                TimeoutError,
                ConnectionError,
                *backend_errors,
            )
            snapshots = request_snapshots(scope=request.scope)
            try:
                admitted = await strategy.hit(item, *identifiers, cost=resolved_cost)
                if admitted and snapshots is None:
                    return
                stats = await strategy.get_window_stats(item, *identifiers)
            except failures as exc:
                raise StorageUnavailable() from exc
            if not admitted:
                raise RateLimitExceeded(
                    limit=item, reset_at=stats.reset_time, cost=resolved_cost, scope=scope
                )
            if snapshots is not None:
                snapshots.append(
                    RateLimitSnapshot(
                        limit=item.amount,
                        remaining=stats.remaining,
                        reset_at=stats.reset_time,
                        cost=resolved_cost,
                        scope=scope,
                        shared=group is not None,
                    )
                )

        return check
