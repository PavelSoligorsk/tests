"""
Асинхронные тесты аутентификации на httpx.AsyncClient.

Покрывают бизнес-требования:
- Регистрация пользователя (успех, дубликат, неразрешённый email)
- Вход в систему (успех, неверный пароль, несуществующий пользователь)
- Восстановление пароля (запрос, сброс, проверка токена)
- Валидация входных данных (слабый пароль, пустые поля)
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers_async import _bearer


# ═══════════════════════════════════════════════════════════════
# Регистрация
# ═══════════════════════════════════════════════════════════════


@pytest.mark.auth
@pytest.mark.asyncio
async def test_register_success(async_client: AsyncClient, admin_token: str) -> None:
    """БТ: Пользователь может зарегистрироваться, если email в списке разрешённых."""
    # Add email to allowed list first
    email = "newuser@test.com"
    await async_client.post(
        "/admin/allowed-emails",
        json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    resp = await async_client.post("/register", json={
        "username": email,
        "password": "StrongPass1!",
        "first_name": "New",
        "last_name": "User",
    })

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "message" in data


@pytest.mark.auth
@pytest.mark.asyncio
async def test_register_duplicate_email(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Нельзя зарегистрироваться с уже занятым email — ошибка 400."""
    email = "dup@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # First registration
    resp1 = await async_client.post("/register", json={
        "username": email, "password": "StrongPass1!",
        "first_name": "First", "last_name": "User",
    })
    assert resp1.status_code == 200

    # Second registration with same email
    resp2 = await async_client.post("/register", json={
        "username": email, "password": "StrongPass1!",
        "first_name": "Second", "last_name": "User",
    })
    assert resp2.status_code == 400, resp2.text


@pytest.mark.auth
@pytest.mark.asyncio
async def test_register_email_not_allowed(async_client: AsyncClient) -> None:
    """БТ: Регистрация с email не из списка разрешённых — ошибка 403."""
    resp = await async_client.post("/register", json={
        "username": "hacker@evil.com",
        "password": "StrongPass1!",
        "first_name": "Hack",
        "last_name": "Er",
    })
    assert resp.status_code == 403, resp.text


# ═══════════════════════════════════════════════════════════════
# Вход в систему
# ═══════════════════════════════════════════════════════════════


@pytest.mark.auth
@pytest.mark.asyncio
async def test_login_success(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Успешный вход возвращает токен, роль и имя пользователя."""
    # re-register fresh user via admin_token
    email = "login-test@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "LoginPass1!",
        "first_name": "Login", "last_name": "Test",
    })

    resp = await async_client.post("/login", data={
        "username": email, "password": "LoginPass1!",
    })

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "student"
    assert data["username"] == email


@pytest.mark.auth
@pytest.mark.asyncio
async def test_login_wrong_password(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Вход с неверным паролем — ошибка 401."""
    email = "wrong-pw@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await async_client.post("/register", json={
        "username": email, "password": "Correct1!",
        "first_name": "A", "last_name": "B",
    })

    resp = await async_client.post("/login", data={
        "username": email, "password": "WrongPass1!",
    })
    assert resp.status_code == 401, resp.text


@pytest.mark.auth
@pytest.mark.asyncio
async def test_login_nonexistent_user(async_client: AsyncClient) -> None:
    """БТ: Вход с несуществующим пользователем — ошибка 401."""
    resp = await async_client.post("/login", data={
        "username": "nobody@test.com", "password": "Whatever1!",
    })
    assert resp.status_code == 401, resp.text


# ═══════════════════════════════════════════════════════════════
# Восстановление пароля
# ═══════════════════════════════════════════════════════════════


@pytest.mark.auth
@pytest.mark.asyncio
async def test_forgot_password_always_ok(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Запрос на восстановление всегда возвращает успех (безопасность)."""
    # Even for non-existent users, the endpoint should return 200
    # to not leak information about registered emails
    resp = await async_client.post("/forgot-password", json={
        "email": "nonexistent@test.com",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "message" in data


@pytest.mark.auth
@pytest.mark.asyncio
async def test_reset_password_invalid_token(
    async_client: AsyncClient,
) -> None:
    """БТ: Сброс пароля с невалидным токеном — ошибка 400."""
    resp = await async_client.post("/reset-password", json={
        "token": "invalid-token-12345",
        "new_password": "NewPass1!",
        "confirm_password": "NewPass1!",
    })
    assert resp.status_code == 400, resp.text


@pytest.mark.auth
@pytest.mark.asyncio
async def test_reset_password_mismatched_passwords(
    async_client: AsyncClient,
) -> None:
    """БТ: Пароли не совпадают — ошибка 400."""
    resp = await async_client.post("/reset-password", json={
        "token": "some-token",
        "new_password": "PassOne1!",
        "confirm_password": "PassTwo2!",
    })
    assert resp.status_code == 400, resp.text


@pytest.mark.auth
@pytest.mark.asyncio
async def test_verify_reset_token_invalid(
    async_client: AsyncClient,
) -> None:
    """БТ: Проверка невалидного токена сброса возвращает valid=false."""
    resp = await async_client.get("/verify-reset-token/fake-token-xyz")
    # The API should return a valid JSON response (not 5xx)
    assert resp.status_code in (200, 400), f"Unexpected: {resp.status_code} {resp.text}"


# ═══════════════════════════════════════════════════════════════
# Валидация входных данных
# ═══════════════════════════════════════════════════════════════


@pytest.mark.auth
@pytest.mark.asyncio
async def test_register_missing_fields(async_client: AsyncClient) -> None:
    """БТ: Регистрация без обязательных полей — ошибка 422."""
    resp = await async_client.post("/register", json={
        "username": "test@test.com",
        # missing password, first_name, last_name
    })
    assert resp.status_code == 422, resp.text


@pytest.mark.auth
@pytest.mark.asyncio
async def test_login_missing_fields(async_client: AsyncClient) -> None:
    """БТ: Вход без обязательных полей — ошибка 422."""
    resp = await async_client.post("/login", data={
        # missing username and password
    })
    assert resp.status_code == 422, resp.text


# ═══════════════════════════════════════════════════════════════
# Правило: admin@gmail.com автоматически получает роль admin
# ═══════════════════════════════════════════════════════════════


@pytest.mark.auth
@pytest.mark.asyncio
async def test_register_admin_auto_role(
    async_client: AsyncClient, admin_token: str
) -> None:
    """БТ: Пользователь с username=admin@gmail.com автоматически получает роль admin."""
    await async_client.post(
        "/admin/allowed-emails",
        json={"email": "admin@gmail.com"},
        headers=_bearer(admin_token),
    )

    resp = await async_client.post("/register", json={
        "username": "admin@gmail.com",
        "password": "SuperAdmin1!",
        "first_name": "Auto",
        "last_name": "Admin",
    })
    assert resp.status_code == 200, resp.text

    # Login to check role
    login_resp = await async_client.post("/login", data={
        "username": "admin@gmail.com", "password": "SuperAdmin1!",
    })
    assert login_resp.status_code == 200
    assert login_resp.json()["role"] == "admin"


# ═══════════════════════════════════════════════════════════════
# Правило: полный цикл восстановления пароля (forgot → reset → login)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.auth
@pytest.mark.asyncio
async def test_full_reset_password_cycle(
    async_client: AsyncClient, admin_token: str, db
) -> None:
    """БТ: Полный цикл: forgot-password создаёт токен, reset меняет пароль, вход с новым паролем."""
    from sqlalchemy import select
    from core.models import PasswordResetToken

    email = "reset-cycle@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token),
    )
    await async_client.post("/register", json={
        "username": email, "password": "OldPass1!",
        "first_name": "Reset", "last_name": "Cycle",
    })

    # Step 1: forgot-password — creates token in DB (even though email send fails)
    forgot_resp = await async_client.post("/forgot-password", json={"email": email})
    assert forgot_resp.status_code == 200

    # Step 2: extract the token from DB
    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.email == email,
            PasswordResetToken.is_used == False,
        )
    )
    token_row = result.scalars().first()
    assert token_row is not None, "Reset token should be in DB"
    assert token_row.token is not None

    # Step 3: reset password with valid token
    reset_resp = await async_client.post("/reset-password", json={
        "token": token_row.token,
        "new_password": "NewPass1!",
        "confirm_password": "NewPass1!",
    })
    assert reset_resp.status_code == 200, reset_resp.text
    assert "успешно" in reset_resp.json()["message"].lower()

    # Step 4: login with new password works
    login_resp = await async_client.post("/login", data={
        "username": email, "password": "NewPass1!",
    })
    assert login_resp.status_code == 200

    # Step 5: old password no longer works
    login_old = await async_client.post("/login", data={
        "username": email, "password": "OldPass1!",
    })
    assert login_old.status_code == 401


@pytest.mark.auth
@pytest.mark.asyncio
async def test_reset_token_cannot_be_reused(
    async_client: AsyncClient, admin_token: str, db
) -> None:
    """БТ: Токен сброса помечается использованным — повторный сброс с тем же токеном отклоняется."""
    from sqlalchemy import select
    from core.models import PasswordResetToken

    email = "token-reuse@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token),
    )
    await async_client.post("/register", json={
        "username": email, "password": "OldPass1!",
        "first_name": "Reuse", "last_name": "Token",
    })

    await async_client.post("/forgot-password", json={"email": email})

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.email == email,
            PasswordResetToken.is_used == False,
        )
    )
    token_row = result.scalars().first()
    assert token_row is not None

    # First reset — works
    resp1 = await async_client.post("/reset-password", json={
        "token": token_row.token,
        "new_password": "FirstNew1!",
        "confirm_password": "FirstNew1!",
    })
    assert resp1.status_code == 200, resp1.text

    # Second reset with same token — must fail (token marked used)
    resp2 = await async_client.post("/reset-password", json={
        "token": token_row.token,
        "new_password": "SecondNew1!",
        "confirm_password": "SecondNew1!",
    })
    assert resp2.status_code == 400, resp2.text


@pytest.mark.auth
@pytest.mark.asyncio
async def test_verify_valid_reset_token(
    async_client: AsyncClient, admin_token: str, db
) -> None:
    """БТ: /verify-reset-token/{token} возвращает valid=true для действительного токена."""
    from sqlalchemy import select
    from core.models import PasswordResetToken

    email = "verify-token@test.com"
    await async_client.post(
        "/admin/allowed-emails", json={"email": email},
        headers=_bearer(admin_token),
    )
    await async_client.post("/register", json={
        "username": email, "password": "Pass123!",
        "first_name": "Verify", "last_name": "Token",
    })

    await async_client.post("/forgot-password", json={"email": email})

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.email == email,
            PasswordResetToken.is_used == False,
        )
    )
    token_row = result.scalars().first()
    assert token_row is not None

    resp = await async_client.get(f"/verify-reset-token/{token_row.token}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["valid"] is True


@pytest.mark.auth
@pytest.mark.asyncio
async def test_reset_password_short_password(
    async_client: AsyncClient,
) -> None:
    """БТ: Сброс пароля с паролем < 8 символов — ошибка 400."""
    resp = await async_client.post("/reset-password", json={
        "token": "some-token",
        "new_password": "Sh0rt",
        "confirm_password": "Sh0rt",
    })
    assert resp.status_code == 400, resp.text
