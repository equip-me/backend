from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.core.enums import MediaOwnerType
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service as org_service
from app.organizations.schemas import OrganizationRead
from app.users import service
from app.users.models import User
from app.users.schemas import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.post("/")
async def register(data: UserCreate) -> TokenResponse:
    return await service.register(data)


@router.post("/token")
async def login(data: LoginRequest) -> TokenResponse:
    return await service.authenticate(data.email, data.password)


@router.get("/me", response_model=UserRead)
async def get_me(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/me", response_model=UserRead)
async def update_me(
    data: UserUpdate,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    updated = await service.update_me(user, data, storage)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, updated.id, storage)
    user_read = UserRead.model_validate(updated)
    user_read.profile_photo = photo
    return user_read


@router.get("/me/organizations", response_model=list[OrganizationRead])
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> list[OrganizationRead]:
    orgs = await org_service.list_user_organizations(user)
    for org_read in orgs:
        org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return orgs


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    user = await service.get_by_id(user_id)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read
