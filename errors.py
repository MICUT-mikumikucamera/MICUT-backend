import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CODES = json.loads(Path("contracts/error_codes.json").read_text(encoding="utf-8"))["codes"]


class AppError(Exception):
    def __init__(self, code: str):
        self.code = code


def failed(code: str) -> JSONResponse:
    info = CODES[code]
    error = {"code": code, "message": info["message"], "retryable": info["retryable"]}
    return JSONResponse({"status": "failed", "error": error}, status_code=info["http"])


def register(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    def handle_app_error(request: Request, exc: AppError):
        return failed(exc.code)

    @app.exception_handler(RequestValidationError)
    def handle_invalid_request(request: Request, exc: RequestValidationError):
        return failed("INVALID_REQUEST")

    @app.exception_handler(Exception)
    def handle_unexpected(request: Request, exc: Exception):
        return failed("INTERNAL_ERROR")