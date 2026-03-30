import pytest
from pydantic import ValidationError

from app.users.schemas import UserCreate, UserUpdate


class TestUserCreatePasswordValidation:
    @pytest.mark.parametrize(
        ("password", "reason"),
        [
            ("short", "too short"),
            ("UPPERCASE1", "no lowercase"),
            ("lowercase1", "no uppercase"),
            ("NoDigitsHere", "no digit"),
        ],
    )
    def test_weak_password_rejected(self, password: str, reason: str) -> None:
        with pytest.raises(ValidationError):
            UserCreate(
                email="test@example.com",
                password=password,
                phone="+79991234567",
                name="Test",
                surname="User",
            )

    def test_strong_password_accepted(self) -> None:
        user = UserCreate(
            email="test@example.com",
            password="StrongPass1",
            phone="+79991234567",
            name="Test",
            surname="User",
        )
        assert user.password == "StrongPass1"


class TestUserCreatePhoneValidation:
    def test_invalid_phone_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(
                email="test@example.com",
                password="StrongPass1",
                phone="12345",
                name="Test",
                surname="User",
            )

    def test_valid_phone_accepted(self) -> None:
        user = UserCreate(
            email="test@example.com",
            password="StrongPass1",
            phone="+79991234567",
            name="Test",
            surname="User",
        )
        assert user.phone == "+79991234567"


class TestUserCreateEmailValidation:
    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserCreate(
                email="not-an-email",
                password="StrongPass1",
                phone="+79991234567",
                name="Test",
                surname="User",
            )


class TestUserUpdatePasswordPairValidation:
    def test_password_without_new_password_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserUpdate(password="StrongPass1")

    def test_new_password_without_current_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserUpdate(new_password="NewPass2y")

    @pytest.mark.parametrize(
        ("new_password", "reason"),
        [
            ("short", "too short"),
            ("UPPERCASE1", "no lowercase"),
            ("lowercase1", "no uppercase"),
            ("NoDigitsHere", "no digit"),
        ],
    )
    def test_weak_new_password_rejected(self, new_password: str, reason: str) -> None:
        with pytest.raises(ValidationError):
            UserUpdate(password="StrongPass1", new_password=new_password)

    def test_valid_password_pair_accepted(self) -> None:
        update = UserUpdate(password="StrongPass1", new_password="NewPass2y")
        assert update.new_password == "NewPass2y"
