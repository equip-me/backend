from app.core.enums import UserRole
from app.core.exceptions import (
    AccountSuspendedError,
    AlreadyExistsError,
    InvalidCredentialsError,
    NotFoundError,
)
from app.core.identifiers import create_with_short_id
from app.core.security import create_access_token, hash_password, verify_password
from app.observability.events import emit_event
from app.observability.metrics import auth_attempts
from app.observability.tracing import traced
from app.users.models import User
from app.users.schemas import AdminRoleUpdate, PrivilegeUpdate, TokenResponse, UserCreate, UserUpdate


@traced
async def register(data: UserCreate) -> TokenResponse:
    existing = await User.filter(email=data.email).exists()
    if existing:
        raise AlreadyExistsError("User with this email already exists")
    user = await create_with_short_id(
        User,
        email=data.email,
        hashed_password=hash_password(data.password),
        phone=data.phone,
        name=data.name,
        surname=data.surname,
        middle_name=data.middle_name,
    )
    token = create_access_token(user.id)
    emit_event("user.registered", user_id=user.id)
    return TokenResponse(access_token=token)


@traced
async def authenticate(email: str, password: str) -> TokenResponse:
    user = await User.get_or_none(email=email)
    if user is None:
        auth_attempts.add(1, {"result": "failed"})
        emit_event("user.auth_failed")
        raise InvalidCredentialsError("Incorrect username or password")
    if not verify_password(password, user.hashed_password):
        auth_attempts.add(1, {"result": "failed"})
        emit_event("user.auth_failed")
        raise InvalidCredentialsError("Incorrect username or password")
    if user.role == UserRole.SUSPENDED:
        auth_attempts.add(1, {"result": "suspended"})
        raise AccountSuspendedError("Account suspended")
    token = create_access_token(user.id)
    auth_attempts.add(1, {"result": "success"})
    emit_event("user.authenticated", user_id=user.id)
    return TokenResponse(access_token=token)


@traced
async def get_by_id(user_id: str) -> User:
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


@traced
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


@traced
async def change_user_role(user_id: str, data: AdminRoleUpdate) -> User:
    user = await get_by_id(user_id)
    user.role = data.role
    await user.save()
    return user


@traced
async def change_privilege(user_id: str, data: PrivilegeUpdate) -> User:
    user = await get_by_id(user_id)
    user.role = data.role
    await user.save()
    return user
