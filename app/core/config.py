import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml_config(env: str) -> dict[str, Any]:
    base_path = CONFIG_DIR / "base.yaml"
    env_path = CONFIG_DIR / f"{env}.yaml"

    with base_path.open() as f:
        base: dict[str, Any] = yaml.safe_load(f) or {}

    if env_path.exists():
        with env_path.open() as f:
            env_config: dict[str, Any] = yaml.safe_load(f) or {}
        return _deep_merge(base, env_config)

    return base


class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    user: str = "rental"
    name: str = "rental_dev"
    password: str = ""


class JWTSettings(BaseModel):
    algorithm: str = "HS256"
    token_lifetime_days: int = 7
    secret: str = ""


class CORSSettings(BaseModel):
    allow_origins: list[str] = []
    allow_methods: list[str] = ["*"]
    allow_headers: list[str] = ["*"]
    allow_credentials: bool = True


class Settings(BaseModel):
    app_env: str = "dev"
    database: DatabaseSettings = DatabaseSettings()
    jwt: JWTSettings = JWTSettings()
    cors: CORSSettings = CORSSettings()
    dadata_api_key: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "dev")
    yaml_data = _load_yaml_config(env)

    db_data = yaml_data.get("database", {})
    db_data["password"] = os.getenv("DATABASE_PASSWORD", "")

    jwt_data = yaml_data.get("jwt", {})
    jwt_data["secret"] = os.getenv("JWT_SECRET", "")

    return Settings(
        app_env=env,
        database=DatabaseSettings(**db_data),
        jwt=JWTSettings(**jwt_data),
        cors=CORSSettings(**yaml_data.get("cors", {})),
        dadata_api_key=os.getenv("DADATA_API_KEY", ""),
    )
