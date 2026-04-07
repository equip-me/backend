from app.core.exceptions import (
    AccountSuspendedError,
    AlreadyExistsError,
    AppError,
    AppValidationError,
    ExternalServiceError,
    IDGenerationError,
    InvalidCredentialsError,
    NotFoundError,
    PermissionDeniedError,
)


class TestAppErrorCode:
    def test_default_code_is_empty_string(self) -> None:
        err = AppError("some detail")
        assert err.code == ""
        assert err.params == {}
        assert err.detail == "some detail"

    def test_code_and_params(self) -> None:
        err = AppError("some detail", code="test.error", params={"key": "val"})
        assert err.code == "test.error"
        assert err.params == {"key": "val"}

    def test_subclass_inherits_code(self) -> None:
        err = NotFoundError("not found", code="users.not_found")
        assert err.code == "users.not_found"
        assert err.params == {}

    def test_subclass_with_params(self) -> None:
        err = AppValidationError(
            "Cannot cancel order in status finished",
            code="orders.invalid_transition",
            params={"action": "cancel", "status": "finished"},
        )
        assert err.code == "orders.invalid_transition"
        assert err.params == {"action": "cancel", "status": "finished"}


class TestSubclassesAcceptCode:
    def test_not_found_error(self) -> None:
        err = NotFoundError("x", code="users.not_found")
        assert err.code == "users.not_found"

    def test_already_exists_error(self) -> None:
        err = AlreadyExistsError("x", code="users.email_taken")
        assert err.code == "users.email_taken"

    def test_invalid_credentials_error(self) -> None:
        err = InvalidCredentialsError("x", code="auth.invalid_credentials")
        assert err.code == "auth.invalid_credentials"

    def test_permission_denied_error(self) -> None:
        err = PermissionDeniedError("x", code="org.admin_required")
        assert err.code == "org.admin_required"

    def test_account_suspended_error(self) -> None:
        err = AccountSuspendedError("x", code="auth.account_suspended")
        assert err.code == "auth.account_suspended"

    def test_app_validation_error(self) -> None:
        err = AppValidationError("x", code="orders.start_date_in_past")
        assert err.code == "orders.start_date_in_past"

    def test_id_generation_error(self) -> None:
        err = IDGenerationError("x", code="server.internal_error")
        assert err.code == "server.internal_error"

    def test_external_service_error(self) -> None:
        err = ExternalServiceError("x", code="server.external_service_unavailable", params={"service": "dadata"})
        assert err.code == "server.external_service_unavailable"
        assert err.params == {"service": "dadata"}
