from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise, connections

from app.chat.pubsub import close_redis, init_redis
from app.core.config import get_settings
from app.core.database import get_tortoise_config
from app.core.enums import OrganizationStatus, UserRole
from app.listings.models import ListingCategory
from app.main import app
from app.media.storage import init_storage
from app.organizations.models import Organization
from app.users.models import User

_TEST_TABLES = (
    "chat_messages",
    "media",
    "reservations",
    "orders",
    "listings",
    "listing_categories",
    "memberships",
    "organization_contacts",
    "payment_details",
    "organizations",
    "users",
)


@pytest.fixture(scope="session", autouse=True)
async def initialize_db() -> AsyncGenerator[None]:
    config = get_tortoise_config()
    await Tortoise.init(config=config)
    conn = connections.get("default")
    for table in _TEST_TABLES:
        await conn.execute_query(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
    await Tortoise.generate_schemas()

    settings = get_settings()
    storage = init_storage(
        endpoint_url=settings.storage.endpoint_url,
        presigned_endpoint_url=settings.storage.presigned_endpoint_url,
        access_key=settings.storage.access_key,
        secret_key=settings.storage.secret_key,
        bucket=settings.storage.bucket,
    )
    await storage.ensure_bucket()
    await init_redis(settings.worker.redis_url)

    yield
    await close_redis()
    await Tortoise.close_connections()


@pytest.fixture(autouse=True)
async def truncate_tables() -> None:
    conn = connections.get("default")
    for table in _TEST_TABLES:
        await conn.execute_query(f'TRUNCATE TABLE "{table}" CASCADE;')


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _default_user_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "email": "test@example.com",
        "password": "StrongPass1",
        "phone": "+79991234567",
        "name": "Иван",
        "surname": "Иванов",
    }
    data.update(overrides)
    return data


@pytest.fixture
async def create_user(client: AsyncClient) -> Any:
    async def _create(**overrides: Any) -> tuple[dict[str, Any], str]:
        data = _default_user_data(**overrides)
        resp = await client.post("/api/v1/users/", json=data)
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        me_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        return me_resp.json(), token

    return _create


@pytest.fixture
async def admin_user(create_user: Any) -> tuple[dict[str, Any], str]:
    user_data, token = await create_user(email="admin@example.com")
    user_id: str = user_data["id"]
    await User.filter(id=user_id).update(role=UserRole.ADMIN)
    return user_data, token


@pytest.fixture
async def owner_user(create_user: Any) -> tuple[dict[str, Any], str]:
    user_data, token = await create_user(email="owner@example.com")
    user_id: str = user_data["id"]
    await User.filter(id=user_id).update(role=UserRole.OWNER)
    return user_data, token


def _default_org_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "inn": "7707083893",
        "contacts": [
            {
                "display_name": "Иван Иванов",
                "phone": "+79991234567",
                "email": "contact@example.com",
            },
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
async def create_organization(client: AsyncClient, create_user: Any) -> Any:
    async def _create(
        token: str | None = None,
        **overrides: Any,
    ) -> tuple[dict[str, Any], str]:
        if token is None:
            _, token = await create_user(email="orgcreator@example.com")
        data = _default_org_data(**overrides)
        resp = await client.post(
            "/api/v1/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        return resp.json(), token

    return _create


@pytest.fixture
async def create_category() -> Any:
    async def _create(
        name: str = "Test Category",
        organization: Any = None,
        user: Any = None,
        *,
        verified: bool = False,
    ) -> ListingCategory:
        return await ListingCategory.create(
            name=name,
            organization=organization,
            added_by=user,
            verified=verified,
        )

    return _create


@pytest.fixture
async def seed_categories() -> list[ListingCategory]:
    categories = []
    for name in ["Спецтехника", "Промышленное оборудование"]:
        cat = await ListingCategory.create(name=name, verified=True)
        categories.append(cat)
    return categories


@pytest.fixture
async def verified_org(create_organization: Any) -> tuple[dict[str, Any], str]:
    org_data, creator_token = await create_organization()
    org_id = org_data["id"]
    await Organization.filter(id=org_id).update(status=OrganizationStatus.VERIFIED)
    return org_data, creator_token


@pytest.fixture
async def create_listing(
    client: AsyncClient,
    verified_org: tuple[dict[str, Any], str],
    seed_categories: list[ListingCategory],
) -> tuple[str, str, str]:
    """Create a published listing in a verified org. Returns (listing_id, org_id, org_admin_token)."""
    org_data, org_token = verified_org
    org_id = org_data["id"]
    category_id = seed_categories[0].id

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/listings/",
        json={
            "name": "Excavator CAT 320",
            "category_id": category_id,
            "price": 5000.00,
            "description": "Heavy excavator for rent",
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 201, resp.text
    listing_id = resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/organizations/{org_id}/listings/{listing_id}/status",
        json={"status": "published"},
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    return listing_id, org_id, org_token


@pytest.fixture
async def renter_token(create_user: Any) -> str:
    """Create a separate user to act as the renter. Returns their token."""
    _, token = await create_user(
        email="renter@example.com",
        phone="+79001112233",
        name="Renter",
        surname="Testov",
    )
    return str(token)


@pytest.fixture
async def create_order_for_chat(
    client: AsyncClient,
    create_listing: tuple[str, str, str],
    renter_token: str,
) -> tuple[str, str, str, str]:
    """Create an order in OFFERED status for chat testing.

    Returns (order_id, org_id, org_admin_token, renter_token).
    """
    listing_id, org_id, org_token = create_listing
    tomorrow = (datetime.now(tz=UTC) + timedelta(days=1)).date().isoformat()
    next_week = (datetime.now(tz=UTC) + timedelta(days=7)).date().isoformat()

    resp = await client.post(
        "/api/v1/orders/",
        json={
            "listing_id": listing_id,
            "requested_start_date": tomorrow,
            "requested_end_date": next_week,
        },
        headers={"Authorization": f"Bearer {renter_token}"},
    )
    assert resp.status_code == 201, resp.text
    order_id: str = resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/organizations/{org_id}/orders/{order_id}/offer",
        json={
            "offered_cost": "5000.00",
            "offered_start_date": tomorrow,
            "offered_end_date": next_week,
        },
        headers={"Authorization": f"Bearer {org_token}"},
    )
    assert resp.status_code == 200, resp.text

    return order_id, org_id, org_token, renter_token
