import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator
from typing_extensions import Self

from app.core.enums import UserRole

_PHONE_RE = re.compile(r"^(\+7|7|8)?[\s\-]?\(?[489]\d{2}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}$")

_PASSWORD_MIN_LENGTH = 8
_LOWER_RE = re.compile(r"[a-zа-яё]")
_UPPER_RE = re.compile(r"[A-ZА-ЯЁ]")
_DIGIT_RE = re.compile(r"\d")


def _validate_password(value: str) -> str:
    if len(value) < _PASSWORD_MIN_LENGTH:
        msg = "Password must be at least 8 characters"
        raise ValueError(msg)
    if not _LOWER_RE.search(value):
        msg = "Password must contain at least one lowercase letter"
        raise ValueError(msg)
    if not _UPPER_RE.search(value):
        msg = "Password must contain at least one uppercase letter"
        raise ValueError(msg)
    if not _DIGIT_RE.search(value):
        msg = "Password must contain at least one digit"
        raise ValueError(msg)
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    phone: str
    name: str
    surname: str
    middle_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password(v)

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            msg = "Invalid Russian phone number format"
            raise ValueError(msg)
        return v


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    name: str | None = None
    surname: str | None = None
    middle_name: str | None = None
    password: str | None = None
    new_password: str | None = None

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v: str | None) -> str | None:
        if v is not None and not _PHONE_RE.match(v):
            msg = "Invalid Russian phone number format"
            raise ValueError(msg)
        return v

    @field_validator("new_password")
    @classmethod
    def new_password_strength(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_password(v)
        return v

    @model_validator(mode="after")
    def password_pair_required(self) -> Self:
        if self.password and not self.new_password:
            msg = "new_password is required when password is provided"
            raise ValueError(msg)
        if self.new_password and not self.password:
            msg = "Current password is required when setting new_password"
            raise ValueError(msg)
        return self


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    phone: str
    name: str
    middle_name: str | None
    surname: str
    role: UserRole
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
