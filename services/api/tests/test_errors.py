from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.testclient import TestClient

from api.middleware.errors import (
    PROBLEM_MEDIA_TYPE,
    ProblemDetailsMiddleware,
    ProblemType,
    install_problem_handlers,
)


def _app() -> FastAPI:
    app = FastAPI()
    install_problem_handlers(app)
    app.add_middleware(ProblemDetailsMiddleware)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password: never-return-this")

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise HTTPException(status_code=403, detail="internal policy explanation")

    @app.get("/validate")
    async def validate(required_number: int = Query()) -> dict[str, int]:
        return {"required_number": required_number}

    return app


def test_unhandled_exception_never_reflects_the_exception_message() -> None:
    response = TestClient(_app(), raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json() == {
        "type": ProblemType.unexpected_error.uri,
        "title": "Unexpected server error",
        "status": 500,
        "detail": "The service could not complete the request.",
        "instance": "/boom",
    }
    assert "database password" not in response.text


def test_http_exception_detail_is_replaced_with_stable_problem() -> None:
    response = TestClient(_app()).get("/forbidden")

    assert response.status_code == 403
    assert response.json()["type"] == ProblemType.forbidden.uri
    assert "internal policy explanation" not in response.text


def test_validation_problem_does_not_echo_invalid_input() -> None:
    response = TestClient(_app()).get(
        "/validate", params={"required_number": "not-a-number"}
    )

    assert response.status_code == 422
    assert response.json()["type"] == ProblemType.invalid_request.uri
    assert "not-a-number" not in response.text
