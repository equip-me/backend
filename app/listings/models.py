from typing import Any

from tortoise import fields
from tortoise.models import Model

from app.core.enums import ListingStatus
from app.core.identifiers import generate_short_id


class ListingCategory(Model):
    id = fields.CharField(max_length=6, primary_key=True, default=generate_short_id)
    name = fields.CharField(max_length=255)
    organization: Any = fields.ForeignKeyField("models.Organization", related_name="categories", null=True)
    added_by: Any = fields.ForeignKeyField("models.User", related_name="created_categories", null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    verified = fields.BooleanField(default=False)

    class Meta:
        table = "listing_categories"
        unique_together = (("name", "organization"),)


class Listing(Model):
    id = fields.CharField(max_length=6, primary_key=True, default=generate_short_id)
    name = fields.CharField(max_length=255)
    category: Any = fields.ForeignKeyField("models.ListingCategory", related_name="listings")
    price = fields.FloatField()
    description = fields.TextField(null=True)
    specifications: Any = fields.JSONField(null=True)
    status = fields.CharEnumField(ListingStatus, default=ListingStatus.HIDDEN, max_length=20)
    organization: Any = fields.ForeignKeyField(
        "models.Organization",
        related_name="listings",
        on_delete=fields.CASCADE,
    )
    added_by: Any = fields.ForeignKeyField("models.User", related_name="listings")
    with_operator = fields.BooleanField(default=False)
    on_owner_site = fields.BooleanField(default=False)
    delivery = fields.BooleanField(default=False)
    installation = fields.BooleanField(default=False)
    setup = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "listings"
