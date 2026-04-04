import pytest

from app.core.enums import OrderAction, OrderStatus
from app.core.exceptions import AppValidationError
from app.orders.state_machine import transition


class TestValidTransitions:
    # PENDING transitions
    def test_pending_offer(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_pending_cancel_by_user(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_pending_cancel_by_org(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_pending_expire(self) -> None:
        assert transition(OrderStatus.PENDING, OrderAction.EXPIRE) == OrderStatus.EXPIRED

    # OFFERED transitions
    def test_offered_reoffer(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_offered_accept(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.ACCEPT_BY_USER) == OrderStatus.ACCEPTED

    def test_offered_cancel_by_user(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_offered_cancel_by_org(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_offered_expire(self) -> None:
        assert transition(OrderStatus.OFFERED, OrderAction.EXPIRE) == OrderStatus.EXPIRED

    # ACCEPTED transitions
    def test_accepted_reoffer(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.OFFER_BY_ORG) == OrderStatus.OFFERED

    def test_accepted_approve(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.APPROVE_BY_ORG) == OrderStatus.CONFIRMED

    def test_accepted_cancel_by_user(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_accepted_cancel_by_org(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    def test_accepted_expire(self) -> None:
        assert transition(OrderStatus.ACCEPTED, OrderAction.EXPIRE) == OrderStatus.EXPIRED

    # CONFIRMED transitions
    def test_confirmed_activate(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.ACTIVATE) == OrderStatus.ACTIVE

    def test_confirmed_cancel_by_user(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_confirmed_cancel_by_org(self) -> None:
        assert transition(OrderStatus.CONFIRMED, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION

    # ACTIVE transitions
    def test_active_finish(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.FINISH) == OrderStatus.FINISHED

    def test_active_cancel_by_user(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_USER) == OrderStatus.CANCELED_BY_USER

    def test_active_cancel_by_org(self) -> None:
        assert transition(OrderStatus.ACTIVE, OrderAction.CANCEL_BY_ORG) == OrderStatus.CANCELED_BY_ORGANIZATION


class TestTerminalStates:
    @pytest.mark.parametrize(
        "terminal_status",
        [
            OrderStatus.FINISHED,
            OrderStatus.CANCELED_BY_USER,
            OrderStatus.CANCELED_BY_ORGANIZATION,
            OrderStatus.EXPIRED,
        ],
    )
    @pytest.mark.parametrize(
        "action",
        list(OrderAction),
    )
    def test_terminal_states_reject_all_actions(self, terminal_status: OrderStatus, action: OrderAction) -> None:
        with pytest.raises(AppValidationError):
            transition(terminal_status, action)


class TestInvalidTransitions:
    def test_pending_cannot_accept(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.PENDING, OrderAction.ACCEPT_BY_USER)

    def test_pending_cannot_approve(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.PENDING, OrderAction.APPROVE_BY_ORG)

    def test_offered_cannot_approve(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.OFFERED, OrderAction.APPROVE_BY_ORG)

    def test_confirmed_cannot_offer(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.CONFIRMED, OrderAction.OFFER_BY_ORG)

    def test_active_cannot_offer(self) -> None:
        with pytest.raises(AppValidationError):
            transition(OrderStatus.ACTIVE, OrderAction.OFFER_BY_ORG)
