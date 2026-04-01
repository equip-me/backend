from typing import Any, ClassVar
from uuid import uuid4

from tortoise import fields
from tortoise.models import Model

from app.core.enums import MediaContext, MediaKind, MediaOwnerType, MediaStatus


class Media(Model):
    id = fields.UUIDField(primary_key=True, default=uuid4)
    uploaded_by: Any = fields.ForeignKeyField("models.User", related_name="uploaded_media")
    owner_type = fields.CharEnumField(MediaOwnerType, max_length=20, null=True)
    owner_id = fields.CharField(max_length=36, null=True)
    kind = fields.CharEnumField(MediaKind, max_length=20)
    context = fields.CharEnumField(MediaContext, max_length=20)
    status = fields.CharEnumField(MediaStatus, max_length=20, default=MediaStatus.PENDING_UPLOAD)
    original_filename = fields.CharField(max_length=255)
    content_type = fields.CharField(max_length=128)
    file_size = fields.IntField()
    position = fields.SmallIntField(default=0)
    upload_key = fields.CharField(max_length=512)
    variants: Any = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)
    processed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "media"
        ordering: ClassVar[list[str]] = ["position", "-created_at"]
