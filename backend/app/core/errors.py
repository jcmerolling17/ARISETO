from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """A business error returned as {"detail": {"code": "<error_code>"}} (Section 6)."""

    def __init__(self, status_code: int, code: str, headers: dict[str, str] | None = None):
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.headers = headers


async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code}},
        headers=exc.headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
