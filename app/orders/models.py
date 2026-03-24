from typing import Any

from tortoise import fields
from tortoise.models import Model

from app.core.enums import OrderStatus


class Order(Model):
    id = fields.UUIDField(pk=True)
    listing: Any = fields.ForeignKeyField("models.Listing", related_name="orders")
    organization: Any = fields.ForeignKeyField("models.Organization", related_name="orders")
    requester: Any = fields.ForeignKeyField("models.User", related_name="orders")
    requested_start_date = fields.DateField()
    requested_end_date = fields.DateField()
    status = fields.CharEnumField(OrderStatus, default=OrderStatus.PENDING, max_length=30)
    estimated_cost = fields.DecimalField(max_digits=12, decimal_places=2, null=True)
    offered_cost = fields.DecimalField(max_digits=12, decimal_places=2, null=True)
    offered_start_date = fields.DateField(null=True)
    offered_end_date = fields.DateField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "orders"
