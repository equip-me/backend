from typing import Annotated

from fastapi import APIRouter, Depends

from app.listings import service
from app.listings.schemas import ListingCategoryCreate, ListingCategoryRead
from app.organizations.dependencies import require_org_editor, require_org_member
from app.organizations.models import Membership, Organization
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Listing Categories"])


@router.get("/listings/categories/", response_model=list[ListingCategoryRead])
async def list_public_categories() -> list[ListingCategoryRead]:
    return await service.list_public_categories()


@router.get("/organizations/{org_id}/listings/categories/", response_model=list[ListingCategoryRead])
async def list_org_categories(
    org_id: str,
) -> list[ListingCategoryRead]:
    return await service.list_org_categories(org_id)


@router.get(
    "/organizations/{org_id}/listings/categories/available/",
    response_model=list[ListingCategoryRead],
)
async def list_available_categories(
    membership: Annotated[Membership, Depends(require_org_member)],
) -> list[ListingCategoryRead]:
    await membership.fetch_related("organization")
    org: Organization = membership.organization
    return await service.list_available_categories(org.id)


@router.post(
    "/organizations/{org_id}/listings/categories/",
    response_model=ListingCategoryRead,
    status_code=201,
)
async def create_category(
    data: ListingCategoryCreate,
    membership: Annotated[Membership, Depends(require_org_editor)],
) -> ListingCategoryRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.create_category(org, user, data)
