"""Provision and verify one named operator in the live ProofShield project."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from proofshield.operator_onboarding import (
    OperatorOnboardingError,
    OperatorOnboardingRequest,
    onboard_operator,
)
from proofshield.supabase_runtime import SupabaseSettings

EXPECTED_PROJECT_REF = "qoujhmqkjicvcwoiyqkp"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-live-write",
        action="store_true",
        help="Required acknowledgement that an Auth user and registry row may be created.",
    )
    parser.add_argument(
        "--project-ref",
        required=True,
        help="Must exactly match the configured ProofShield project reference.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_live_write:
        parser.error("--confirm-live-write is required for live operator onboarding")

    settings = SupabaseSettings.from_env()
    if settings.project_ref != EXPECTED_PROJECT_REF:
        raise OperatorOnboardingError("the configured environment is not the ProofShield project")
    if arguments.project_ref != settings.project_ref:
        raise OperatorOnboardingError("--project-ref does not match the configured environment")

    request = OperatorOnboardingRequest(
        email=os.getenv("PROOFSHIELD_DEMO_OPERATOR_EMAIL", ""),
        password=os.getenv("PROOFSHIELD_DEMO_OPERATOR_PASSWORD", ""),
        display_name=os.getenv("PROOFSHIELD_DEMO_OPERATOR_DISPLAY_NAME", ""),
    )

    from supabase import create_client

    result = onboard_operator(
        admin_client=create_client(settings.url, settings.secret_key),
        public_auth_client=create_client(settings.url, settings.publishable_key),
        request=request,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
