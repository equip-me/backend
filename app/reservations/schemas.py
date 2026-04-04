from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    listing_id: str
    start_date: date
    end_date: date
