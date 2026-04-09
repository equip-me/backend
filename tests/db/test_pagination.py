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


async def test_paginate_ascending_ordering(create_user: Any) -> None:
    for i in range(5):
        await create_user(email=f"asc{i}@example.com", phone=f"+7999300000{i}")

    items1, cursor1, has_more1 = await paginate(
        User.all(),
        CursorParams(limit=3),
        ordering=("created_at", "id"),
    )
    assert len(items1) == 3
    assert has_more1 is True
    assert cursor1 is not None

    items2, _cursor2, has_more2 = await paginate(
        User.all(),
        CursorParams(cursor=cursor1, limit=3),
        ordering=("created_at", "id"),
    )
    assert len(items2) == 2
    assert has_more2 is False

    # Ascending: first page should have earliest created_at
    assert items1[0].created_at <= items1[-1].created_at
    # No overlap
    all_ids = [u.id for u in items1] + [u.id for u in items2]
    assert len(all_ids) == len(set(all_ids))


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


async def test_paginate_custom_ordering_cursor_correctness(create_user: Any) -> None:
    """Verify cursor pagination produces correct results with non-default ordering."""
    emails = [f"user{i:02d}@example.com" for i in range(7)]
    for i, email in enumerate(emails):
        await create_user(email=email, phone=f"+7999400000{i}")

    # Sort by email ascending — cursor must encode email + id
    all_items: list[Any] = []
    cursor: str | None = None

    for _ in range(10):  # safety limit
        items, cursor, has_more = await paginate(
            User.all(),
            CursorParams(cursor=cursor, limit=3),
            ordering=("email", "id"),
        )
        all_items.extend(items)
        if not has_more:
            break

    assert len(all_items) == 7
    all_emails = [u.email for u in all_items]
    assert all_emails == sorted(all_emails), f"Expected sorted emails, got {all_emails}"
    all_ids = [u.id for u in all_items]
    assert len(all_ids) == len(set(all_ids)), "Duplicate items across pages"


async def test_paginate_descending_custom_field_cursor(create_user: Any) -> None:
    """Verify cursor pagination works with descending custom field ordering."""
    for i in range(5):
        await create_user(
            email=f"desc{i}@example.com",
            phone=f"+7999500000{i}",
            surname=f"Surname{i:02d}",
        )

    items1, cursor1, has_more1 = await paginate(
        User.all(),
        CursorParams(limit=2),
        ordering=("-surname", "-id"),
    )
    assert len(items1) == 2
    assert has_more1 is True
    assert cursor1 is not None

    items2, cursor2, _has_more2 = await paginate(
        User.all(),
        CursorParams(cursor=cursor1, limit=2),
        ordering=("-surname", "-id"),
    )
    assert len(items2) == 2

    items3, _cursor3, has_more3 = await paginate(
        User.all(),
        CursorParams(cursor=cursor2, limit=2),
        ordering=("-surname", "-id"),
    )
    assert len(items3) == 1
    assert has_more3 is False

    all_surnames = [u.surname for u in items1 + items2 + items3]
    assert all_surnames == sorted(all_surnames, reverse=True)
    all_ids = [u.id for u in items1 + items2 + items3]
    assert len(all_ids) == len(set(all_ids))
