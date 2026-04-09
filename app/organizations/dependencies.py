from typing import Annotated

from dadata import Dadata
from fastapi import Depends, Path

from app.core.config import get_settings
from app.core.dependencies import require_active_user
from app.core.enums import MembershipRole, MembershipStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.pagination import ordering_dependency
from app.organizations.models import Membership, Organization
from app.users.models import User


def get_dadata_client() -> Dadata:
    settings = get_settings()
    return Dadata(settings.dadata_api_key)


async def get_org_or_404(org_id: str = Path()) -> Organization:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found", code="org.not_found")
    return org


async def require_org_member(
    org: Annotated[Organization, Depends(get_org_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Membership:
    membership = await Membership.get_or_none(
        organization=org,
        user=user,
        status=MembershipStatus.MEMBER,
    )
    if membership is None:
        raise PermissionDeniedError("Organization membership required", code="org.membership_required")
    return membership


async def require_org_editor(
    org: Annotated[Organization, Depends(get_org_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Membership:
    membership = await Membership.get_or_none(
        organization=org,
        user=user,
        status=MembershipStatus.MEMBER,
        role__in=[MembershipRole.ADMIN, MembershipRole.EDITOR],
    )
    if membership is None:
        raise PermissionDeniedError("Organization editor access required", code="org.editor_required")
    return membership


async def require_org_admin(
    org: Annotated[Organization, Depends(get_org_or_404)],
    user: Annotated[User, Depends(require_active_user)],
) -> Membership:
    membership = await Membership.get_or_none(
        organization=org,
        user=user,
        status=MembershipStatus.MEMBER,
        role=MembershipRole.ADMIN,
    )
    if membership is None:
        raise PermissionDeniedError("Organization admin access required", code="org.admin_required")
    return membership


OrganizationOrdering = ordering_dependency(
    allowed_fields={"short_name": "short_name", "created_at": "created_at"},
    default="-created_at",
)
MemberOrdering = ordering_dependency(
    allowed_fields={"role": "role", "created_at": "created_at"},
    default="-created_at",
)
UserOrgOrdering = ordering_dependency(
    allowed_fields={"created_at": "created_at"},
    default="-created_at",
)
