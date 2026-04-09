from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.dependencies import require_active_user
from app.core.pagination import CursorParams, OrderingParams, PaginatedResponse
from app.organizations import service
from app.organizations.dependencies import MemberOrdering, get_org_or_404, require_org_admin, require_org_member
from app.organizations.models import Membership, Organization
from app.organizations.schemas import (
    MembershipApprove,
    MembershipInvite,
    MembershipRead,
    MembershipRoleUpdate,
)
from app.users.models import User

router = APIRouter(prefix="/api/v1/organizations", tags=["Memberships"])


@router.post("/{org_id}/members/invite", response_model=MembershipRead)
async def invite_member(
    org_id: str,
    data: MembershipInvite,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.invite_member(org_id, data)


@router.post("/{org_id}/members/join", response_model=MembershipRead)
async def join_organization(
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> MembershipRead:
    return await service.join_organization(org.id, user)


@router.patch("/{org_id}/members/{member_id}/approve", response_model=MembershipRead)
async def approve_candidate(
    org_id: str,
    member_id: str,
    data: MembershipApprove,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.approve_candidate(org_id, member_id, data)


@router.patch("/{org_id}/members/{member_id}/accept", response_model=MembershipRead)
async def accept_invitation(
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> MembershipRead:
    return await service.accept_invitation(org.id, member_id, user)


@router.patch("/{org_id}/members/{member_id}/role", response_model=MembershipRead)
async def change_member_role(
    org_id: str,
    member_id: str,
    data: MembershipRoleUpdate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.change_member_role(org_id, member_id, data)


@router.delete("/{org_id}/members/{member_id}", status_code=204)
async def remove_member(
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
    org: Annotated[Organization, Depends(get_org_or_404)],
) -> Response:
    await service.remove_member(org.id, member_id, user)
    return Response(status_code=204)


@router.get("/{org_id}/members", response_model=PaginatedResponse[MembershipRead])
async def list_members(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
    ordering: Annotated[OrderingParams, Depends(MemberOrdering)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MembershipRead]:
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.list_members(org_id, params, ordering.ordering)
