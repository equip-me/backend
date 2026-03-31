from typing import Any

from tortoise import fields
from tortoise.models import Model

from app.core.enums import MembershipRole, MembershipStatus, OrganizationStatus
from app.core.identifiers import generate_short_id


class Organization(Model):
    id = fields.CharField(max_length=6, primary_key=True, default=generate_short_id)
    inn = fields.CharField(max_length=12, unique=True)
    short_name = fields.CharField(max_length=255, null=True)
    full_name = fields.CharField(max_length=512, null=True)
    registration_date = fields.DateField(null=True)
    authorized_capital_k_rubles = fields.DecimalField(max_digits=12, decimal_places=2, null=True)
    legal_address = fields.TextField(null=True)
    manager_name = fields.CharField(max_length=255, null=True)
    main_activity = fields.CharField(max_length=255, null=True)
    dadata_response: Any = fields.JSONField(null=True)
    status = fields.CharEnumField(OrganizationStatus, default=OrganizationStatus.CREATED, max_length=20)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "organizations"


class OrganizationContact(Model):
    id = fields.UUIDField(primary_key=True)
    organization: Any = fields.ForeignKeyField("models.Organization", related_name="contacts")
    display_name = fields.CharField(max_length=255)
    phone = fields.CharField(max_length=255, null=True)
    email = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "organization_contacts"


class PaymentDetails(Model):
    id = fields.UUIDField(primary_key=True)
    organization: Any = fields.OneToOneField("models.Organization", related_name="payment_details")
    payment_account = fields.CharField(max_length=255)
    bank_bic = fields.CharField(max_length=255)
    bank_inn = fields.CharField(max_length=255)
    bank_name = fields.CharField(max_length=255)
    bank_correspondent_account = fields.CharField(max_length=255)

    class Meta:
        table = "payment_details"


class Membership(Model):
    id = fields.UUIDField(primary_key=True)
    user: Any = fields.ForeignKeyField("models.User", related_name="memberships")
    organization: Any = fields.ForeignKeyField("models.Organization", related_name="memberships")
    role = fields.CharEnumField(MembershipRole, max_length=20)
    status = fields.CharEnumField(MembershipStatus, max_length=20)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "memberships"
        unique_together = (("user", "organization"),)
