from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.pagination import CursorParams, PaginatedResponse
from app.listings import service
from app.listings.dependencies import get_category_filter, get_org_filter, resolve_listing, resolve_public_listing
from app.listings.models import Listing
from app.listings.schemas import (
    ListingCreate,
    ListingRead,
    ListingStatusUpdate,
    ListingUpdate,
)
from app.media.storage import StorageClient, get_storage
from app.organizations.dependencies import require_org_editor, require_org_member
from app.organizations.models import Membership, Organization
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Listings"])


@router.post(
    "/organizations/{org_id}/listings/",
    response_model=ListingRead,
    status_code=201,
)
async def create_listing(
    data: ListingCreate,
    membership: Annotated[Membership, Depends(require_org_editor)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.create_listing(org, user, data, storage)


@router.patch("/organizations/{org_id}/listings/{listing_id}", response_model=ListingRead)
async def update_listing(
    data: ListingUpdate,
    listing: Annotated[Listing, Depends(resolve_listing)],
    membership: Annotated[Membership, Depends(require_org_editor)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    return await service.update_listing(listing, org, data, user, storage)


@router.delete("/organizations/{org_id}/listings/{listing_id}", status_code=204)
async def delete_listing(
    listing: Annotated[Listing, Depends(resolve_listing)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> Response:
    await service.delete_listing(listing, storage)
    return Response(status_code=204)


@router.patch(
    "/organizations/{org_id}/listings/{listing_id}/status",
    response_model=ListingRead,
)
async def change_listing_status(
    data: ListingStatusUpdate,
    listing: Annotated[Listing, Depends(resolve_listing)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    return await service.change_listing_status(listing, data.status, storage)


@router.get("/organizations/{org_id}/listings/", response_model=PaginatedResponse[ListingRead])
async def list_org_listings(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[ListingRead]:
    """List all listings for the organization regardless of status. Org members only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_org_listings(org_id, storage, params)


@router.get("/listings/", response_model=PaginatedResponse[ListingRead])
async def list_public_listings(
    category_id: Annotated[str | None, Depends(get_category_filter)],
    organization_id: Annotated[str | None, Depends(get_org_filter)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
) -> PaginatedResponse[ListingRead]:
    """Browse published listings from verified organizations only."""
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_public_listings(storage, params, category_id, organization_id, search)


@router.get("/listings/{listing_id}", response_model=ListingRead)
async def get_listing(
    listing: Annotated[Listing, Depends(resolve_public_listing)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> ListingRead:
    """Get a single listing by ID. Public access for verified orgs, member-only for unverified."""
    return await service.get_listing_read(listing, storage)
