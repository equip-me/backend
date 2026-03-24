from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from app.core.database import get_tortoise_config
from app.core.enums import UserRole
from app.main import app
from app.users.models import User


@pytest.fixture(scope="session", autouse=True)
async def initialize_db() -> AsyncGenerator[None]:
    config = get_tortoise_config()
    config["connections"]["default"]["credentials"]["database"] = "rental_test"  # type: ignore[index]
    await Tortoise.init(config=config)
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture(autouse=True)
async def truncate_tables() -> None:
    from tortoise import connections

    conn = connections.get("default")
    tables = ["orders", "listings", "listing_categories", "memberships", "organizations", "users"]
    for table in tables:
        await conn.execute_query(f"TRUNCATE TABLE {table} CASCADE;")


@pytest.fixture()
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


@pytest.fixture()
async def create_user(client: AsyncClient) -> Any:
    async def _create(**overrides: Any) -> tuple[dict[str, Any], str]:
        data = _default_user_data(**overrides)
        resp = await client.post("/users/", json=data)
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        me_resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        return me_resp.json(), token

    return _create


@pytest.fixture()
async def admin_user(create_user: Any) -> tuple[dict[str, Any], str]:
    user_data, token = await create_user(email="admin@example.com")
    user_id: UUID = user_data["id"]
    await User.filter(id=user_id).update(role=UserRole.ADMIN)
    return user_data, token


@pytest.fixture()
async def owner_user(create_user: Any) -> tuple[dict[str, Any], str]:
    user_data, token = await create_user(email="owner@example.com")
    user_id: UUID = user_data["id"]
    await User.filter(id=user_id).update(role=UserRole.OWNER)
    return user_data, token
