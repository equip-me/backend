import re
from unittest.mock import patch

import pytest
from tortoise.exceptions import IntegrityError

from app.core.exceptions import IDGenerationError
from app.core.identifiers import create_with_short_id
from app.users.models import User

_SHORT_ID_PATTERN = re.compile(r"^[A-Z0-9]{6}$")


async def test_create_with_short_id_success() -> None:
    user = await create_with_short_id(
        User,
        email="short@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="Test",
        surname="User",
    )
    assert len(user.id) == 6
    assert isinstance(user.id, str)
    assert _SHORT_ID_PATTERN.match(user.id)


async def test_create_with_short_id_retries_on_pk_collision() -> None:
    first = await create_with_short_id(
        User,
        email="first@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="First",
        surname="User",
    )
    with patch(
        "app.core.identifiers.generate_short_id",
        side_effect=[first.id, first.id, "ZZZZZZ"],
    ):
        second = await create_with_short_id(
            User,
            email="second@example.com",
            hashed_password="fakehash",
            phone="+79997654321",
            name="Second",
            surname="User",
        )
    assert second.id == "ZZZZZZ"


async def test_create_with_short_id_propagates_non_pk_error() -> None:
    await create_with_short_id(
        User,
        email="dup@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="First",
        surname="User",
    )
    with pytest.raises(IntegrityError):
        await create_with_short_id(
            User,
            email="dup@example.com",
            hashed_password="fakehash",
            phone="+79997654321",
            name="Second",
            surname="User",
        )


async def test_create_with_short_id_raises_after_max_retries() -> None:
    existing = await create_with_short_id(
        User,
        email="existing@example.com",
        hashed_password="fakehash",
        phone="+79991234567",
        name="Existing",
        surname="User",
    )
    with (
        patch(
            "app.core.identifiers.generate_short_id",
            return_value=existing.id,
        ),
        pytest.raises(IDGenerationError),
    ):
        await create_with_short_id(
            User,
            max_retries=3,
            email="another@example.com",
            hashed_password="fakehash",
            phone="+79997654321",
            name="Another",
            surname="User",
        )
