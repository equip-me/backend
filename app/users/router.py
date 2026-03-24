from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user, require_platform_admin
from app.users import service
from app.users.models import User
from app.users.schemas import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    UserRoleUpdate,
    UserUpdate,
)

router = APIRouter()


@router.post("/users/", response_model=TokenResponse)
async def register(data: UserCreate) -> TokenResponse:
    return await service.register(data)


@router.post("/users/token", response_model=TokenResponse)
async def login(data: LoginRequest) -> TokenResponse:
    return await service.authenticate(data.email, data.password)


@router.get("/users/me", response_model=UserRead)
async def get_me(user: Annotated[User, Depends(require_active_user)]) -> User:
    return user


@router.patch("/users/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    user: Annotated[User, Depends(require_active_user)],
) -> User:
    return await service.update_me(user, data)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(user_id: UUID) -> User:
    return await service.get_by_id(user_id)


@router.patch("/private/users/{user_id}/role", response_model=UserRead)
async def change_role(
    user_id: UUID,
    data: UserRoleUpdate,
    acting_user: Annotated[User, Depends(require_platform_admin)],
) -> User:
    return await service.change_role(user_id, data, acting_user)
