import pytest
from fastapi.exceptions import RequestValidationError

from app.core.pagination import ordering_dependency


class TestOrderingDependency:
    def setup_method(self) -> None:
        self.cls = ordering_dependency(
            allowed_fields={"price": "price", "name": "name", "created_at": "created_at"},
            default="-created_at",
        )

    def test_default_ordering(self) -> None:
        dep = self.cls(order_by=None)
        assert dep.ordering == ("-created_at", "-id")

    def test_ascending_field(self) -> None:
        dep = self.cls(order_by="price")
        assert dep.ordering == ("price", "id")

    def test_descending_field(self) -> None:
        dep = self.cls(order_by="-price")
        assert dep.ordering == ("-price", "-id")

    def test_field_name_mapping(self) -> None:
        cls = ordering_dependency(
            allowed_fields={"cost": "estimated_cost"},
            default="-estimated_cost",
        )
        dep = cls(order_by="-cost")
        assert dep.ordering == ("-estimated_cost", "-id")

    def test_invalid_field_raises_validation_error(self) -> None:
        with pytest.raises(RequestValidationError):
            self.cls(order_by="nonexistent")

    def test_empty_string_raises_validation_error(self) -> None:
        with pytest.raises(RequestValidationError):
            self.cls(order_by="")

    def test_double_dash_raises_validation_error(self) -> None:
        with pytest.raises(RequestValidationError):
            self.cls(order_by="--price")

    def test_tiebreaker_direction_matches_primary_desc(self) -> None:
        dep = self.cls(order_by="-name")
        assert dep.ordering == ("-name", "-id")

    def test_tiebreaker_direction_matches_primary_asc(self) -> None:
        dep = self.cls(order_by="name")
        assert dep.ordering == ("name", "id")

    def test_default_with_ascending(self) -> None:
        cls = ordering_dependency(
            allowed_fields={"name": "name"},
            default="name",
        )
        dep = cls(order_by=None)
        assert dep.ordering == ("name", "id")
