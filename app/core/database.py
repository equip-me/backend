from app.core.config import get_settings

MODELS = [
    "app.users.models",
    "app.organizations.models",
    "app.listings.models",
    "app.orders.models",
    "app.media.models",
    "app.chat.models",
]


def get_tortoise_config() -> dict[str, object]:
    settings = get_settings()
    return {
        "connections": {
            "default": {
                "engine": "tortoise.backends.asyncpg",
                "credentials": {
                    "host": settings.database.host,
                    "port": settings.database.port,
                    "user": settings.database.user,
                    "password": settings.database.password,
                    "database": settings.database.name,
                },
            },
        },
        "apps": {
            "models": {
                "models": MODELS,
                "default_connection": "default",
            },
        },
    }
