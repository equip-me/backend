import re
from typing import Any

import jwt as pyjwt
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.enums import UserRole
from app.users.models import User

_SHORT_ID_PATTERN = re.compile(r"^[A-Z0-9]{6}$")


async def test_registered_user_has_short_id(create_user: Any) -> None:
    user_data, _ = await create_user(email="shortid@example.com")
    assert _SHORT_ID_PATTERN.match(user_data["id"]), f"ID {user_data['id']} is not a valid short ID"


async def test_register_returns_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "new@example.com",
            "password": "StrongPass1",
            "phone": "+79991234567",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    me_resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "new@example.com"


async def test_register_duplicate_email(client: AsyncClient, create_user: Any) -> None:
    await create_user(email="dup@example.com")
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "dup@example.com",
            "password": "StrongPass1",
            "phone": "+79997654321",
            "name": "Петр",
            "surname": "Петров",
        },
    )
    assert resp.status_code == 409


async def test_register_weak_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "weak@example.com",
            "password": "short",
            "phone": "+79991234567",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 422


async def test_register_password_no_lowercase(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "nolower@example.com",
            "password": "UPPERCASE1",
            "phone": "+79991234567",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 422


async def test_register_password_no_uppercase(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "noupper@example.com",
            "password": "lowercase1",
            "phone": "+79991234567",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 422


async def test_register_password_no_digit(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "nodigit@example.com",
            "password": "NoDigitsHere",
            "phone": "+79991234567",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 422


async def test_register_invalid_phone(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "phone@example.com",
            "password": "StrongPass1",
            "phone": "12345",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 422


async def test_register_invalid_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "not-an-email",
            "password": "StrongPass1",
            "phone": "+79991234567",
            "name": "Иван",
            "surname": "Иванов",
        },
    )
    assert resp.status_code == 422


async def test_login_success(client: AsyncClient, create_user: Any) -> None:
    await create_user(email="login@example.com", password="StrongPass1")
    resp = await client.post(
        "/api/v1/users/token",
        json={
            "email": "login@example.com",
            "password": "StrongPass1",
        },
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/token",
        json={
            "email": "nobody@example.com",
            "password": "StrongPass1",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"


async def test_login_wrong_password(client: AsyncClient, create_user: Any) -> None:
    await create_user(email="wrongpw@example.com", password="StrongPass1")
    resp = await client.post(
        "/api/v1/users/token",
        json={
            "email": "wrongpw@example.com",
            "password": "WrongPass1",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect username or password"


async def test_login_suspended_user(client: AsyncClient, create_user: Any) -> None:
    user_data, _ = await create_user(email="suspended@example.com")
    await User.filter(id=user_data["id"]).update(role=UserRole.SUSPENDED)
    resp = await client.post(
        "/api/v1/users/token",
        json={
            "email": "suspended@example.com",
            "password": "StrongPass1",
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Account suspended"


async def test_get_me_success(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="me@example.com")
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"
    assert "hashed_password" not in resp.json()


async def test_get_me_no_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


async def test_get_me_invalid_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer invalidtoken"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Could not validate credentials"


async def test_get_me_suspended(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user(email="susp@example.com")
    await User.filter(id=user_data["id"]).update(role=UserRole.SUSPENDED)
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Account suspended"


async def test_get_user_by_id(client: AsyncClient, create_user: Any) -> None:
    user_data, _ = await create_user(email="byid@example.com")
    resp = await client.get(f"/api/v1/users/{user_data['id']}")
    assert resp.status_code == 200
    assert resp.json()["email"] == "byid@example.com"


async def test_get_me_expired_token(client: AsyncClient) -> None:
    settings = get_settings()
    expired_payload = {"sub": "000000", "exp": 0}
    expired_token = pyjwt.encode(expired_payload, settings.jwt.secret, algorithm=settings.jwt.algorithm)
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Could not validate credentials"


async def test_token_for_deleted_user(client: AsyncClient, create_user: Any) -> None:
    user_data, token = await create_user(email="deleted@example.com")
    await User.filter(id=user_data["id"]).delete()
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Could not validate credentials"


async def test_token_without_sub_claim(client: AsyncClient) -> None:
    settings = get_settings()
    token = pyjwt.encode({"exp": 9999999999}, settings.jwt.secret, algorithm=settings.jwt.algorithm)
    resp = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Could not validate credentials"


async def test_get_user_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/ZZZZZZ")
    assert resp.status_code == 404


async def test_update_name(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="upd@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"name": "НовоеИмя"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "НовоеИмя"


async def test_update_invalid_phone(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="badphone_upd@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"phone": "12345"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_update_phone(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="phone_upd@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"phone": "+79998887766"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+79998887766"


async def test_update_email(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="oldemail@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"email": "newemail@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "newemail@example.com"


async def test_update_email_duplicate(client: AsyncClient, create_user: Any) -> None:
    await create_user(email="taken@example.com")
    _, token = await create_user(email="other@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"email": "taken@example.com"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_password_change_success(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="pwchange@example.com", password="OldPass1x")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"password": "OldPass1x", "new_password": "NewPass2y"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    login_resp = await client.post(
        "/api/v1/users/token",
        json={
            "email": "pwchange@example.com",
            "password": "NewPass2y",
        },
    )
    assert login_resp.status_code == 200


async def test_password_change_missing_new_password(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="nopw@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"password": "StrongPass1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_password_change_missing_current_password(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="nocur@example.com")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"new_password": "NewPass2y"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_password_change_wrong_current(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="wrongcur@example.com", password="CorrectPass1")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"password": "WrongPass1", "new_password": "NewPass2y"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_password_change_weak_new_password(client: AsyncClient, create_user: Any) -> None:
    _, token = await create_user(email="weaknew@example.com", password="StrongPass1")
    resp = await client.patch(
        "/api/v1/users/me",
        json={"password": "StrongPass1", "new_password": "weak"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_admin_assigns_suspended_role(
    client: AsyncClient,
    create_user: Any,
    admin_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="target@example.com")
    _, admin_token = admin_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/role",
        json={"role": "suspended"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "suspended"


async def test_admin_assigns_user_role(
    client: AsyncClient,
    create_user: Any,
    admin_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="target2@example.com")
    _, admin_token = admin_user
    await User.filter(id=target["id"]).update(role=UserRole.SUSPENDED)
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/role",
        json={"role": "user"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


async def test_non_admin_rejected(
    client: AsyncClient,
    create_user: Any,
) -> None:
    target, _ = await create_user(email="t1@example.com")
    _, regular_token = await create_user(email="regular@example.com")
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/role",
        json={"role": "suspended"},
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403


async def test_role_route_rejects_admin_value(
    client: AsyncClient,
    create_user: Any,
    admin_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="t2@example.com")
    _, admin_token = admin_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/role",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


async def test_role_route_rejects_owner_value(
    client: AsyncClient,
    create_user: Any,
    admin_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="t3@example.com")
    _, admin_token = admin_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/role",
        json={"role": "owner"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 422


# ── Privilege route (owner only) ────────────────────────


async def test_owner_assigns_admin_privilege(
    client: AsyncClient,
    create_user: Any,
    owner_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="t4@example.com")
    _, owner_token = owner_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/privilege",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_owner_assigns_owner_privilege(
    client: AsyncClient,
    create_user: Any,
    owner_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="t5@example.com")
    _, owner_token = owner_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/privilege",
        json={"role": "owner"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"


async def test_admin_rejected_from_privilege_route(
    client: AsyncClient,
    create_user: Any,
    admin_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="t6@example.com")
    _, admin_token = admin_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/privilege",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403


async def test_regular_user_rejected_from_privilege_route(
    client: AsyncClient,
    create_user: Any,
) -> None:
    target, _ = await create_user(email="t7@example.com")
    _, regular_token = await create_user(email="regular2@example.com")
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/privilege",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {regular_token}"},
    )
    assert resp.status_code == 403


async def test_privilege_route_rejects_user_role(
    client: AsyncClient,
    create_user: Any,
    owner_user: tuple[dict[str, Any], str],
) -> None:
    target, _ = await create_user(email="t8@example.com")
    _, owner_token = owner_user
    resp = await client.patch(
        f"/api/v1/private/users/{target['id']}/privilege",
        json={"role": "user"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 422
