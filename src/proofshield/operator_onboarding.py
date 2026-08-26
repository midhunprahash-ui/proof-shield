"""Guarded provisioning for one named Supabase Auth operator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from proofshield.operator_auth import SupabaseOperatorAuthenticator


class OperatorOnboardingError(RuntimeError):
    """Raised when operator provisioning cannot complete safely."""


@dataclass(frozen=True)
class OperatorOnboardingRequest:
    email: str
    password: str
    display_name: str

    def normalized(self) -> OperatorOnboardingRequest:
        email = self.email.strip().casefold()
        display_name = " ".join(self.display_name.split())
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise OperatorOnboardingError("a valid operator email is required")
        if len(self.password) < 12:
            raise OperatorOnboardingError(
                "the operator password must contain at least 12 characters"
            )
        if not 2 <= len(display_name) <= 80:
            raise OperatorOnboardingError(
                "the operator display name must contain 2 to 80 characters"
            )
        return OperatorOnboardingRequest(
            email=email,
            password=self.password,
            display_name=display_name,
        )


@dataclass(frozen=True)
class OperatorOnboardingResult:
    user_id: str
    email: str
    display_name: str
    auth_user_created: bool
    registry_row_created: bool
    sign_in_verified: bool = True
    operator_access_verified: bool = True


def onboard_operator(
    *,
    admin_client: Any,
    public_auth_client: Any,
    request: OperatorOnboardingRequest,
) -> OperatorOnboardingResult:
    """Create or verify an Auth user, register it, and prove operator access."""

    desired = request.normalized()
    auth_user = _find_auth_user(admin_client, desired.email)
    auth_user_created = auth_user is None
    if auth_user is None:
        try:
            response = admin_client.auth.admin.create_user(
                {
                    "email": desired.email,
                    "password": desired.password,
                    "email_confirm": True,
                    "user_metadata": {"display_name": desired.display_name},
                }
            )
        except Exception as error:
            raise OperatorOnboardingError(
                "Supabase Auth could not create the operator account"
            ) from error
        auth_user = response.user

    user_id = str(getattr(auth_user, "id", ""))
    auth_email = str(getattr(auth_user, "email", "") or "").strip().casefold()
    if not user_id or auth_email != desired.email:
        raise OperatorOnboardingError(
            "the Supabase Auth identity does not match the requested operator"
        )

    access_token = _verify_password_session(
        public_auth_client,
        email=desired.email,
        password=desired.password,
        expected_user_id=user_id,
    )
    registry_row_created = _register_operator(
        admin_client,
        user_id=user_id,
        email=desired.email,
        display_name=desired.display_name,
    )
    try:
        identity = SupabaseOperatorAuthenticator(admin_client).authenticate(access_token)
    except Exception as error:
        raise OperatorOnboardingError(
            "the new session could not pass the active operator gate"
        ) from error
    if str(identity.user_id) != user_id or identity.email != desired.email:
        raise OperatorOnboardingError(
            "the verified operator identity does not match the Auth account"
        )

    return OperatorOnboardingResult(
        user_id=user_id,
        email=desired.email,
        display_name=identity.display_name,
        auth_user_created=auth_user_created,
        registry_row_created=registry_row_created,
    )


def _find_auth_user(admin_client: Any, email: str) -> Any | None:
    matches: list[Any] = []
    page = 1
    while True:
        try:
            users = admin_client.auth.admin.list_users(page=page, per_page=1000)
        except Exception as error:
            raise OperatorOnboardingError("Supabase Auth users could not be inspected") from error
        matches.extend(
            user
            for user in users
            if str(getattr(user, "email", "") or "").strip().casefold() == email
        )
        if len(users) < 1000:
            break
        page += 1
    if len(matches) > 1:
        raise OperatorOnboardingError(
            "multiple Supabase Auth users unexpectedly share the operator email"
        )
    return matches[0] if matches else None


def _verify_password_session(
    public_auth_client: Any,
    *,
    email: str,
    password: str,
    expected_user_id: str,
) -> str:
    try:
        response = public_auth_client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except Exception as error:
        raise OperatorOnboardingError(
            "the operator email/password could not start a Supabase Auth session"
        ) from error
    session = response.session
    session_user_id = str(getattr(getattr(response, "user", None), "id", ""))
    access_token = str(getattr(session, "access_token", "") or "")
    if session_user_id != expected_user_id or len(access_token) < 16:
        raise OperatorOnboardingError(
            "Supabase Auth returned an incomplete or mismatched operator session"
        )
    return access_token


def _register_operator(
    admin_client: Any,
    *,
    user_id: str,
    email: str,
    display_name: str,
) -> bool:
    try:
        by_user = (
            admin_client.table("proofshield_operators")
            .select("user_id,email,display_name,active")
            .eq("user_id", user_id)
            .execute()
            .data
        )
        by_email = (
            admin_client.table("proofshield_operators")
            .select("user_id,email,display_name,active")
            .eq("email", email)
            .execute()
            .data
        )
    except Exception as error:
        raise OperatorOnboardingError("the operator registry could not be inspected") from error

    rows = {str(row["user_id"]): row for row in [*by_user, *by_email]}
    if rows:
        if set(rows) != {user_id}:
            raise OperatorOnboardingError(
                "the operator email is already registered to a different Auth user"
            )
        row = rows[user_id]
        if str(row["email"]).casefold() != email:
            raise OperatorOnboardingError(
                "the Auth user is registered with a different operator email"
            )
        if row["display_name"] != display_name:
            raise OperatorOnboardingError("the existing operator has a different display name")
        if row["active"] is not True:
            raise OperatorOnboardingError(
                "the existing operator is inactive and was not reactivated"
            )
        return False

    try:
        admin_client.table("proofshield_operators").insert(
            {
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "active": True,
            }
        ).execute()
    except Exception as error:
        raise OperatorOnboardingError(
            "the Auth user was created but the operator registry insert failed"
        ) from error
    return True
