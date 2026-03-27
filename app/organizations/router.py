from typing import Annotated

from dadata import Dadata
from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user, require_platform_admin
from app.core.exceptions import NotFoundError
from app.organizations import service
from app.organizations.dependencies import get_dadata_client, require_org_admin, require_org_member
from app.organizations.models import Membership, Organization
from app.organizations.schemas import (
    ContactRead,
    ContactsReplace,
    MembershipApprove,
    MembershipInvite,
    MembershipRead,
    OrganizationCreate,
    OrganizationRead,
    PaymentDetailsCreate,
    PaymentDetailsRead,
)
from app.users.models import User

router = APIRouter()


@router.post("/organizations/", response_model=OrganizationRead)
async def create_organization(
    data: OrganizationCreate,
    user: Annotated[User, Depends(require_active_user)],
    dadata: Annotated[Dadata, Depends(get_dadata_client)],
) -> OrganizationRead:
    return await service.create_organization(data, user, dadata)


@router.get("/organizations/{org_id}", response_model=OrganizationRead)
async def get_organization(org_id: str) -> OrganizationRead:
    return await service.get_organization(org_id)


@router.get("/users/me/organizations", response_model=list[OrganizationRead])
async def list_my_organizations(
    user: Annotated[User, Depends(require_active_user)],
) -> list[OrganizationRead]:
    return await service.list_user_organizations(user)


@router.put("/organizations/{org_id}/contacts", response_model=list[ContactRead])
async def replace_contacts(
    org_id: str,
    data: ContactsReplace,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> list[ContactRead]:
    return await service.replace_contacts(org_id, data)


@router.get("/organizations/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def get_payment_details(
    org_id: str,
    _membership: Annotated[Membership, Depends(require_org_member)],
) -> PaymentDetailsRead:
    return await service.get_payment_details(org_id)


@router.post("/organizations/{org_id}/payment-details", response_model=PaymentDetailsRead)
async def create_payment_details(
    org_id: str,
    data: PaymentDetailsCreate,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> PaymentDetailsRead:
    return await service.upsert_payment_details(org_id, data)


@router.post("/organizations/{org_id}/members/invite", response_model=MembershipRead)
async def invite_member(
    org_id: str,
    data: MembershipInvite,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.invite_member(org_id, data)


@router.post("/organizations/{org_id}/members/join", response_model=MembershipRead)
async def join_organization(
    org_id: str,
    user: Annotated[User, Depends(require_active_user)],
) -> MembershipRead:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return await service.join_organization(org_id, user)


@router.patch("/organizations/{org_id}/members/{member_id}/approve", response_model=MembershipRead)
async def approve_candidate(
    org_id: str,
    member_id: str,
    data: MembershipApprove,
    _membership: Annotated[Membership, Depends(require_org_admin)],
) -> MembershipRead:
    return await service.approve_candidate(org_id, member_id, data)


@router.patch("/organizations/{org_id}/members/{member_id}/accept", response_model=MembershipRead)
async def accept_invitation(
    org_id: str,
    member_id: str,
    user: Annotated[User, Depends(require_active_user)],
) -> MembershipRead:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return await service.accept_invitation(org_id, member_id, user)


@router.patch("/private/organizations/{org_id}/verify", response_model=OrganizationRead)
async def verify_organization(
    org_id: str,
    _admin: Annotated[User, Depends(require_platform_admin)],
) -> OrganizationRead:
    return await service.verify_organization(org_id)
