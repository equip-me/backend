from typing import Any, cast

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        code: str = "",
        params: dict[str, str | int] | None = None,
    ) -> None:
        self.detail = detail
        self.code = code
        self.params: dict[str, str | int] = params or {}
        super().__init__(detail)


class NotFoundError(AppError):
    pass


class AlreadyExistsError(AppError):
    pass


class InvalidCredentialsError(AppError):
    pass


class PermissionDeniedError(AppError):
    pass


class AccountSuspendedError(AppError):
    pass


class AppValidationError(AppError):
    pass


class IDGenerationError(AppError):
    pass


class ExternalServiceError(AppError):
    pass


_STATUS_MAP: dict[type[AppError], int] = {
    NotFoundError: 404,
    AlreadyExistsError: 409,
    InvalidCredentialsError: 401,
    PermissionDeniedError: 403,
    AccountSuspendedError: 403,
    AppValidationError: 400,
    IDGenerationError: 500,
    ExternalServiceError: 502,
}


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    app_exc = cast("AppError", exc)
    status_code = _STATUS_MAP.get(type(app_exc), 500)
    return JSONResponse(
        status_code=status_code,
        content={"code": app_exc.code, "detail": app_exc.detail, "params": app_exc.params},
    )


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    val_exc = cast("RequestValidationError", exc)
    errors: list[dict[str, Any]] = []
    for err in val_exc.errors():
        loc = err.get("loc", ())
        field = ".".join(str(part) for part in loc)
        errors.append(
            {
                "field": field,
                "code": f"validation.{err.get('type', 'unknown')}",
                "detail": err.get("msg", ""),
                "params": {},
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation.request_invalid",
            "detail": "Request validation failed",
            "params": {},
            "errors": errors,
        },
    )
