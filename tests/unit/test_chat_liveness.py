from datetime import UTC, datetime, timedelta

import pytest

from app.chat.service import get_chat_status
from app.core.enums import OrderStatus

_NOW = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


class TestGetChatStatus:
    """Tests for get_chat_status(order_status, order_updated_at, last_message_at, cooldown_days, now)."""

    def test_active_order_is_active(self) -> None:
        result = get_chat_status(
            order_status=OrderStatus.PENDING,
            order_updated_at=_NOW - timedelta(days=1),
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    @pytest.mark.parametrize(
        "status",
        [
            OrderStatus.PENDING,
            OrderStatus.OFFERED,
            OrderStatus.CONFIRMED,
            OrderStatus.ACTIVE,
        ],
    )
    def test_non_terminal_statuses_are_active(self, status: OrderStatus) -> None:
        result = get_chat_status(
            order_status=status,
            order_updated_at=_NOW,
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    def test_terminal_within_cooldown_with_message(self) -> None:
        last_msg = _NOW - timedelta(days=3)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=5),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    def test_terminal_past_cooldown_with_message(self) -> None:
        last_msg = _NOW - timedelta(days=10)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=12),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    def test_terminal_no_messages_within_cooldown(self) -> None:
        result = get_chat_status(
            order_status=OrderStatus.REJECTED,
            order_updated_at=_NOW - timedelta(days=3),
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"

    def test_terminal_no_messages_past_cooldown(self) -> None:
        result = get_chat_status(
            order_status=OrderStatus.REJECTED,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=None,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    @pytest.mark.parametrize(
        "status",
        [
            OrderStatus.FINISHED,
            OrderStatus.REJECTED,
            OrderStatus.DECLINED,
            OrderStatus.CANCELED_BY_USER,
            OrderStatus.CANCELED_BY_ORGANIZATION,
        ],
    )
    def test_all_terminal_statuses_respect_cooldown(self, status: OrderStatus) -> None:
        last_msg = _NOW - timedelta(days=8)
        result = get_chat_status(
            order_status=status,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    def test_cooldown_boundary_exact(self) -> None:
        last_msg = _NOW - timedelta(days=7)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "read_only"

    def test_cooldown_boundary_just_before(self) -> None:
        last_msg = _NOW - timedelta(days=7) + timedelta(seconds=1)
        result = get_chat_status(
            order_status=OrderStatus.FINISHED,
            order_updated_at=_NOW - timedelta(days=10),
            last_message_at=last_msg,
            cooldown_days=7,
            now=_NOW,
        )
        assert result == "active"
