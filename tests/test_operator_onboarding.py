from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from proofshield.operator_onboarding import (
    OperatorOnboardingError,
    OperatorOnboardingRequest,
    onboard_operator,
)

USER_ID = "11111111-1111-4111-8111-111111111111"


def test_onboarding_creates_auth_user_registry_and_verified_session() -> None:
    backend = FakeBackendClient()
    public = FakePublicAuthClient(backend)

    result = onboard_operator(
        admin_client=backend,
        public_auth_client=public,
        request=OperatorOnboardingRequest(
            email=" Operator@Example.com ",
            password="correct-horse-battery-staple",
            display_name="  Demo   Operator ",
        ),
    )

    assert result.email == "operator@example.com"
    assert result.display_name == "Demo Operator"
    assert result.auth_user_created is True
    assert result.registry_row_created is True
    assert backend.created_payload["email_confirm"] is True
    assert backend.created_payload["password"] == "correct-horse-battery-staple"
    assert backend.rows[0]["active"] is True


def test_onboarding_is_idempotent_for_the_same_active_operator() -> None:
    backend = FakeBackendClient()
    public = FakePublicAuthClient(backend)
    request = OperatorOnboardingRequest(
        email="operator@example.com",
        password="correct-horse-battery-staple",
        display_name="Demo Operator",
    )

    first = onboard_operator(
        admin_client=backend,
        public_auth_client=public,
        request=request,
    )
    second = onboard_operator(
        admin_client=backend,
        public_auth_client=public,
        request=request,
    )

    assert first.auth_user_created is True
    assert second.auth_user_created is False
    assert second.registry_row_created is False
    assert len(backend.rows) == 1


def test_onboarding_refuses_wrong_existing_password_before_registry_write() -> None:
    backend = FakeBackendClient()
    backend.users.append(FakeUser(USER_ID, "operator@example.com", "right-password-123"))

    with pytest.raises(OperatorOnboardingError, match="email/password"):
        onboard_operator(
            admin_client=backend,
            public_auth_client=FakePublicAuthClient(backend),
            request=OperatorOnboardingRequest(
                email="operator@example.com",
                password="wrong-password-123",
                display_name="Demo Operator",
            ),
        )

    assert backend.rows == []


def test_onboarding_does_not_silently_reactivate_an_operator() -> None:
    backend = FakeBackendClient()
    backend.users.append(FakeUser(USER_ID, "operator@example.com", "right-password-123"))
    backend.rows.append(
        {
            "user_id": USER_ID,
            "email": "operator@example.com",
            "display_name": "Demo Operator",
            "active": False,
        }
    )

    with pytest.raises(OperatorOnboardingError, match="inactive"):
        onboard_operator(
            admin_client=backend,
            public_auth_client=FakePublicAuthClient(backend),
            request=OperatorOnboardingRequest(
                email="operator@example.com",
                password="right-password-123",
                display_name="Demo Operator",
            ),
        )


@dataclass
class FakeUser:
    id: str
    email: str
    password: str


class FakeBackendClient:
    def __init__(self) -> None:
        self.auth = self
        self.admin = self
        self.users: list[FakeUser] = []
        self.rows: list[dict] = []
        self.created_payload: dict = {}
        self._query_filters: list[tuple[str, object]] = []
        self._insert_payload: dict | None = None

    def list_users(self, page: int, per_page: int) -> list[FakeUser]:
        start = (page - 1) * per_page
        return self.users[start : start + per_page]

    def create_user(self, payload: dict) -> SimpleNamespace:
        self.created_payload = payload
        user = FakeUser(USER_ID, payload["email"], payload["password"])
        self.users.append(user)
        return SimpleNamespace(user=user)

    def get_user(self, token: str) -> SimpleNamespace:
        user_id = token.removeprefix("verified-access-token-")
        user = next(user for user in self.users if user.id == user_id)
        return SimpleNamespace(user=user)

    def table(self, name: str) -> FakeBackendClient:
        assert name == "proofshield_operators"
        self._query_filters = []
        self._insert_payload = None
        return self

    def select(self, _columns: str) -> FakeBackendClient:
        return self

    def eq(self, field: str, value: str) -> FakeBackendClient:
        self._query_filters.append((field, value))
        return self

    def limit(self, _count: int) -> FakeBackendClient:
        return self

    def insert(self, payload: dict) -> FakeBackendClient:
        self._insert_payload = payload
        return self

    def execute(self) -> SimpleNamespace:
        if self._insert_payload is not None:
            self.rows.append(self._insert_payload)
            payload = self._insert_payload
            self._insert_payload = None
            return SimpleNamespace(data=[payload])
        rows = [
            row
            for row in self.rows
            if all(row.get(field) == value for field, value in self._query_filters)
        ]
        return SimpleNamespace(data=rows)


class FakePublicAuthClient:
    def __init__(self, backend: FakeBackendClient) -> None:
        self.auth = self
        self.backend = backend

    def sign_in_with_password(self, payload: dict) -> SimpleNamespace:
        user = next(
            (
                user
                for user in self.backend.users
                if user.email == payload["email"] and user.password == payload["password"]
            ),
            None,
        )
        if user is None:
            raise ValueError("invalid credentials")
        return SimpleNamespace(
            user=user,
            session=SimpleNamespace(access_token=f"verified-access-token-{user.id}"),
        )
