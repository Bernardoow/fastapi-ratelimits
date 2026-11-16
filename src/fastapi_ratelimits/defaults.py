from fastapi import Request
from fastapi.routing import APIRoute


async def key_by_ip(request: Request) -> str:
    if request.client is None:
        raise ValueError("The request has no client address; configure a key_func")
    return request.client.host


async def default_route_id(request: Request) -> str:
    route = request.scope.get("route")
    # FastAPI >=0.163 keeps include-specific IDs in an effective route context.
    context = request.scope.get("fastapi", {}).get("effective_route_context")
    if context is not None and context.original_route is route:
        return str(context.operation_id or context.unique_id)
    if isinstance(route, APIRoute):
        return route.operation_id or route.unique_id
    raise ValueError("Rate limiting requires a FastAPI HTTP route")
