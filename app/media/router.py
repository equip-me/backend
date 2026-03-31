from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.dependencies import require_active_user
from app.media import service
from app.media.dependencies import require_media_uploader
from app.media.models import Media
from app.media.schemas import MediaStatusResponse, UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient, get_storage
from app.users.models import User

router = APIRouter(prefix="/api/v1/media", tags=["Media"])


@router.post("/upload-url", response_model=UploadUrlResponse)
async def request_upload_url(
    data: UploadUrlRequest,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UploadUrlResponse:
    return await service.request_upload_url(data, user, storage)


@router.get("/{media_id}/status", response_model=MediaStatusResponse)
async def get_media_status(
    media: Annotated[Media, Depends(require_media_uploader)],
) -> MediaStatusResponse:
    return MediaStatusResponse(
        id=media.id,
        status=media.status,
        kind=media.kind,
        context=media.context,
        original_filename=media.original_filename,
        variants=media.variants,
    )


@router.delete("/{media_id}", status_code=204)
async def delete_media(
    media: Annotated[Media, Depends(require_media_uploader)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> Response:
    await service.delete_media(media, storage)
    return Response(status_code=204)


@router.post("/{media_id}/confirm", response_model=MediaStatusResponse)
async def confirm_upload(
    media: Annotated[Media, Depends(require_media_uploader)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> MediaStatusResponse:
    updated = await service.confirm_upload(media, storage)
    return MediaStatusResponse(
        id=updated.id,
        status=updated.status,
        kind=updated.kind,
        context=updated.context,
        original_filename=updated.original_filename,
        variants=updated.variants,
    )


@router.post("/{media_id}/retry", response_model=MediaStatusResponse)
async def retry_media(
    media: Annotated[Media, Depends(require_media_uploader)],
) -> MediaStatusResponse:
    updated = await service.retry_media(media)
    return MediaStatusResponse(
        id=updated.id,
        status=updated.status,
        kind=updated.kind,
        context=updated.context,
        original_filename=updated.original_filename,
        variants=updated.variants,
    )
