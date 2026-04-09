from app.core.pagination import ordering_dependency

UserOrdering = ordering_dependency(
    allowed_fields={"email": "email", "surname": "surname", "created_at": "created_at"},
    default="-created_at",
)
