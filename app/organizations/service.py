import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dadata import Dadata
from tortoise.expressions import Q
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
from app.core.pagination import CursorParams, PaginatedResponse, paginate
from app.observability.events import emit_event
from app.observability.metrics import dadata_duration, dadata_requests
from app.observability.tracing import traced
from app.organizations.models import Membership, Organization, OrganizationContact, PaymentDetails
from app.organizations.schemas import (
    ContactRead,
    ContactsReplace,
    MembershipApprove,
    MembershipInvite,
    MembershipRead,
    MembershipRoleUpdate,
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
    management = data.get("management") or {}

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


@traced
async def create_organization(
    data: OrganizationCreate,
    user: User,
    dadata: Dadata,
) -> OrganizationRead:
    existing = await Organization.filter(inn=data.inn).exists()
    if existing:
        raise AlreadyExistsError("Organization with this INN already exists")

    start = time.monotonic()
    try:
        results = await asyncio.to_thread(dadata.find_by_id, "party", data.inn)
        duration_ms = (time.monotonic() - start) * 1000
        dadata_requests.add(1, {"success": "true"})
        dadata_duration.record(duration_ms)
        emit_event("dadata.called", inn=data.inn, success="true", duration_ms=str(int(duration_ms)))
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        dadata_requests.add(1, {"success": "false"})
        dadata_duration.record(duration_ms)
        emit_event("dadata.called", inn=data.inn, success="false", duration_ms=str(int(duration_ms)))
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
    emit_event("organization.created", org_id=org.id, inn=data.inn)
    return OrganizationRead.model_validate(org)


@traced
async def get_organization(org_id: str) -> OrganizationRead:
    org = await Organization.get_or_none(id=org_id).prefetch_related("contacts")
    if org is None:
        raise NotFoundError("Organization not found")
    return OrganizationRead.model_validate(org)


@traced
async def list_user_organizations(
    user: User,
    params: CursorParams,
) -> tuple[list[Organization], str | None, bool]:
    qs = Membership.filter(
        user=user,
        status=MembershipStatus.MEMBER,
    ).prefetch_related("organization__contacts")

    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))
    orgs = [m.organization for m in items]
    return orgs, next_cursor, has_more


@traced
async def list_public_organizations(
    params: CursorParams,
    search: str | None = None,
) -> tuple[list[Organization], str | None, bool]:
    qs = Organization.filter(status=OrganizationStatus.VERIFIED)
    if search:
        qs = qs.filter(Q(short_name__icontains=search) | Q(full_name__icontains=search))
    return await paginate(qs, params, ordering=("-created_at", "-id"))


@traced
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


@traced
async def get_payment_details(org_id: str) -> PaymentDetailsRead:
    pd = await PaymentDetails.get_or_none(organization_id=org_id)
    if pd is None:
        raise NotFoundError("Payment details not found")
    return PaymentDetailsRead.model_validate(pd)


@traced
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


@traced
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
    emit_event("membership.invited", org_id=org_id, user_id=data.user_id, role=data.role.value)
    return MembershipRead.model_validate(membership)


@traced
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


@traced
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


@traced
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
    emit_event("membership.accepted", org_id=org_id, user_id=user.id)
    return MembershipRead.model_validate(membership)


async def _is_last_admin(org_id: str, member_id: str) -> bool:
    admin_count = await Membership.filter(
        organization_id=org_id,
        role=MembershipRole.ADMIN,
        status=MembershipStatus.MEMBER,
    ).count()
    if admin_count > 1:
        return False
    membership = await Membership.get(id=member_id)
    return membership.role == MembershipRole.ADMIN


@traced
async def change_member_role(org_id: str, member_id: str, data: MembershipRoleUpdate) -> MembershipRead:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")
    if membership.status != MembershipStatus.MEMBER:
        raise AppValidationError("Can only change role of active members")
    if data.role != MembershipRole.ADMIN and await _is_last_admin(org_id, member_id):
        raise AppValidationError("Cannot remove the last admin")
    membership.role = data.role
    await membership.save()
    return MembershipRead.model_validate(membership)


@traced
async def remove_member(org_id: str, member_id: str, user: User) -> None:
    membership = await Membership.get_or_none(id=member_id, organization_id=org_id)
    if membership is None:
        raise NotFoundError("Membership not found")

    # Check if self-removal
    await membership.fetch_related("user")
    membership_user: User = membership.user
    is_self = membership_user.id == user.id

    if not is_self:
        caller_membership = await Membership.get_or_none(
            user=user,
            organization_id=org_id,
            status=MembershipStatus.MEMBER,
            role=MembershipRole.ADMIN,
        )
        if caller_membership is None:
            raise PermissionDeniedError("Only admins can remove other members")

    if (
        membership.role == MembershipRole.ADMIN
        and membership.status == MembershipStatus.MEMBER
        and await _is_last_admin(org_id, member_id)
    ):
        raise AppValidationError("Cannot remove the last admin")

    await membership.delete()


@traced
async def list_members(
    org_id: str,
    params: CursorParams,
) -> PaginatedResponse[MembershipRead]:
    qs = Membership.filter(organization_id=org_id)
    items, next_cursor, has_more = await paginate(qs, params, ordering=("-created_at", "-id"))
    member_reads = [MembershipRead.model_validate(m) for m in items]
    return PaginatedResponse(items=member_reads, next_cursor=next_cursor, has_more=has_more)


@traced
async def verify_organization(org_id: str) -> OrganizationRead:
    org = await Organization.get_or_none(id=org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    org.status = OrganizationStatus.VERIFIED
    await org.save()
    await org.fetch_related("contacts")
    emit_event("organization.verified", org_id=org_id)
    return OrganizationRead.model_validate(org)
