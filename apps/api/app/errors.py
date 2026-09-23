"""Standard error envelope: {error: {code, message, request_id}} — never leak stack traces."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.logging_config import request_id_ctx


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id_ctx.get() or None}},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")
