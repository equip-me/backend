from datetime import UTC, date, datetime
from uuid import uuid4

from app.core.exceptions import AppValidationError
from app.reservations.models import Reservation


async def create_reservation(
    *,
    listing_id: str,
    order_id: str,
    start_date: date,
    end_date: date,
) -> Reservation:
    overlap_exists = await Reservation.filter(
        listing_id=listing_id,
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).exists()
    if overlap_exists:
        raise AppValidationError("Cannot approve: overlapping reservation exists for this listing")
    return await Reservation.create(
        id=uuid4(),
        listing_id=listing_id,
        order_id=order_id,
        start_date=start_date,
        end_date=end_date,
    )


async def delete_reservation_by_order(order_id: str) -> bool:
    deleted_count = await Reservation.filter(order_id=order_id).delete()
    return deleted_count > 0


async def list_future_reservations(
    *,
    listing_id: str,
    today: date | None = None,
) -> list[Reservation]:
    if today is None:
        today = datetime.now(UTC).date()
    return await Reservation.filter(
        listing_id=listing_id,
        end_date__gte=today,
    ).order_by("start_date")
