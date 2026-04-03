from tortoise import fields
from tortoise.models import Model


class Reservation(Model):
    id = fields.UUIDField(primary_key=True)
    listing = fields.ForeignKeyField("models.Listing", related_name="reservations")
    listing_id: str
    order_id = fields.CharField(max_length=20, unique=True)
    start_date = fields.DateField()
    end_date = fields.DateField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "reservations"
