import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dadata import Dadata
from tortoise.transactions import in_transaction

from app.core.enums import MembershipRole, MembershipStatus, OrganizationStatus
from app.core.exceptions import (
    AlreadyExistsError,
    AppValidationError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.identifiers import create_with_short_id
from app.organizations.models import Membership, Organization, OrganizationContact, PaymentDetails
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


def _extract_dadata_fields(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data", {})
    name = data.get("name", {})
    state = data.get("state", {})
    address = data.get("address", {})
    management = data.get("management", {})

    reg_date = None
    reg_ts = state.get("registration_date")
    if reg_ts is not None:
        reg_date = datetime.fromtimestamp(reg_ts / 1000, tz=UTC).date()

    return {
        "short_name": name.get("short_with_opf"),
        "full_name": name.get("full_with_opf"),
        "registration_date": reg_date,
        "legal_address": address.get("value"),
        "manager_name": management.get("name"),
        "main_activity": data.get("okved"),
    }


async def create_organization(
    data: OrganizationCreate,
    user: User,
    dadata: Dadata,
) -> OrganizationRead:
    existing = await Organization.filter(inn=data.inn).exists()
    if existing:
        raise AlreadyExistsError("Organization with this INN already exists")

    try:
        results = await asyncio.to_thread(dadata.find_by_id, "party", data.inn)
    except Exception as e:
        raise ExternalServiceError("Dadata service unavailable") from e

    if not results:
        raise ExternalServiceError("Organization not found by INN")

    dadata_result = results[0]
    dadata_fields = _extract_dadata_fields(dadata_result)

    async with in_transaction():
        org = await create_with_short_id(
            Organization,
            inn=data.inn,
            dadata_response=dadata_result,
            **dadata_fields,
        )

        for contact in data.contacts:
            await OrganizationContact.create(
                id=uuid4(),
                organization=org,
                display_name=contact.display_name,
                phone=contact.phone,
                email=contact.email,
            )

        await Membership.create(
            id=uuid4(),
            user=user,
            organization=org,
            role=MembershipRole.ADMIN,
            status=MembershipStatus.MEMBER,
        )

    await org.fetch_related("contacts")
    return OrganizationRead.model_validate(org)


async def get_organization(org_id: str) -> OrganizationRead:
    org = await Organization.get_or_none(id=org_id).prefetch_related("contacts")
    if org is None:
        raise NotFoundError("Organization not found")
    return OrganizationRead.model_validate(org)


async def list_user_organizations(user: User) -> list[OrganizationRead]:
    memberships = await Membership.filter(
        user=user,
        status=MembershipStatus.MEMBER,
    ).prefetch_related("organization__contacts")
    return [OrganizationRead.model_validate(m.organization) for m in memberships]


async def replace_contacts(org_id: str, data: ContactsReplace) -> list[ContactRead]:
    async with in_transaction():
        await OrganizationContact.filter(organization_id=org_id).delete()
        for contact in data.contacts:
            await OrganizationContact.create(
                id=uuid4(),
                organization_id=org_id,
                display_name=contact.display_name,
                phone=contact.phone,
                email=contact.email,
            )
    contacts = await OrganizationContact.filter(organization_id=org_id)
    return [ContactRead.model_validate(c) for c in contacts]


async def get_payment_details(org_id: str) -> PaymentDetailsRead:
    pd = await PaymentDetails.get_or_none(organization_id=org_id)
    if pd is None:
        raise NotFoundError("Payment details not found")
    return PaymentDetailsRead.model_validate(pd)


async def upsert_payment_details(org_id: str, data: PaymentDetailsCreate) -> PaymentDetailsRead:
    pd = await PaymentDetails.get_or_none(organization_id=org_id)
    if pd is None:
        pd = await PaymentDetails.create(
            id=uuid4(),
            organization_id=org_id,
            **data.model_dump(),
        )
    else:
        for field, value in data.model_dump().items():
            setattr(pd, field, value)
        await pd.save()
    return PaymentDetailsRead.model_validate(pd)


async def invite_member(org_id: str, data: MembershipInvite) -> MembershipRead:
    target_user = await User.get_or_none(id=data.user_id)
    if target_user is None:
        raise NotFoundError("User not found")
    existing = await Membership.get_or_none(user=target_user, organization_id=org_id)
    if existing is not None:
        raise AlreadyExistsError("User already has a membership in this organization")
    membership = await Membership.create(
        id=uuid4(),
        user=target_user,
        organization_id=org_id,
        role=data.role,
        status=MembershipStatus.INVITED,
    )
    return MembershipRead.model_validate(membership)


async def join_organization(org_id: str, user: User) -> MembershipRead:
    existing = await Membership.get_or_none(user=user, organization_id=org_id)
    if existing is not None:
        raise AlreadyExistsError("You already have a membership in this organization")
    membership = await Membership.create(
        id=uuid4(),
        user=user,
        organization_id=org_id,
        role=MembershipRole.VIEWER,
        status=MembershipStatus.CANDIDATE,
    )
    return MembershipRead.model_validate(membership)


async def approve_candidate(org_id: str, member_id: str, data: MembershipApprove) -> MembershipRead:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.status != MembershipStatus.CANDIDATE:
        raise AppValidationError("Only candidates can be approved")
    membership.role = data.role
    membership.status = MembershipStatus.MEMBER
    await membership.save()
    return MembershipRead.model_validate(membership)


async def accept_invitation(org_id: str, member_id: str, user: User) -> MembershipRead:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")
    await membership.fetch_related("user")
    membership_user: User = membership.user
    if membership_user.id != user.id:
        raise PermissionDeniedError("You can only accept your own invitation")
    if membership.status != MembershipStatus.INVITED:
        raise AppValidationError("Only invitations can be accepted")
    membership.status = MembershipStatus.MEMBER
    await membership.save()
    return MembershipRead.model_validate(membership)


async def verify_organization(org_id: str) -> OrganizationRead:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    org.status = OrganizationStatus.VERIFIED
    await org.save()
    await org.fetch_related("contacts")
    return OrganizationRead.model_validate(org)
