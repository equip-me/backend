from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator

from app.core.enums import OrderStatus


class OrderCreate(BaseModel):
    listing_id: str
    requested_start_date: date
    requested_end_date: date

    @model_validator(mode="after")
    def start_before_end(self) -> Self:
        if self.requested_start_date > self.requested_end_date:
            msg = "requested_start_date must be <= requested_end_date"
            raise ValueError(msg)
        return self


class OrderOffer(BaseModel):
    offered_cost: Decimal
    offered_start_date: date
    offered_end_date: date

    @field_validator("offered_cost")
    @classmethod
    def positive_cost(cls, v: Decimal) -> Decimal:
        if v <= 0:
            msg = "offered_cost must be positive"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def start_before_end(self) -> Self:
        if self.offered_start_date > self.offered_end_date:
            msg = "offered_start_date must be <= offered_end_date"
            raise ValueError(msg)
        return self


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    listing_id: str
    organization_id: str
    requester_id: str
    requested_start_date: date
    requested_end_date: date
    status: OrderStatus
    estimated_cost: Decimal | None
    offered_cost: Decimal | None
    offered_start_date: date | None
    offered_end_date: date | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("estimated_cost", "offered_cost")
    def serialize_decimal(self, v: Decimal | None) -> str | None:
        if v is None:
            return None
        return str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
