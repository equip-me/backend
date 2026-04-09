from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_platform_admin, require_platform_owner
from app.core.enums import ListingStatus, MediaOwnerType, OrganizationStatus, UserRole
from app.core.pagination import CursorParams, OrderingParams, PaginatedResponse
from app.listings.models import Listing
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service as org_service
from app.organizations.dependencies import OrganizationOrdering
from app.organizations.schemas import OrganizationListRead, OrganizationRead
from app.users import service as user_service
from app.users.models import User
from app.users.schemas import AdminRoleUpdate, PrivilegeUpdate, UserRead

router = APIRouter(prefix="/api/v1/private", tags=["Admin"])


@router.get("/users/", response_model=PaginatedResponse[UserRead])
async def list_users(
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
    role: UserRole | None = None,
) -> PaginatedResponse[UserRead]:
    """List all platform users. Supports search by name/email and role filter. Platform Admin only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await user_service.list_users(params, storage, search=search, role=role)


@router.patch("/users/{user_id}/role", response_model=UserRead)
async def change_role(
    user_id: str,
    data: AdminRoleUpdate,
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    """Change user role (user/suspended). Platform Admin only."""
    user = await user_service.change_user_role(user_id, data)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.patch("/users/{user_id}/privilege", response_model=UserRead)
async def change_privilege(
    user_id: str,
    data: PrivilegeUpdate,
    _owner: Annotated[User, Depends(require_platform_owner)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UserRead:
    """Promote/demote platform admin. Platform Owner only."""
    user = await user_service.change_privilege(user_id, data)
    photo = await media_service.get_profile_photo(MediaOwnerType.USER, user.id, storage)
    user_read = UserRead.model_validate(user)
    user_read.profile_photo = photo
    return user_read


@router.get("/organizations/", response_model=PaginatedResponse[OrganizationListRead])
async def list_all_organizations(
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    ordering: Annotated[OrderingParams, Depends(OrganizationOrdering)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
    status: OrganizationStatus | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """List all organizations regardless of verification status. Platform Admin only."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await org_service.list_all_organizations(
        params, ordering.ordering, search=search, status=status
    )

    org_reads: list[OrganizationListRead] = []
    for org in items:
        published_count = await Listing.filter(
            organization=org,
            status=ListingStatus.PUBLISHED,
        ).count()
        photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
        org_reads.append(
            OrganizationListRead(
                id=org.id,
                inn=org.inn,
                short_name=org.short_name,
                full_name=org.full_name,
                status=org.status,
                photo=photo,
                published_listing_count=published_count,
            ),
        )

    return PaginatedResponse(items=org_reads, next_cursor=next_cursor, has_more=has_more)


@router.patch("/organizations/{org_id}/verify", response_model=OrganizationRead)
async def verify_organization(
    org_id: str,
    _admin: Annotated[User, Depends(require_platform_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    """Verify organization, making its published listings visible in the public catalog. Platform Admin only."""
    org_read = await org_service.verify_organization(org_id)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read
