from copy import deepcopy
from typing import Any

from .exceptions import _RATE_LIMIT_EXCEEDED_DETAIL, _STORAGE_UNAVAILABLE_DETAIL


def rate_limit_responses(
    *,
    schema_429: dict[str, Any] | None = None,
    schema_503: dict[str, Any] | None = None,
) -> dict[int | str, dict[str, Any]]:
    """Return OpenAPI response metadata for FastAPI's `responses` argument.

    Args:
        schema_429: JSON Schema for a custom 429 response body.
        schema_503: JSON Schema for a custom 503 response body.

    Returns:
        Response entries for 429 and 503 with their JSON body schemas and the
        `Retry-After` header for 429. Each omitted schema uses the default body.
    """
    return {
        429: {
            "description": _RATE_LIMIT_EXCEEDED_DETAIL,
            "content": _error_content(schema=schema_429, detail=_RATE_LIMIT_EXCEEDED_DETAIL),
            "headers": {
                "Retry-After": {
                    "description": "Seconds to wait before retrying.",
                    "required": True,
                    "schema": {"type": "integer", "minimum": 1},
                },
            },
        },
        503: {
            "description": _STORAGE_UNAVAILABLE_DETAIL,
            "content": _error_content(schema=schema_503, detail=_STORAGE_UNAVAILABLE_DETAIL),
        },
    }


def _error_content(*, schema: dict[str, Any] | None, detail: str) -> dict[str, Any]:
    if schema is not None:
        return {"application/json": {"schema": deepcopy(schema)}}

    return {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {"detail": {"type": "string"}},
                "required": ["detail"],
            },
            "example": {"detail": detail},
        },
    }
