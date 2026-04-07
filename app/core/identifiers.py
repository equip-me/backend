import secrets
import string
from typing import Any

from tortoise.exceptions import IntegrityError
from tortoise.models import Model

from app.core.exceptions import IDGenerationError

SHORT_ID_ALPHABET = string.ascii_uppercase + string.digits
SHORT_ID_LENGTH = 6


def generate_short_id(length: int = SHORT_ID_LENGTH) -> str:
    return "".join(secrets.choice(SHORT_ID_ALPHABET) for _ in range(length))


def _is_pk_collision(exc: IntegrityError) -> bool:
    error_msg = str(exc)
    return "duplicate key" in error_msg and "_pkey" in error_msg


async def create_with_short_id[M: Model](
    model_class: type[M],
    max_retries: int = 5,
    **kwargs: Any,
) -> M:
    last_exc: IntegrityError | None = None
    for _ in range(max_retries):
        kwargs["id"] = generate_short_id()
        try:
            return await model_class.create(**kwargs)
        except IntegrityError as e:
            if _is_pk_collision(e):
                last_exc = e
                continue
            raise
    msg = f"Failed to generate unique ID for {model_class.__name__} after {max_retries} attempts"
    raise IDGenerationError(msg, code="server.internal_error") from last_exc
