from uuid import UUID

from app.core.enums import UserRole
from app.core.exceptions import (
    AccountSuspendedError,
    AlreadyExistsError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.users.models import User
from app.users.schemas import TokenResponse, UserCreate, UserRoleUpdate, UserUpdate


async def register(data: UserCreate) -> TokenResponse:
    existing = await User.filter(email=data.email).exists()
    if existing:
        raise AlreadyExistsError("User with this email already exists")
    user = await User.create(
        email=data.email,
        hashed_password=hash_password(data.password),
        phone=data.phone,
        name=data.name,
        surname=data.surname,
        middle_name=data.middle_name,
    )
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


async def authenticate(email: str, password: str) -> TokenResponse:
    user = await User.get_or_none(email=email)
    if user is None:
        raise InvalidCredentialsError("Incorrect username or password")
    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError("Incorrect username or password")
    if user.role == UserRole.SUSPENDED:
        raise AccountSuspendedError("Account suspended")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


async def get_by_id(user_id: UUID) -> User:
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def update_me(user: User, data: UserUpdate) -> User:
    update_data = data.model_dump(exclude_unset=True, exclude={"password", "new_password"})

    if data.email is not None and data.email != user.email:
        existing = await User.filter(email=data.email).exists()
        if existing:
            raise AlreadyExistsError("User with this email already exists")

    if data.password and data.new_password:
        if not verify_password(data.password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect username or password")
        update_data["hashed_password"] = hash_password(data.new_password)

    for field, value in update_data.items():
        setattr(user, field, value)
    await user.save()
    return user


async def change_role(user_id: UUID, data: UserRoleUpdate, acting_user: User) -> User:
    if data.role in (UserRole.ADMIN, UserRole.OWNER) and acting_user.role != UserRole.OWNER:
        raise PermissionDeniedError("Only platform owner can assign admin or owner roles")
    user = await get_by_id(user_id)
    user.role = data.role
    await user.save()
    return user
