"""Verified Supabase Auth identities for protected operator workflows."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from supabase_auth.errors import AuthError, AuthRetryableError


class OperatorAuthenticationError(RuntimeError):
    """Base class for operator authentication failures."""


class InvalidOperatorToken(OperatorAuthenticationError):
    pass


class OperatorNotAuthorized(OperatorAuthenticationError):
    pass


class OperatorAuthenticationUnavailable(OperatorAuthenticationError):
    pass


class OperatorIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)


class PublicAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    supabase_url: str
    supabase_publishable_key: str


class OperatorAuthenticator(Protocol):
    def authenticate(self, access_token: str) -> OperatorIdentity: ...


class SupabaseOperatorAuthenticator:
    """Verify a JWT with Supabase Auth, then require an active operator row."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def authenticate(self, access_token: str) -> OperatorIdentity:
        try:
            response = self.client.auth.get_user(access_token)
        except AuthRetryableError as error:
            raise OperatorAuthenticationUnavailable(
                "Supabase Auth is temporarily unavailable."
            ) from error
        except AuthError as error:
            raise InvalidOperatorToken("The operator session is invalid or expired.") from error
        except Exception as error:
            raise OperatorAuthenticationUnavailable(
                "Supabase Auth could not verify the operator session."
            ) from error

        user = response.user if response is not None else None
        user_id = getattr(user, "id", None)
        email = getattr(user, "email", None)
        if not user_id or not email:
            raise InvalidOperatorToken("The operator session has no verified identity.")

        try:
            rows = (
                self.client.table("proofshield_operators")
                .select("user_id,email,display_name")
                .eq("user_id", str(user_id))
                .eq("active", True)
                .limit(1)
                .execute()
                .data
            )
        except Exception as error:
            raise OperatorAuthenticationUnavailable(
                "The operator registry could not be checked."
            ) from error
        if not rows:
            raise OperatorNotAuthorized(
                "This signed-in account is not an active ProofShield operator."
            )
        row = rows[0]
        if str(row["email"]).casefold() != str(email).casefold():
            raise OperatorNotAuthorized(
                "The operator registry does not match the verified account."
            )
        return OperatorIdentity(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
        )
