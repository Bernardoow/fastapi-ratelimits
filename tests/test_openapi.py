import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import HTMLResponse

from fastapi_ratelimits import Limiter, rate_limit_responses


class TestRateLimitResponses:
    @pytest.mark.parametrize("at_router", [False, True], ids=["operation", "router"])
    def test_documents_json_errors_for_html_endpoint(self, *, at_router: bool) -> None:
        limiter = Limiter(storage_uri="async+memory://")
        dependencies = [Depends(limiter.limit("2/minute"))]
        app = FastAPI()

        async def orders() -> HTMLResponse:
            return HTMLResponse("<p>Orders</p>")

        if at_router:
            router = APIRouter(dependencies=dependencies, responses=rate_limit_responses())
            router.get("/orders", response_class=HTMLResponse)(orders)
            app.include_router(router)
        else:
            app.get(
                "/orders",
                dependencies=dependencies,
                response_class=HTMLResponse,
                responses=rate_limit_responses(),
            )(orders)

        app.get("/implicit", dependencies=dependencies, response_class=HTMLResponse)(orders)

        paths = app.openapi()["paths"]
        assert set(paths["/implicit"]["get"]["responses"]) == {"200"}
        responses = paths["/orders"]["get"]["responses"]
        assert set(responses) == {"200", "429", "503"}
        assert set(responses["200"]["content"]) == {"text/html"}

        for status, detail in (
            ("429", "Rate limit exceeded"),
            ("503", "Rate limit storage unavailable"),
        ):
            assert responses[status]["content"] == {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                        "required": ["detail"],
                    },
                    "example": {"detail": detail},
                },
            }
        retry_after = responses["429"]["headers"]["Retry-After"]
        assert retry_after["required"] is True
        assert retry_after["schema"] == {"type": "integer", "minimum": 1}
        assert "headers" not in responses["503"]

    @pytest.mark.parametrize("status", [429, 503])
    def test_overrides_only_the_requested_body_schema(self, *, status: int) -> None:
        app = FastAPI()
        schema = {
            "type": "object",
            "properties": {"error": {"type": "string"}},
            "required": ["error"],
        }

        @app.get("/default", responses=rate_limit_responses())
        @app.get("/custom", responses=rate_limit_responses(**{f"schema_{status}": schema}))
        async def orders() -> list[str]:
            return []

        paths = app.openapi()["paths"]
        default = paths["/default"]["get"]["responses"]
        custom = paths["/custom"]["get"]["responses"]
        assert custom["429"]["headers"] == default["429"]["headers"]
        assert custom[str(status)]["content"] == {"application/json": {"schema": schema}}
        other_status = "503" if status == 429 else "429"
        assert custom[other_status] == default[other_status]
