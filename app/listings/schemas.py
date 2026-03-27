from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import ListingStatus


class ListingCategoryCreate(BaseModel):
    name: str


class ListingCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    verified: bool
    created_at: datetime
    listing_count: int = 0


class ListingCreate(BaseModel):
    name: str
    category_id: str
    price: float
    description: str | None = None
    specifications: dict[str, str] | None = None
    with_operator: bool = False
    on_owner_site: bool = False
    delivery: bool = False
    installation: bool = False
    setup: bool = False


class ListingUpdate(BaseModel):
    name: str | None = None
    category_id: str | None = None
    price: float | None = None
    description: str | None = None
    specifications: dict[str, str] | None = None
    with_operator: bool | None = None
    on_owner_site: bool | None = None
    delivery: bool | None = None
    installation: bool | None = None
    setup: bool | None = None


class ListingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: ListingCategoryRead
    price: float
    description: str | None
    specifications: dict[str, str] | None
    status: ListingStatus
    organization_id: str
    added_by_id: str
    with_operator: bool
    on_owner_site: bool
    delivery: bool
    installation: bool
    setup: bool
    created_at: datetime
    updated_at: datetime


class ListingStatusUpdate(BaseModel):
    status: ListingStatus
