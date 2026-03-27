from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise, connections

from app.core.database import get_tortoise_config
from app.core.enums import UserRole
from app.main import app
from app.organizations.dependencies import get_dadata_client
from app.users.models import User

_TEST_TABLES = (
    "orders",
    "listings",
    "listing_categories",
    "memberships",
    "organization_contacts",
    "payment_details",
    "organizations",
    "users",
)

DADATA_PARTY_RESPONSE = {
    "value": 'ООО "РОГА И КОПЫТА"',
    "data": {
        "inn": "7707083893",
        "name": {
            "short_with_opf": 'ООО "Рога и копыта"',
            "full_with_opf": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "РОГА И КОПЫТА"',
        },
        "state": {
            "registration_date": 1029456000000,
        },
        "address": {
            "value": "г Москва, ул Ленина, д 1",
        },
        "management": {
            "name": "Иванов Иван Иванович",
        },
        "okved": "62.01",
    },
}


@pytest.fixture(scope="session", autouse=True)
async def initialize_db() -> AsyncGenerator[None]:
    config = get_tortoise_config()
    await Tortoise.init(config=config)
    conn = connections.get("default")
    for table in _TEST_TABLES:
        await conn.execute_query(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
    await Tortoise.generate_schemas()
    yield
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
        resp = await client.post("/users/", json=data)
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        me_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
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


@pytest.fixture(autouse=True)
def mock_dadata(client: AsyncClient) -> Generator[MagicMock]:  # noqa: ARG001
    mock = MagicMock()
    mock.find_by_id.return_value = [DADATA_PARTY_RESPONSE]
    app.dependency_overrides[get_dadata_client] = lambda: mock
    yield mock
    app.dependency_overrides.pop(get_dadata_client, None)


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
            "/organizations/",
            json=data,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        return resp.json(), token

    return _create
