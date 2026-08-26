from uuid import UUID

from proofshield.operator_auth import (
    InvalidOperatorToken,
    OperatorIdentity,
    OperatorNotAuthorized,
)

TEST_ACCESS_TOKEN = "test-supabase-operator-access-token"
TEST_OPERATOR = OperatorIdentity(
    user_id=UUID("11111111-1111-4111-8111-111111111111"),
    email="operator@example.com",
    display_name="Merchant risk lead",
)
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"}


class FakeOperatorAuthenticator:
    def __init__(self, identity: OperatorIdentity = TEST_OPERATOR) -> None:
        self.identity = identity

    def authenticate(self, access_token: str) -> OperatorIdentity:
        if access_token == TEST_ACCESS_TOKEN:
            return self.identity
        if access_token == "signed-in-but-not-operator":
            raise OperatorNotAuthorized("This account is not an active operator.")
        raise InvalidOperatorToken("The operator session is invalid or expired.")


TEST_AUTHENTICATOR = FakeOperatorAuthenticator()
