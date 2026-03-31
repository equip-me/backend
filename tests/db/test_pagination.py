from typing import Any

from app.core.pagination import CursorParams, paginate
from app.users.models import User


async def test_paginate_returns_first_page(create_user: Any) -> None:
    for i in range(5):
        await create_user(email=f"page{i}@example.com", phone=f"+7999000000{i}")

    items, next_cursor, has_more = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("-created_at", "-id"),
    )
    assert len(items) == 3
    assert has_more is True
    assert next_cursor is not None


async def test_paginate_second_page_uses_cursor(create_user: Any) -> None:
    for i in range(5):
        await create_user(email=f"cur{i}@example.com", phone=f"+7999100000{i}")

    items1, cursor1, _ = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("-created_at", "-id"),
    )
    assert cursor1 is not None

    items2, cursor2, has_more2 = await paginate(
        User.all(),
        CursorParams(cursor=cursor1, limit=3),
        ordering=("-created_at", "-id"),
    )
    assert len(items2) == 2
    assert has_more2 is False
    assert cursor2 is None

    all_ids = [u.id for u in items1] + [u.id for u in items2]
    assert len(all_ids) == len(set(all_ids)), "Pages must not overlap"


async def test_paginate_empty_queryset() -> None:
    items, cursor, has_more = await paginate(
        User.all(),
        CursorParams(limit=10),
        ordering=("-created_at", "-id"),
    )
    assert items == []
    assert cursor is None
    assert has_more is False


async def test_paginate_exact_page_size(create_user: Any) -> None:
    for i in range(3):
        await create_user(email=f"exact{i}@example.com", phone=f"+7999200000{i}")

    items, cursor, has_more = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("-created_at", "-id"),
    )
    assert len(items) == 3
    assert has_more is False
    assert cursor is None
