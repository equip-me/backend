from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.core.enums import ListingStatus, MediaOwnerType
from app.core.pagination import CursorParams, OrderingParams, PaginatedResponse
from app.listings.models import Listing
from app.media import service as media_service
from app.media.storage import StorageClient, get_storage
from app.organizations import service
from app.organizations.dependencies import (
    OrganizationOrdering,
    get_dadata_client,
    require_org_admin,
    require_org_member,
)
from app.organizations.models import Membership, Organization
from app.organizations.schemas import (
    ContactRead,
    ContactsReplace,
    OrganizationCreate,
    OrganizationListRead,
    OrganizationPhotoUpdate,
    OrganizationRead,
    PaymentDetailsCreate,
    PaymentDetailsRead,
)
from app.users.models import User

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


@router.post("/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.create_organization(data, user, dadata)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read


@router.get("/", response_model=PaginatedResponse[OrganizationListRead])
async def list_organizations(
    storage: Annotated[StorageClient, Depends(get_storage)],
    ordering: Annotated[OrderingParams, Depends(OrganizationOrdering)],
    cursor: str | None = None,
    limit: int = 20,
    search: str | None = None,
) -> PaginatedResponse[OrganizationListRead]:
    """Browse verified organizations with published listing count."""
    params = CursorParams(cursor=cursor, limit=limit)
    items, next_cursor, has_more = await service.list_public_organizations(params, ordering.ordering, search=search)

    org_reads: list[OrganizationListRead] = []
    for org in items:
        published_count = await Listing.filter(
            organization=org,
            status=ListingStatus.PUBLISHED,
        ).count()
        photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
        org_read = OrganizationListRead(
            id=org.id,
            inn=org.inn,
            short_name=org.short_name,
            full_name=org.full_name,
            status=org.status,
            photo=photo,
            published_listing_count=published_count,
        )
        org_reads.append(org_read)

    return PaginatedResponse(items=org_reads, next_cursor=next_cursor, has_more=has_more)


@router.get("/{org_id}", response_model=OrganizationRead)
async def get_organization(
    org_id: str,
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    org_read = await service.get_organization(org_id)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org_read.id, storage)
    return org_read


@router.patch("/{org_id}/photo", response_model=OrganizationRead)
async def update_org_photo(
    data: OrganizationPhotoUpdate,
    membership: Annotated[Membership, Depends(require_org_admin)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> OrganizationRead:
    await membership.fetch_related("organization", "user")
    org: Organization = membership.organization
    user: User = membership.user
    await media_service.attach_profile_photo(
        data.photo_id,
        MediaOwnerType.ORGANIZATION,
        org.id,
        user,
        storage,
    )
    await org.fetch_related("contacts")
    org_read = OrganizationRead.model_validate(org)
    org_read.photo = await media_service.get_profile_photo(MediaOwnerType.ORGANIZATION, org.id, storage)
    return org_read


@router.put("/{org_id}/contacts", response_model=list[ContactRead])
async def replace_contacts(
    org_id: str,
    data: ContactsReplace,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> list[ContactRead]:
    return await service.replace_contacts(org_id, data)


@router.get("/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def get_payment_details(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> PaymentDetailsRead:
    return await service.get_payment_details(org_id)


@router.post("/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def create_payment_details(
    org_id: str,
    data: PaymentDetailsCreate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> PaymentDetailsRead:
    return await service.upsert_payment_details(org_id, data)
