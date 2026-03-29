from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.dependencies import require_active_user
from app.media import service
from app.media.schemas import UploadUrlRequest, UploadUrlResponse
from app.media.storage import StorageClient, get_storage
from app.users.models import User

router = APIRouter(tags=["media"])


@router.post("/media/upload-url", response_model=UploadUrlResponse)
async def request_upload_url(
    data: UploadUrlRequest,
    user: Annotated[User, Depends(require_active_user)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> UploadUrlResponse:
    return await service.request_upload_url(data, user, storage)
