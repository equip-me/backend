from fastapi import APIRouter

from app.reservations import service
from app.reservations.schemas import ReservationRead

router = APIRouter(prefix="/api/v1", tags=["Reservations"])


@router.get("/listings/{listing_id}/reservations", response_model=list[ReservationRead])
async def list_listing_reservations(listing_id: str) -> list[ReservationRead]:
    reservations = await service.list_future_reservations(listing_id=listing_id)
    return [ReservationRead.model_validate(r) for r in reservations]
