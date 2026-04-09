from tortoise.expressions import Q

from app.core.enums import MediaOwnerType, UserRole
from app.core.exceptions import (
    AccountSuspendedError,
    AlreadyExistsError,
    InvalidCredentialsError,
    NotFoundError,
)
from app.core.identifiers import create_with_short_id
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.core.security import create_access_token, hash_password, verify_password
from app.media import service as media_service
from app.media.storage import StorageClient
from app.observability.events import emit_event
from app.observability.metrics import auth_attempts
from app.observability.tracing import traced
from app.users.models import User
from app.users.schemas import AdminRoleUpdate, PrivilegeUpdate, TokenResponse, UserCreate, UserRead, UserUpdate


@traced
async def register(data: UserCreate) -> TokenResponse:
    existing = await User.filter(email=data.email).exists()
    if existing:
        raise AlreadyExistsError("User with this email already exists", code="users.email_taken")
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
        raise InvalidCredentialsError("Incorrect username or password", code="auth.incorrect_password")
    if not verify_password(password, user.hashed_password):
        auth_attempts.add(1, {"result": "failed"})
        emit_event("user.auth_failed")
        raise InvalidCredentialsError("Incorrect username or password", code="auth.incorrect_password")
    if user.role == UserRole.SUSPENDED:
        auth_attempts.add(1, {"result": "suspended"})
        raise AccountSuspendedError("Account suspended", code="auth.account_suspended")
    token = create_access_token(user.id)
    auth_attempts.add(1, {"result": "success"})
    emit_event("user.authenticated", user_id=user.id)
    return TokenResponse(access_token=token)


@traced
async def get_by_id(user_id: str) -> User:
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise NotFoundError("User not found", code="users.not_found")
    return user


@traced
async def update_me(user: User, data: UserUpdate, storage: StorageClient) -> User:
    update_data = data.model_dump(exclude_unset=True, exclude={"password", "new_password", "profile_photo_id"})

    if data.email is not None and data.email != user.email:
        existing = await User.filter(email=data.email).exists()
        if existing:
            raise AlreadyExistsError("User with this email already exists", code="users.email_taken")

    if data.password and data.new_password:
        if not verify_password(data.password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect username or password", code="auth.incorrect_password")
        update_data["hashed_password"] = hash_password(data.new_password)

    for field, value in update_data.items():
        setattr(user, field, value)
    await user.save()

    if "profile_photo_id" in data.model_fields_set:
        await media_service.attach_profile_photo(
            data.profile_photo_id,
            MediaOwnerType.USER,
            user.id,
            user,
            storage,
        )

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


@traced
async def list_users(
    params: CursorParams,
    storage: StorageClient,
    ordering: tuple[str, ...],
    search: str | None = None,
    role: UserRole | None = None,
) -> PaginatedResponse[UserRead]:
    qs = User.all()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(surname__icontains=search) | Q(email__icontains=search),
        )
    if role:
        qs = qs.filter(role=role)

    items, next_cursor, has_more = await paginate(qs, params, ordering=ordering)

    user_reads: list[UserRead] = []
    for user in items:
        photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
        user_read = UserRead.model_validate(user)
        user_read.profile_photo = photo
        user_reads.append(user_read)

    return PaginatedResponse(items=user_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def search_users_by_email(
    email: str,
    limit: int,
    storage: StorageClient,
) -> list[UserRead]:
    users = await User.filter(email__icontains=email).exclude(role=UserRole.SUSPENDED).order_by("email").limit(limit)
    result: list[UserRead] = []
    for user in users:
        photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
        user_read = UserRead.model_validate(user)
        user_read.profile_photo = photo
        result.append(user_read)
    return result
