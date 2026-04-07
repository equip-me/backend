from typing import Annotated

from fastapi import Depends, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.enums import MembershipStatus, OrganizationStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.security import decode_access_token
from app.listings.models import Listing
from app.organizations.dependencies import require_org_editor
from app.organizations.models import Membership, Organization
from app.users.models import User

_optional_bearer = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
) -> User | None:
    if credentials is None:
        return None
    try:
        subject = decode_access_token(credentials.credentials)
    except ValueError:
        return None
    return await User.get_or_none(id=subject)


async def resolve_listing(
    membership: Annotated[Membership, Depends(require_org_editor)],
    listing_id: str = Path(),
) -> Listing:
    await membership.fetch_related("organization")
    org: Organization = membership.organization
    listing = await Listing.get_or_none(id=listing_id, organization=org).prefetch_related("category")
    if listing is None:
        raise NotFoundError("Listing not found", code="listings.not_found")
    return listing


async def resolve_public_listing(
    user: Annotated[User | None, Depends(get_optional_user)],
    listing_id: str = Path(),
) -> Listing:
    listing = await Listing.get_or_none(id=listing_id).prefetch_related("category", "organization")
    if listing is None:
        raise NotFoundError("Listing not found", code="listings.not_found")
    org: Organization = listing.organization
    if org.status != OrganizationStatus.VERIFIED:
        if user is None:
            raise PermissionDeniedError("Access denied", code="listings.access_denied")
        is_member = await Membership.filter(
            organization=org,
            user=user,
            status=MembershipStatus.MEMBER,
        ).exists()
        if not is_member:
            raise PermissionDeniedError("Access denied", code="listings.access_denied")
    return listing


class ListingFilter:
    def __init__(
        self,
        *,
        category_id: Annotated[list[str] | None, Query()] = None,
        organization_id: str | None = Query(None),
        search: str | None = Query(None),
        price_min: float | None = Query(None, ge=0),
        price_max: float | None = Query(None, ge=0),
        with_operator: bool | None = Query(None),
        on_owner_site: bool | None = Query(None),
        delivery: bool | None = Query(None),
        installation: bool | None = Query(None),
        setup: bool | None = Query(None),
    ) -> None:
        self.category_ids = category_id
        self.organization_id = organization_id
        self.search = search
        self.price_min = price_min
        self.price_max = price_max
        self.with_operator = with_operator
        self.on_owner_site = on_owner_site
        self.delivery = delivery
        self.installation = installation
        self.setup = setup
