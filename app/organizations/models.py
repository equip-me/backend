from typing import Any

from tortoise import fields
from tortoise.models import Model

from app.core.enums import MembershipRole, MembershipStatus, OrganizationStatus


class Organization(Model):
    id = fields.UUIDField(pk=True)
    inn = fields.CharField(max_length=12, unique=True)
    short_name = fields.CharField(max_length=255, null=True)
    full_name = fields.CharField(max_length=512, null=True)
    ogrn = fields.CharField(max_length=15, null=True)
    kpp = fields.CharField(max_length=9, null=True)
    registration_date = fields.DateField(null=True)
    authorized_capital_k_rubles = fields.DecimalField(max_digits=12, decimal_places=2, null=True)
    legal_address = fields.TextField(null=True)
    manager_name = fields.CharField(max_length=255, null=True)
    main_activity = fields.CharField(max_length=255, null=True)
    contact_phone = fields.CharField(max_length=20)
    contact_email = fields.CharField(max_length=255)
    contact_employee_name = fields.CharField(max_length=150)
    contact_employee_middle_name = fields.CharField(max_length=150, null=True)
    contact_employee_surname = fields.CharField(max_length=150, null=True)
    status = fields.CharEnumField(OrganizationStatus, default=OrganizationStatus.CREATED, max_length=20)

    class Meta:
        table = "organizations"


class Membership(Model):
    id = fields.UUIDField(pk=True)
    user: Any = fields.ForeignKeyField("models.User", related_name="memberships")
    organization: Any = fields.ForeignKeyField("models.Organization", related_name="memberships")
    role = fields.CharEnumField(MembershipRole, max_length=20)
    status = fields.CharEnumField(MembershipStatus, max_length=20)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "memberships"
        unique_together = (("user", "organization"),)
