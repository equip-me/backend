from datetime import date

import pytest

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError
from app.orders.state_machine import maybe_auto_transition, transition


class TestTransition:
    def test_pending_to_offered(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_pending_to_rejected(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.REJECT_BY_ORG) == OrderStatus.REJECTED

    def test_offered_to_offered(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_offered_to_confirmed(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.CONFIRM_BY_USER) == OrderStatus.CONFIRMED

    def test_offered_to_declined(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.DECLINE_BY_USER) == OrderStatus.DECLINED

    def test_confirmed_to_active(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.ACTIVATE) == OrderStatus.ACTIVE

    def test_confirmed_cancel_by_user(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_confirmed_cancel_by_org(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_active_to_finished(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.FINISH) == OrderStatus.FINISHED

    def test_active_cancel_by_user(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_active_cancel_by_org(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.FINISHED, OrderAction.OFFER_BY_ORG)

    def test_invalid_transition_from_rejected(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.REJECTED, OrderAction.CONFIRM_BY_USER)

    def test_invalid_transition_from_declined(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.DECLINED, OrderAction.OFFER_BY_ORG)

    def test_invalid_transition_pending_confirm(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.PENDING, OrderAction.CONFIRM_BY_USER)


class TestMaybeAutoTransition:
    def test_confirmed_activates_on_start_date(self) -> None:
        today = date(2026, 4, 1)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.ACTIVE

    def test_confirmed_activates_after_start_date(self) -> None:
        today = date(2026, 4, 5)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.ACTIVE

    def test_confirmed_no_transition_before_start(self) -> None:
        today = date(2026, 3, 31)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result is None

    def test_active_finishes_after_end_date(self) -> None:
        today = date(2026, 4, 11)
        result = maybe_auto_transition(
            status=OrderStatus.ACTIVE,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.FINISHED

    def test_active_no_transition_on_end_date(self) -> None:
        today = date(2026, 4, 10)
        result = maybe_auto_transition(
            status=OrderStatus.ACTIVE,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result is None

    def test_chained_confirmed_to_finished(self) -> None:
        today = date(2026, 4, 15)
        result = maybe_auto_transition(
            status=OrderStatus.CONFIRMED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result == OrderStatus.FINISHED

    def test_pending_no_transition(self) -> None:
        today = date(2026, 4, 5)
        result = maybe_auto_transition(
            status=OrderStatus.PENDING,
            offered_start_date=None,
            offered_end_date=None,
            today=today,
        )
        assert result is None

    def test_offered_no_transition(self) -> None:
        today = date(2026, 4, 5)
        result = maybe_auto_transition(
            status=OrderStatus.OFFERED,
            offered_start_date=date(2026, 4, 1),
            offered_end_date=date(2026, 4, 10),
            today=today,
        )
        assert result is None
