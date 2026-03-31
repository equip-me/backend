import re
from datetime import date, datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.core.enums import MembershipRole, MembershipStatus, OrganizationStatus
from app.media.schemas import ProfilePhotoRead

_INN_RE = re.compile(r"^\d{10}$|^\d{12}$")


class ContactCreate(BaseModel):
    display_name: str
    phone: str | None = None
    email: EmailStr | None = None

    @model_validator(mode="after")
    def at_least_one_contact_method(self) -> Self:
        if not self.phone and not self.email:
            msg = "At least one of phone or email must be provided"
            raise ValueError(msg)
        return self


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    phone: str | None
    email: str | None


class OrganizationCreate(BaseModel):
    inn: str
    contacts: list[ContactCreate]

    @field_validator("inn")
    @classmethod
    def inn_format(cls, v: str) -> str:
        if not _INN_RE.match(v):
            msg = "INN must be 10 or 12 digits"
            raise ValueError(msg)
        return v

    @field_validator("contacts")
    @classmethod
    def at_least_one_contact(cls, v: list[ContactCreate]) -> list[ContactCreate]:
        if not v:
            msg = "At least one contact is required"
            raise ValueError(msg)
        return v


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inn: str
    short_name: str | None
    full_name: str | None
    registration_date: date | None
    authorized_capital_k_rubles: Decimal | None
    legal_address: str | None
    manager_name: str | None
    main_activity: str | None
    status: OrganizationStatus
    contacts: list[ContactRead]
    photo: ProfilePhotoRead | None = None


class OrganizationListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inn: str
    short_name: str | None
    full_name: str | None
    status: OrganizationStatus
    photo: ProfilePhotoRead | None = None
    published_listing_count: int = 0


class OrganizationPhotoUpdate(BaseModel):
    photo_id: UUID | None = None


class ContactsReplace(BaseModel):
    contacts: list[ContactCreate]

    @field_validator("contacts")
    @classmethod
    def at_least_one_contact(cls, v: list[ContactCreate]) -> list[ContactCreate]:
        if not v:
            msg = "At least one contact is required"
            raise ValueError(msg)
        return v


class PaymentDetailsCreate(BaseModel):
    payment_account: str
    bank_bic: str
    bank_inn: str
    bank_name: str
    bank_correspondent_account: str


class PaymentDetailsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_account: str
    bank_bic: str
    bank_inn: str
    bank_name: str
    bank_correspondent_account: str


class MembershipInvite(BaseModel):
    user_id: str
    role: MembershipRole


class MembershipApprove(BaseModel):
    role: MembershipRole


class MembershipRoleUpdate(BaseModel):
    role: MembershipRole


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    organization_id: str
    role: MembershipRole
    status: MembershipStatus
    created_at: datetime
    updated_at: datetime
