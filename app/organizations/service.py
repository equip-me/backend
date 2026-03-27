import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from dadata import Dadata
from tortoise.transactions import in_transaction

from app.core.enums import MembershipRole, MembershipStatus
from app.core.exceptions import AlreadyExistsError, ExternalServiceError
from app.core.identifiers import create_with_short_id
from app.organizations.models import Membership, Organization, OrganizationContact
from app.organizations.schemas import OrganizationCreate, OrganizationRead
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
