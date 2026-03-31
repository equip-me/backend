"""E2E tests for order cancel, reject, and decline flows.

Uses real infrastructure: PostgreSQL, MinIO, Redis, Dadata API.
Only ``datetime.now`` is mocked for active order cancellation scenarios.
"""

import datetime
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.enums import ListingStatus, OrderStatus
from app.listings.models import Listing, ListingCategory
from app.organizations.models import Organization

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SBERBANK_INN = "7707083893"
YANDEX_INN = "7736207543"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: httpx.AsyncClient, **overrides: Any) -> tuple[dict[str, Any], str]:
    defaults: dict[str, Any] = {
        "email": "user@example.com",
        "password": "StrongPass1",
        "phone": "+79991234567",
        "name": "Иван",
        "surname": "Иванов",
    }
    defaults.update(overrides)
    resp = await client.post("/api/v1/users/", json=defaults)
    assert resp.status_code == 200, resp.text
    token: str = resp.json()["access_token"]
    me = await client.get("/api/v1/users/me", headers=_auth(token))
    assert me.status_code == 200, me.text
    return me.json(), token


async def _create_verified_org(client: httpx.AsyncClient, token: str, *, inn: str = SBERBANK_INN) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "inn": inn,
        "contacts": [
            {
                "display_name": "Иван Иванов",
                "phone": "+79991234567",
                "email": "contact@example.com",
            },
        ],
    }
    resp = await client.post("/api/v1/organizations/", json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    org: dict[str, Any] = resp.json()
    await Organization.filter(id=org["id"]).update(status="verified")
    return org


async def _create_published_listing(
    client: httpx.AsyncClient,
    org_id: str,
    token: str,
    *,
    price: float = 1000.0,
) -> dict[str, Any]:
    cat = await ListingCategory.create(name="Test Category", verified=True)
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Excavator CAT 320",
            "category_id": cat.id,
            "price": price,
            "description": "Heavy excavator for rent",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    listing = resp.json()

    patch_resp = await client.patch(
        f"/api/v1/organizations/{org_id}/listings/{listing['id']}/status",
        json={"status": "published"},
        headers=_auth(token),
    )
    assert patch_resp.status_code == 200, patch_resp.text
    result: dict[str, Any] = patch_resp.json()
    return result


async def _setup_order_env(
    client: httpx.AsyncClient,
    *,
    price: float = 1000.0,
) -> tuple[str, str, str, str, str]:
    """Create org owner, verified org, published listing, and renter.

    Returns (listing_id, org_id, org_token, renter_user_id, renter_token).
    """
    _, org_token = await _register(client, email="orgowner@example.com")
    org = await _create_verified_org(client, org_token)
    listing = await _create_published_listing(client, org["id"], org_token, price=price)
    renter_data, renter_token = await _register(
        client, email="renter@example.com", phone="+79001112233", name="Renter", surname="Testov"
    )
    return listing["id"], org["id"], org_token, renter_data["id"], renter_token


def _today() -> datetime.date:
    return datetime.datetime.now(tz=datetime.UTC).date()


def _future_dates(days_ahead: int = 10, duration: int = 5) -> tuple[str, str]:
    start = _today() + datetime.timedelta(days=days_ahead)
    end = start + datetime.timedelta(days=duration - 1)
    return start.isoformat(), end.isoformat()


async def _create_order(
    client: httpx.AsyncClient,
    listing_id: str,
    renter_token: str,
    *,
    days_ahead: int = 10,
    duration: int = 5,
) -> tuple[str, str, str]:
    """Create an order and return (order_id, start_str, end_str)."""
    start_str, end_str = _future_dates(days_ahead=days_ahead, duration=duration)
    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": start_str,
            "requested_end_date": end_str,
        },
        headers=_auth(renter_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], start_str, end_str


async def _advance_to_offered(
    client: httpx.AsyncClient,
    org_id: str,
    org_token: str,
    order_id: str,
    start_str: str,
    end_str: str,
) -> None:
    """Move order from pending to offered."""
    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": "4500.00",
            "offered_start_date": start_str,
            "offered_end_date": end_str,
        },
        headers=_auth(org_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == OrderStatus.OFFERED


async def _advance_to_confirmed(
    client: httpx.AsyncClient,
    org_id: str,
    org_token: str,
    renter_token: str,
    order_id: str,
    start_str: str,
    end_str: str,
) -> None:
    """Move order from pending to confirmed."""
    await _advance_to_offered(client, org_id, org_token, order_id, start_str, end_str)
    resp = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == OrderStatus.CONFIRMED


async def _advance_to_active(
    client: httpx.AsyncClient,
    org_id: str,
    org_token: str,
    renter_token: str,
    order_id: str,
    start_str: str,
    end_str: str,
    mock_today: MagicMock,
) -> None:
    """Move order from pending to active (via confirmed + date mock)."""
    await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)
    start_date = datetime.date.fromisoformat(start_str)
    mock_today.now.return_value = datetime.datetime(
        start_date.year, start_date.month, start_date.day, tzinfo=datetime.UTC
    )
    # Trigger auto-transition by reading the order
    get_resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["status"] == OrderStatus.ACTIVE


# ---------------------------------------------------------------------------
# Happy paths: cancel, reject, decline
# ---------------------------------------------------------------------------


class TestCancelRejectDeclineHappyPaths:
    """Scenarios 1-6: reject, decline, and cancel flows."""

    async def test_org_rejects_pending_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 1: org rejects pending order -> rejected (terminal)."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/reject",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.REJECTED

        # Verify terminal: cannot offer after rejection
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 400

    async def test_user_declines_offered_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 2: user declines offered order -> declined (terminal)."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, org_token, order_id, start_str, end_str)

        resp = await client.patch(f"/api/v1/orders/{order_id}/decline", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.DECLINED

        # Verify terminal: cannot confirm after decline
        confirm_resp = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))
        assert confirm_resp.status_code == 400

    async def test_user_cancels_confirmed_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 3: user cancels confirmed order -> canceled_by_user."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.CANCELED_BY_USER

    async def test_user_cancels_active_order(self, client: httpx.AsyncClient, mock_today: MagicMock) -> None:
        """Scenario 4: user cancels active order -> canceled_by_user, listing back to published."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_active(client, org_id, org_token, renter_token, order_id, start_str, end_str, mock_today)

        # Verify listing is in_rent before cancellation
        listing_obj = await Listing.get(id=listing_id)
        assert listing_obj.status == ListingStatus.IN_RENT

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.CANCELED_BY_USER

        # Verify listing is back to published
        listing_after = await Listing.get(id=listing_id)
        assert listing_after.status == ListingStatus.PUBLISHED

    async def test_org_cancels_confirmed_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 5: org cancels confirmed order -> canceled_by_organization."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.CANCELED_BY_ORGANIZATION

    async def test_org_cancels_active_order(self, client: httpx.AsyncClient, mock_today: MagicMock) -> None:
        """Scenario 6: org cancels active order -> canceled_by_organization, listing back to published."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_active(client, org_id, org_token, renter_token, order_id, start_str, end_str, mock_today)

        # Verify listing is in_rent before cancellation
        listing_obj = await Listing.get(id=listing_id)
        assert listing_obj.status == ListingStatus.IN_RENT

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.CANCELED_BY_ORGANIZATION

        # Verify listing is back to published
        listing_after = await Listing.get(id=listing_id)
        assert listing_after.status == ListingStatus.PUBLISHED


# ---------------------------------------------------------------------------
# Negative / edge cases
# ---------------------------------------------------------------------------


class TestCancelRejectDeclineNegativeCases:
    """Scenarios 7-16: invalid transitions and permission errors."""

    async def test_reject_non_pending_offered(self, client: httpx.AsyncClient) -> None:
        """Scenario 7: reject offered order -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, org_token, order_id, start_str, end_str)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/reject",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400

    async def test_decline_non_offered_pending(self, client: httpx.AsyncClient) -> None:
        """Scenario 8a: decline pending order -> invalid transition."""
        listing_id, _org_id, _org_token, _, renter_token = await _setup_order_env(client)
        order_id, _start_str, _end_str = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(f"/api/v1/orders/{order_id}/decline", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_decline_non_offered_confirmed(self, client: httpx.AsyncClient) -> None:
        """Scenario 8b: decline confirmed order -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        resp = await client.patch(f"/api/v1/orders/{order_id}/decline", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_user_cancel_from_pending(self, client: httpx.AsyncClient) -> None:
        """Scenario 9: user cancel from pending -> invalid transition."""
        listing_id, _org_id, _org_token, _, renter_token = await _setup_order_env(client)
        order_id, _start_str, _end_str = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_user_cancel_from_offered(self, client: httpx.AsyncClient) -> None:
        """Scenario 10: user cancel from offered -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, org_token, order_id, start_str, end_str)

        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 400

    async def test_org_cancel_from_pending(self, client: httpx.AsyncClient) -> None:
        """Scenario 11: org cancel from pending -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, _start_str, _end_str = await _create_order(client, listing_id, renter_token)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400

    async def test_org_cancel_from_offered(self, client: httpx.AsyncClient) -> None:
        """Scenario 12: org cancel from offered -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_offered(client, org_id, org_token, order_id, start_str, end_str)

        resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp.status_code == 400

    async def test_cancel_already_canceled_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 13: cancel already canceled order -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        # Cancel by user
        resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == OrderStatus.CANCELED_BY_USER

        # Try to cancel again by user
        resp2 = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert resp2.status_code == 400

        # Try to cancel by org
        resp3 = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert resp3.status_code == 400

    async def test_cancel_finished_order(self, client: httpx.AsyncClient, mock_today: MagicMock) -> None:
        """Scenario 14: cancel finished order -> invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        # Mock date past end -> auto-transition to finished
        end_date = datetime.date.fromisoformat(end_str)
        past_end = end_date + datetime.timedelta(days=5)
        mock_today.now.return_value = datetime.datetime(
            past_end.year, past_end.month, past_end.day, tzinfo=datetime.UTC
        )

        # Read order to trigger auto-transition to finished
        get_resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == OrderStatus.FINISHED

        # Try to cancel by user
        cancel_resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert cancel_resp.status_code == 400

        # Try to cancel by org
        org_cancel_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert org_cancel_resp.status_code == 400

    async def test_non_requester_cancels(self, client: httpx.AsyncClient) -> None:
        """Scenario 15: non-requester tries to cancel -> 403."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        # Third user tries to cancel via user endpoint
        _, stranger_token = await _register(
            client, email="stranger@example.com", phone="+79009998877", name="S", surname="T"
        )
        cancel_resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(stranger_token))
        assert cancel_resp.status_code == 403

    async def test_wrong_org_cancels(self, client: httpx.AsyncClient) -> None:
        """Scenario 16: wrong org tries to cancel -> 404 (order not found in their scope)."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        order_id, start_str, end_str = await _create_order(client, listing_id, renter_token)
        await _advance_to_confirmed(client, org_id, org_token, renter_token, order_id, start_str, end_str)

        # Create a second org with a different INN
        _, other_org_token = await _register(client, email="other@example.com", phone="+79005556677")
        other_org = await _create_verified_org(client, other_org_token, inn=YANDEX_INN)
        other_org_id = other_org["id"]

        cancel_resp = await client.patch(
            f"/api/v1/organizations/{other_org_id}/orders/{order_id}/cancel",
            headers=_auth(other_org_token),
        )
        assert cancel_resp.status_code == 404
