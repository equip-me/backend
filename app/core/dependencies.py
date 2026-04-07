from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.enums import UserRole
from app.core.exceptions import (
    AccountSuspendedError,
    InvalidCredentialsError,
    PermissionDeniedError,
)
from app.core.security import decode_access_token
from app.users.models import User

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise InvalidCredentialsError("Could not validate credentials", code="auth.invalid_credentials")
    try:
        subject = decode_access_token(credentials.credentials)
    except ValueError as e:
        raise InvalidCredentialsError("Could not validate credentials", code="auth.invalid_credentials") from e
    user = await User.get_or_none(id=subject)
    if user is None:
        raise InvalidCredentialsError("Could not validate credentials", code="auth.invalid_credentials")
    return user


async def require_active_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role == UserRole.SUSPENDED:
        raise AccountSuspendedError("Account suspended", code="auth.account_suspended")
    return user


async def require_platform_admin(
    user: Annotated[User, Depends(require_active_user)],
) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise PermissionDeniedError("Platform admin access required", code="org.platform_admin_required")
    return user


async def require_platform_owner(
    user: Annotated[User, Depends(require_active_user)],
) -> User:
    if user.role != UserRole.OWNER:
        raise PermissionDeniedError("Platform owner access required", code="org.platform_owner_required")
    return user
