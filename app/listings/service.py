from tortoise.expressions import Q
from tortoise.functions import Count
from tortoise.queryset import QuerySet

from app.core.enums import ListingStatus, MediaOwnerType, OrganizationStatus
from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.core.identifiers import create_with_short_id
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.listings.dependencies import ListingFilter
from app.listings.models import Listing, ListingCategory
from app.listings.schemas import (
    ListingCategoryCreate,
    ListingCategoryRead,
    ListingCreate,
    ListingRead,
    ListingUpdate,
)
from app.media import service as media_service
from app.media.storage import StorageClient
from app.observability.events import emit_event
from app.observability.tracing import traced
from app.organizations.models import Organization
from app.users.models import User


async def _verified_org_ids() -> list[str]:
    orgs = await Organization.filter(status=OrganizationStatus.VERIFIED).only("id")
    return [org.id for org in orgs]


def _category_to_read(category: ListingCategory) -> ListingCategoryRead:
    return ListingCategoryRead(
        id=category.id,
        name=category.name,
        verified=category.verified,
        created_at=category.created_at,
        listing_count=getattr(category, "listing_count", 0),
    )


async def _listing_to_read(listing: Listing, storage: StorageClient) -> ListingRead:
    """Build ListingRead with media arrays from storage."""
    photos, videos, documents = await media_service.get_listing_media(listing.id, storage)
    read = ListingRead.model_validate(listing)
    read.photos = photos
    read.videos = videos
    read.documents = documents
    return read


@traced
async def create_category(org: Organization, user: User, data: ListingCategoryCreate) -> ListingCategoryRead:
    exists = await ListingCategory.filter(name=data.name, organization=org).exists()
    if exists:
        raise AlreadyExistsError("Category with this name already exists", code="listings.category_name_taken")
    category = await create_with_short_id(
        ListingCategory,
        name=data.name,
        organization=org,
        added_by=user,
        verified=False,
    )
    return ListingCategoryRead(
        id=category.id,
        name=category.name,
        verified=category.verified,
        created_at=category.created_at,
        listing_count=0,
    )


@traced
async def list_public_categories() -> list[ListingCategoryRead]:
    verified_org_ids = await _verified_org_ids()
    categories = (
        await ListingCategory.filter(verified=True)
        .annotate(
            listing_count=Count(
                "listings",
                _filter=Q(
                    listings__status=ListingStatus.PUBLISHED,
                    listings__organization_id__in=verified_org_ids,
                ),
            ),
        )
        .order_by("-listing_count")
    )
    return [_category_to_read(c) for c in categories]


async def _validate_category(category_id: str, org: Organization) -> ListingCategory:
    category = await ListingCategory.get_or_none(id=category_id)
    if category is None:
        raise NotFoundError("Category not found", code="listings.category_not_found")
    if not category.verified:
        owned = await ListingCategory.filter(id=category_id, organization_id=org.id).exists()
        if not owned:
            raise NotFoundError("Category not found", code="listings.category_not_found")
    return category


@traced
async def create_listing(org: Organization, user: User, data: ListingCreate, storage: StorageClient) -> ListingRead:
    category = await _validate_category(data.category_id, org)
    listing = await create_with_short_id(
        Listing,
        name=data.name,
        category=category,
        price=data.price,
        description=data.description,
        specifications=data.specifications,
        organization=org,
        added_by=user,
        with_operator=data.with_operator,
        on_owner_site=data.on_owner_site,
        delivery=data.delivery,
        installation=data.installation,
        setup=data.setup,
    )
    await listing.fetch_related("category")

    if data.photo_ids or data.video_ids or data.document_ids:
        await media_service.attach_listing_media(
            listing.id,
            data.photo_ids,
            data.video_ids,
            data.document_ids,
            storage,
        )

    emit_event("listing.created", listing_id=listing.id, org_id=org.id)
    return await _listing_to_read(listing, storage)


@traced
async def update_listing(
    listing: Listing, org: Organization, data: ListingUpdate, storage: StorageClient
) -> ListingRead:
    update_data = data.model_dump(exclude_unset=True)

    # Extract media fields before applying ORM updates
    has_media_update = "photo_ids" in update_data or "video_ids" in update_data or "document_ids" in update_data
    update_data.pop("photo_ids", None)
    update_data.pop("video_ids", None)
    update_data.pop("document_ids", None)

    if "category_id" in update_data:
        category = await _validate_category(update_data.pop("category_id"), org)
        listing.category = category
    for field, value in update_data.items():
        setattr(listing, field, value)
    await listing.save()
    await listing.fetch_related("category")

    if has_media_update:
        await media_service.attach_listing_media(
            listing.id,
            data.photo_ids if data.photo_ids is not None else [],
            data.video_ids if data.video_ids is not None else [],
            data.document_ids if data.document_ids is not None else [],
            storage,
        )

    return await _listing_to_read(listing, storage)


@traced
async def delete_listing(listing: Listing, storage: StorageClient) -> None:
    await media_service.delete_entity_media(MediaOwnerType.LISTING, listing.id, storage)
    await listing.delete()


@traced
async def change_listing_status(listing: Listing, status: ListingStatus, storage: StorageClient) -> ListingRead:
    old_status = listing.status
    listing.status = status
    await listing.save()
    await listing.fetch_related("category")
    emit_event("listing.status_changed", listing_id=listing.id, old_status=old_status.value, new_status=status.value)
    return await _listing_to_read(listing, storage)


def _apply_listing_filters(qs: QuerySet[Listing], filters: ListingFilter) -> QuerySet[Listing]:
    if filters.category_ids is not None:
        qs = qs.filter(category_id__in=filters.category_ids)
    if filters.organization_id is not None:
        qs = qs.filter(organization_id=filters.organization_id)
    if filters.search:
        qs = qs.filter(name__icontains=filters.search)
    if filters.price_min is not None:
        qs = qs.filter(price__gte=filters.price_min)
    if filters.price_max is not None:
        qs = qs.filter(price__lte=filters.price_max)
    for field in ("with_operator", "on_owner_site", "delivery", "installation", "setup"):
        value = getattr(filters, field)
        if value is not None:
            qs = qs.filter(**{field: value})
    return qs


@traced
async def list_org_listings(
    org_id: str,
    storage: StorageClient,
    params: CursorParams,
    filters: ListingFilter,
) -> PaginatedResponse[ListingRead]:
    qs = Listing.filter(organization_id=org_id)
    qs = _apply_listing_filters(qs, filters)
    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=("-updated_at", "-id"),
    )
    listing_reads = [await _listing_to_read(listing, storage) for listing in items]
    return PaginatedResponse(items=listing_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def list_public_listings(
    storage: StorageClient,
    params: CursorParams,
    filters: ListingFilter,
) -> PaginatedResponse[ListingRead]:
    qs = Listing.filter(
        status=ListingStatus.PUBLISHED,
        organization__status=OrganizationStatus.VERIFIED,
    )
    qs = _apply_listing_filters(qs, filters)

    items, next_cursor, has_more = await paginate(
        qs.prefetch_related("category"),
        params,
        ordering=("-updated_at", "-id"),
    )

    listing_reads = [await _listing_to_read(listing, storage) for listing in items]
    return PaginatedResponse(items=listing_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def get_listing_read(listing: Listing, storage: StorageClient) -> ListingRead:
    return await _listing_to_read(listing, storage)


@traced
async def list_available_categories(org_id: str) -> list[ListingCategoryRead]:
    verified_org_ids = await _verified_org_ids()
    categories = (
        await ListingCategory.filter(Q(verified=True) | Q(organization_id=org_id))
        .annotate(
            listing_count=Count(
                "listings",
                _filter=Q(
                    listings__status=ListingStatus.PUBLISHED,
                    listings__organization_id__in=verified_org_ids,
                ),
            ),
        )
        .distinct()
        .order_by("-listing_count")
    )
    return [_category_to_read(c) for c in categories]


@traced
async def list_org_categories(org_id: str) -> list[ListingCategoryRead]:
    org_exists = await Organization.filter(id=org_id).exists()
    if not org_exists:
        raise NotFoundError("Organization not found", code="org.not_found")
    categories = (
        await ListingCategory.filter(
            listings__organization_id=org_id,
            listings__status=ListingStatus.PUBLISHED,
        )
        .annotate(
            listing_count=Count(
                "listings",
                _filter=Q(
                    listings__organization_id=org_id,
                    listings__status=ListingStatus.PUBLISHED,
                ),
            ),
        )
        .distinct()
        .order_by("-listing_count")
    )
    return [_category_to_read(c) for c in categories]
