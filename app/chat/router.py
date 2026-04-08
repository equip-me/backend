from typing import Annotated

from fastapi import APIRouter, Depends

from app.chat import service
from app.chat.dependencies import require_chat_participant_org, require_chat_participant_user
from app.chat.schemas import ChatStatusResponse, MessageRead
from app.core.pagination import CursorParams, PaginatedResponse
from app.orders.models import Order
from app.users.models import User

router = APIRouter(prefix="/api/v1", tags=["Chat"])


# --- User (renter) endpoints ---


@router.get("/orders/{order_id}/chat/messages", response_model=PaginatedResponse[MessageRead])
async def get_user_chat_messages(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_user)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MessageRead]:
    order, _user = participant
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.get_messages(order, params, side="requester")


@router.get("/orders/{order_id}/chat/status", response_model=ChatStatusResponse)
async def get_user_chat_status(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_user)],
) -> ChatStatusResponse:
    order, user = participant
    return await service.compute_chat_status_for_order(order, user)


# --- Organization endpoints ---


@router.get(
    "/organizations/{org_id}/orders/{order_id}/chat/messages",
    response_model=PaginatedResponse[MessageRead],
)
async def get_org_chat_messages(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_org)],
    cursor: str | None = None,
    limit: int = 20,
) -> PaginatedResponse[MessageRead]:
    order, _user = participant
    params = CursorParams(cursor=cursor, limit=limit)
    return await service.get_messages(order, params, side="organization")


@router.get(
    "/organizations/{org_id}/orders/{order_id}/chat/status",
    response_model=ChatStatusResponse,
)
async def get_org_chat_status(
    participant: Annotated[tuple[Order, User], Depends(require_chat_participant_org)],
) -> ChatStatusResponse:
    order, user = participant
    return await service.compute_chat_status_for_order(order, user)
