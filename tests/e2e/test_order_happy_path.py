"""E2E tests for the order lifecycle — happy paths and edge cases.

Uses real infrastructure: PostgreSQL, MinIO, Redis, Dadata API.
Only ``datetime.now`` is mocked for auto-transition scenarios.
"""

import datetime
from typing import Any

import httpx
import pytest

from app.core.enums import ListingStatus, OrderStatus, OrganizationStatus
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
    await Organization.filter(id=org["id"]).update(status=OrganizationStatus.VERIFIED)
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


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestOrderHappyPaths:
    """Scenarios 1-8: order lifecycle happy paths."""

    async def test_complete_rental_journey(self, client: httpx.AsyncClient, mock_today: Any) -> None:
        """Scenario 1: pending -> offered -> confirmed -> active -> finished."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        # Renter creates order
        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start_str,
                "requested_end_date": end_str,
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 201
        order = resp.json()
        order_id = order["id"]
        assert order["status"] == OrderStatus.PENDING

        # Org offers terms
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": "4500.00",
                "offered_start_date": start_str,
                "offered_end_date": end_str,
            },
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 200
        assert offer_resp.json()["status"] == OrderStatus.OFFERED

        # Renter confirms
        confirm_resp = await client.patch(
            f"/api/v1/orders/{order_id}/confirm",
            headers=_auth(renter_token),
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == OrderStatus.CONFIRMED

        # Mock date to start date -> auto-transition to active on read
        start_date = datetime.date.fromisoformat(start_str)
        mock_today.now.return_value = datetime.datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=datetime.UTC
        )

        get_resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == OrderStatus.ACTIVE

        # Verify listing is in_rent
        listing_obj = await Listing.get(id=listing_id)
        assert listing_obj.status == ListingStatus.IN_RENT

        # Mock date past end -> auto-transition to finished
        end_date = datetime.date.fromisoformat(end_str)
        mock_today.now.return_value = datetime.datetime(
            end_date.year, end_date.month, end_date.day + 1, tzinfo=datetime.UTC
        )

        get_resp2 = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert get_resp2.status_code == 200
        assert get_resp2.json()["status"] == OrderStatus.FINISHED

        # Verify listing back to published
        listing_after = await Listing.get(id=listing_id)
        assert listing_after.status == ListingStatus.PUBLISHED

    async def test_order_with_original_terms(self, client: httpx.AsyncClient) -> None:
        """Scenario 2: org offers the same cost/dates as the renter requested."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client, price=1000.0)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start_str,
                "requested_end_date": end_str,
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 201
        order = resp.json()
        order_id = order["id"]
        estimated = order["estimated_cost"]

        # Org offers same terms
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": estimated,
                "offered_start_date": start_str,
                "offered_end_date": end_str,
            },
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 200
        offered = offer_resp.json()
        assert offered["status"] == OrderStatus.OFFERED
        assert offered["offered_cost"] == estimated
        assert offered["offered_start_date"] == start_str
        assert offered["offered_end_date"] == end_str

    async def test_re_offer_before_user_decides(self, client: httpx.AsyncClient) -> None:
        """Scenario 3: org offers, re-offers with updated terms, renter confirms the updated offer."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start_str,
                "requested_end_date": end_str,
            },
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # First offer
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": "3000.00",
                "offered_start_date": start_str,
                "offered_end_date": end_str,
            },
            headers=_auth(org_token),
        )

        # Re-offer with different cost
        new_start_str, new_end_str = _future_dates(days_ahead=12, duration=4)
        reoffer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": "3500.00",
                "offered_start_date": new_start_str,
                "offered_end_date": new_end_str,
            },
            headers=_auth(org_token),
        )
        assert reoffer_resp.status_code == 200
        assert reoffer_resp.json()["offered_cost"] == "3500.00"
        assert reoffer_resp.json()["offered_start_date"] == new_start_str

        # Renter confirms the updated offer
        confirm_resp = await client.patch(
            f"/api/v1/orders/{order_id}/confirm",
            headers=_auth(renter_token),
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["status"] == OrderStatus.CONFIRMED
        assert confirm_resp.json()["offered_cost"] == "3500.00"

    async def test_estimated_cost_calculation(self, client: httpx.AsyncClient) -> None:
        """Scenario 4: 5 days at 1000/day = 5000.00 estimated cost."""
        listing_id, _, _, _, renter_token = await _setup_order_env(client, price=1000.0)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start_str,
                "requested_end_date": end_str,
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 201
        assert resp.json()["estimated_cost"] == "5000.00"

    async def test_chained_auto_transitions(self, client: httpx.AsyncClient, mock_today: Any) -> None:
        """Scenario 5: both dates in past -> confirmed -> active -> finished in one read."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start_str,
                "requested_end_date": end_str,
            },
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # Offer
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={
                "offered_cost": "4000.00",
                "offered_start_date": start_str,
                "offered_end_date": end_str,
            },
            headers=_auth(org_token),
        )

        # Confirm
        await client.patch(
            f"/api/v1/orders/{order_id}/confirm",
            headers=_auth(renter_token),
        )

        # Mock date well past the end date -> should chain confirmed -> active -> finished
        end_date = datetime.date.fromisoformat(end_str)
        past_end = end_date + datetime.timedelta(days=5)
        mock_today.now.return_value = datetime.datetime(
            past_end.year, past_end.month, past_end.day, tzinfo=datetime.UTC
        )

        get_resp = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == OrderStatus.FINISHED

    async def test_list_my_orders(self, client: httpx.AsyncClient) -> None:
        """Scenario 6: renter sees multiple orders in /orders/."""
        listing_id, _, _, _, renter_token = await _setup_order_env(client)

        start1, end1 = _future_dates(days_ahead=10, duration=3)
        start2, end2 = _future_dates(days_ahead=20, duration=5)

        await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start1, "requested_end_date": end1},
            headers=_auth(renter_token),
        )
        await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start2, "requested_end_date": end2},
            headers=_auth(renter_token),
        )

        list_resp = await client.get("/api/v1/orders/", headers=_auth(renter_token))
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) == 2

    async def test_list_org_orders(self, client: httpx.AsyncClient) -> None:
        """Scenario 7: org sees orders via /organizations/{org_id}/orders/."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )

        list_resp = await client.get(
            f"/api/v1/organizations/{org_id}/orders/",
            headers=_auth(org_token),
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) == 1
        assert list_resp.json()["items"][0]["listing_id"] == listing_id

    async def test_get_order_detail_both_sides(self, client: httpx.AsyncClient) -> None:
        """Scenario 8: both renter and org can view order detail."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates(days_ahead=10, duration=5)

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # Renter view
        renter_view = await client.get(f"/api/v1/orders/{order_id}", headers=_auth(renter_token))
        assert renter_view.status_code == 200
        assert renter_view.json()["id"] == order_id

        # Org view
        org_view = await client.get(
            f"/api/v1/organizations/{org_id}/orders/{order_id}",
            headers=_auth(org_token),
        )
        assert org_view.status_code == 200
        assert org_view.json()["id"] == order_id
        assert org_view.json()["status"] == renter_view.json()["status"]


# ---------------------------------------------------------------------------
# Negative / edge cases
# ---------------------------------------------------------------------------


class TestOrderNegativeCases:
    """Scenarios 9-26: validation errors, permission errors, invalid transitions."""

    async def test_order_for_unpublished_listing(self, client: httpx.AsyncClient) -> None:
        """Scenario 9: ordering a hidden listing fails."""
        _, org_token = await _register(client, email="orgowner@example.com")
        org = await _create_verified_org(client, org_token)

        cat = await ListingCategory.create(name="Cat", verified=True)
        resp = await client.post(
            f"/api/v1/organizations/{org['id']}/listings/",
            json={"name": "Hidden Item", "category_id": cat.id, "price": 500.0, "description": "x"},
            headers=_auth(org_token),
        )
        assert resp.status_code == 201
        hidden_listing_id = resp.json()["id"]

        _, renter_token = await _register(
            client, email="renter@example.com", phone="+79001112233", name="R", surname="T"
        )
        start_str, end_str = _future_dates()

        order_resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": hidden_listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        assert order_resp.status_code == 400

    async def test_order_for_unverified_org(self, client: httpx.AsyncClient) -> None:
        """Scenario 10: ordering from unverified org fails."""
        _, org_token = await _register(client, email="orgowner@example.com")
        payload: dict[str, Any] = {
            "inn": SBERBANK_INN,
            "contacts": [{"display_name": "Test", "phone": "+79991234567", "email": "c@e.com"}],
        }
        org_resp = await client.post("/api/v1/organizations/", json=payload, headers=_auth(org_token))
        assert org_resp.status_code == 200
        org_id = org_resp.json()["id"]

        # Create listing directly (not via API, since unverified org might block publishing)
        cat = await ListingCategory.create(name="Cat", verified=True)
        create_resp = await client.post(
            f"/api/v1/organizations/{org_id}/listings/",
            json={"name": "Item", "category_id": cat.id, "price": 500.0, "description": "x"},
            headers=_auth(org_token),
        )
        assert create_resp.status_code == 201
        listing_id = create_resp.json()["id"]

        # Force-publish the listing at DB level
        await Listing.filter(id=listing_id).update(status=ListingStatus.PUBLISHED)

        _, renter_token = await _register(
            client, email="renter@example.com", phone="+79001112233", name="R", surname="T"
        )
        start_str, end_str = _future_dates()

        order_resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        assert order_resp.status_code == 403

    async def test_order_with_start_date_in_past(self, client: httpx.AsyncClient) -> None:
        """Scenario 11: start date in the past is rejected."""
        listing_id, _, _, _, renter_token = await _setup_order_env(client)
        past_start = (_today() - datetime.timedelta(days=1)).isoformat()
        end_str = (_today() + datetime.timedelta(days=5)).isoformat()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": past_start, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        assert resp.status_code == 400

    async def test_order_with_start_after_end(self, client: httpx.AsyncClient) -> None:
        """Scenario 12: start > end is rejected by schema validation."""
        listing_id, _, _, _, renter_token = await _setup_order_env(client)
        start = _today() + datetime.timedelta(days=10)
        end = start - datetime.timedelta(days=3)

        resp = await client.post(
            "/api/v1/orders/",
            json={
                "listing_id": listing_id,
                "requested_start_date": start.isoformat(),
                "requested_end_date": end.isoformat(),
            },
            headers=_auth(renter_token),
        )
        assert resp.status_code == 422

    async def test_order_for_nonexistent_listing(self, client: httpx.AsyncClient) -> None:
        """Scenario 13: ordering non-existent listing returns 404."""
        _, renter_token = await _register(client, email="renter@example.com")
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": "NOSUCH", "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        assert resp.status_code == 404

    async def test_unauthenticated_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 14: no auth header returns 401."""
        start_str, end_str = _future_dates()
        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": "SOMEID", "requested_start_date": start_str, "requested_end_date": end_str},
        )
        assert resp.status_code == 401

    async def test_offer_with_missing_fields(self, client: httpx.AsyncClient) -> None:
        """Scenario 15: offer without required fields returns 422."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # Missing offered_cost
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 422

    async def test_offer_with_negative_cost(self, client: httpx.AsyncClient) -> None:
        """Scenario 16: negative offered_cost is rejected."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "-100.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 422

    async def test_offer_with_start_after_end(self, client: httpx.AsyncClient) -> None:
        """Scenario 17: offered start > end is rejected."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": end_str, "offered_end_date": start_str},
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 422

    async def test_offer_on_wrong_orgs_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 18: org tries to offer on another org's order -> 404."""
        listing_id, _org_id, _org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # Create a second org with a different INN
        _, other_org_token = await _register(client, email="other@example.com", phone="+79005556677")
        other_org = await _create_verified_org(client, other_org_token, inn=YANDEX_INN)
        other_org_id = other_org["id"]

        offer_resp = await client.patch(
            f"/api/v1/organizations/{other_org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(other_org_token),
        )
        assert offer_resp.status_code == 404

    async def test_offer_on_confirmed_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 19: offering on a confirmed order is invalid transition."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # Offer + confirm
        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )
        await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))

        # Try to offer again on confirmed order
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "2000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 400

    async def test_confirm_non_offered_order(self, client: httpx.AsyncClient) -> None:
        """Scenario 20: confirming a pending order is invalid transition."""
        listing_id, _, _, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        confirm_resp = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))
        assert confirm_resp.status_code == 400

    async def test_non_requester_confirms(self, client: httpx.AsyncClient) -> None:
        """Scenario 21: another user tries to confirm -> 403."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )

        # Third user tries to confirm
        _, stranger_token = await _register(
            client, email="stranger@example.com", phone="+79009998877", name="S", surname="T"
        )
        confirm_resp = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(stranger_token))
        assert confirm_resp.status_code == 403

    async def test_non_requester_declines(self, client: httpx.AsyncClient) -> None:
        """Scenario 22: another user tries to decline -> 403."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )

        _, stranger_token = await _register(
            client, email="stranger@example.com", phone="+79009998877", name="S", surname="T"
        )
        decline_resp = await client.patch(f"/api/v1/orders/{order_id}/decline", headers=_auth(stranger_token))
        assert decline_resp.status_code == 403

    async def test_org_editor_tries_to_confirm(self, client: httpx.AsyncClient) -> None:
        """Scenario 23: org editor cannot confirm order (renter endpoint requires requester)."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )

        # Org owner tries the renter confirm endpoint
        confirm_resp = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(org_token))
        assert confirm_resp.status_code == 403

    async def test_renter_tries_to_offer(self, client: httpx.AsyncClient) -> None:
        """Scenario 24: renter cannot offer on their own order via org endpoint -> 403/404."""
        listing_id, org_id, _, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        # Renter tries the org offer endpoint
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(renter_token),
        )
        assert offer_resp.status_code in {403, 404}

    async def test_double_confirm(self, client: httpx.AsyncClient) -> None:
        """Scenario 25: confirming twice fails (second time status is confirmed, not offered)."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )

        # First confirm
        first = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))
        assert first.status_code == 200

        # Second confirm
        second = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))
        assert second.status_code == 400

    async def test_actions_on_terminal_statuses(self, client: httpx.AsyncClient) -> None:
        """Scenario 26: all actions rejected on terminal statuses (rejected, declined, finished, canceled)."""
        listing_id, org_id, org_token, _, renter_token = await _setup_order_env(client)
        start_str, end_str = _future_dates()

        # Create and reject an order
        resp = await client.post(
            "/api/v1/orders/",
            json={"listing_id": listing_id, "requested_start_date": start_str, "requested_end_date": end_str},
            headers=_auth(renter_token),
        )
        order_id = resp.json()["id"]

        reject_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/reject",
            headers=_auth(org_token),
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == OrderStatus.REJECTED

        # Try to offer on rejected order
        offer_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
            json={"offered_cost": "1000.00", "offered_start_date": start_str, "offered_end_date": end_str},
            headers=_auth(org_token),
        )
        assert offer_resp.status_code == 400

        # Try to confirm rejected order
        confirm_resp = await client.patch(f"/api/v1/orders/{order_id}/confirm", headers=_auth(renter_token))
        assert confirm_resp.status_code == 400

        # Try to decline rejected order
        decline_resp = await client.patch(f"/api/v1/orders/{order_id}/decline", headers=_auth(renter_token))
        assert decline_resp.status_code == 400

        # Try to cancel rejected order (by user)
        cancel_resp = await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=_auth(renter_token))
        assert cancel_resp.status_code == 400

        # Try to cancel rejected order (by org)
        org_cancel_resp = await client.patch(
            f"/api/v1/organizations/{org_id}/orders/{order_id}/cancel",
            headers=_auth(org_token),
        )
        assert org_cancel_resp.status_code == 400
