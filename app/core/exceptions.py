from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, detail: str) -> None:
        self.detail = detail
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


_STATUS_MAP: dict[type[AppError], int] = {
    NotFoundError: 404,
    AlreadyExistsError: 409,
    InvalidCredentialsError: 401,
    PermissionDeniedError: 403,
    AccountSuspendedError: 403,
    AppValidationError: 422,
}


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    status_code = _STATUS_MAP.get(type(exc), 500)
    return JSONResponse(status_code=status_code, content={"detail": exc.detail})
