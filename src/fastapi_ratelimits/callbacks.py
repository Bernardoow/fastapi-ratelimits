import functools
import inspect
import warnings
from collections.abc import Callable
from typing import Any


class SynchronousCallbackWarning(UserWarning):
    """A configured callback uses a worker thread instead of native async I/O."""


def is_async_callable(callback: Callable[..., Any]) -> bool:
    while isinstance(callback, functools.partial):
        callback = callback.func
    return inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
        type(callback).__call__
    )


def warn_if_sync(callback: Callable[..., Any]) -> None:
    if not (
        is_async_callable(callback)
        or inspect.isasyncgenfunction(callback)
        or inspect.isasyncgenfunction(type(callback).__call__)
    ):
        warnings.warn(
            "A synchronous callback runs in a worker thread. Prefer async def with async I/O.",
            SynchronousCallbackWarning,
            stacklevel=3,
        )
