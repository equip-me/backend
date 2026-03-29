from typing import Annotated
from uuid import UUID

from fastapi import Depends, Path

from app.core.dependencies import require_active_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.media.models import Media
from app.users.models import User


async def resolve_media(
    media_id: Annotated[UUID, Path()],
) -> Media:
    media = await Media.get_or_none(id=media_id).prefetch_related("uploaded_by")
    if media is None:
        raise NotFoundError("Media not found")
    return media


async def require_media_uploader(
    media: Annotated[Media, Depends(resolve_media)],
    user: Annotated[User, Depends(require_active_user)],
) -> Media:
    uploader: User = media.uploaded_by
    if uploader.id != user.id:
        raise PermissionDeniedError("You can only manage your own uploads")
    return media
