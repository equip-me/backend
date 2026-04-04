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
    expose_headers: list[str] = []


class ObservabilitySettings(BaseModel):
    enabled: bool = True
    otlp_endpoint: str = "localhost:4317"
    service_name: str = "rental-platform"
    console_log_level: str = "DEBUG"
    otel_log_level: str = "DEBUG"
    metrics_export_interval_seconds: int = 30


class StorageSettings(BaseModel):
    endpoint_url: str = "http://localhost:9000"
    presigned_endpoint_url: str = ""
    bucket: str = "rental-media"
    presigned_url_expiry_seconds: int = 3600
    access_key: str = ""
    secret_key: str = ""


class MediaSettings(BaseModel):
    max_photo_size_mb: int = 20
    max_video_size_mb: int = 500
    max_document_size_mb: int = 50
    allowed_photo_types: list[str] = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    allowed_video_types: list[str] = ["video/mp4", "video/quicktime", "video/webm"]
    allowed_document_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "text/csv",
    ]
    orphan_cleanup_after_hours: int = 24
    orphan_cleanup_interval_minutes: int = 60
    photo_variant_sets: dict[str, list[dict[str, int | str]]] = {}
    video_variant_sets: dict[str, list[dict[str, int | str | bool]]] = {}
    listing_limits_max_photos: int = 20
    listing_limits_max_videos: int = 5
    listing_limits_max_documents: int = 10


class WorkerSettings(BaseModel):
    redis_url: str = "redis://localhost:6379"
    max_concurrent_jobs: int = 10


class ChatSettings(BaseModel):
    cooldown_days: int = 7
    max_message_length: int = 4000
    max_attachments_per_message: int = 10
    rate_limit_per_minute: int = 30


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__", env_file=".env", env_file_encoding="utf-8")

    app_env: str = "dev"
    database: DatabaseSettings = DatabaseSettings()
    jwt: JWTSettings = JWTSettings()
    cors: CORSSettings = CORSSettings()
    observability: ObservabilitySettings = ObservabilitySettings()
    dadata_api_key: str = ""
    seed_categories: list[str] = []
    storage: StorageSettings = StorageSettings()
    media: MediaSettings = MediaSettings()
    worker: WorkerSettings = WorkerSettings()
    chat: ChatSettings = ChatSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
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
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_files),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
