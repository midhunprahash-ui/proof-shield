"""FastAPI entrypoint for the first ProofShield vertical slice."""

from fastapi import FastAPI

from proofshield import __version__
from proofshield.domain import Assessment, DisputeCase
from proofshield.verifier import CaseAssessor

app = FastAPI(
    title="ProofShield API",
    version=__version__,
    description=(
        "Human-approved evidence assessment for product-not-received chargebacks."
    ),
)
assessor = CaseAssessor()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/v1/assessments", response_model=Assessment)
def create_assessment(case: DisputeCase) -> Assessment:
    return assessor.assess(case)
