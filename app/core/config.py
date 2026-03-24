import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    app_env: str = "dev"
    database: DatabaseSettings = DatabaseSettings()
    jwt: JWTSettings = JWTSettings()
    cors: CORSSettings = CORSSettings()
    dadata_api_key: str = ""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        env = os.getenv("APP_ENV", "dev")
        yaml_files: list[Path] = [CONFIG_DIR / "base.yaml"]
        env_path = CONFIG_DIR / f"{env}.yaml"
        if env_path.exists():
            yaml_files.append(env_path)
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_files),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
