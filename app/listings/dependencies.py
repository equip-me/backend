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
        raise NotFoundError("Listing not found")
    return listing


async def resolve_public_listing(
    user: Annotated[User | None, Depends(get_optional_user)],
    listing_id: str = Path(),
) -> Listing:
    listing = await Listing.get_or_none(id=listing_id).prefetch_related("category", "organization")
    if listing is None:
        raise NotFoundError("Listing not found")
    org: Organization = listing.organization
    if org.status != OrganizationStatus.VERIFIED:
        if user is None:
            raise PermissionDeniedError("Access denied")
        is_member = await Membership.filter(
            organization=org,
            user=user,
            status=MembershipStatus.MEMBER,
        ).exists()
        if not is_member:
            raise PermissionDeniedError("Access denied")
    return listing


async def get_category_filter(
    category_id: Annotated[list[str] | None, Query()] = None,
) -> list[str] | None:
    return category_id


async def get_org_filter(organization_id: str | None = Query(None)) -> str | None:
    return organization_id
