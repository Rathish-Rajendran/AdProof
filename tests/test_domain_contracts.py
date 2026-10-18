import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from adproof.domain.models import (
    CampaignInput,
    Decision,
    RepairRequest,
    RepairResult,
    TypedError,
    TypedErrorCode,
    VerificationRequest,
)

ROOT = Path(__file__).resolve().parents[1]


def test_campaign_contract_rejects_unknown_fields_at_every_level():
    value = json.loads((ROOT / "schemas/examples/CampaignInput.json").read_text())
    value["unexpected"] = True
    with pytest.raises(ValidationError):
        CampaignInput.model_validate(value)
    value.pop("unexpected")
    value["creative"]["unexpected"] = True
    with pytest.raises(ValidationError):
        CampaignInput.model_validate(value)


def test_repair_result_has_no_verdict_field():
    with pytest.raises(ValidationError):
        RepairResult(
            audit_id="audit",
            original_candidate_id="original",
            candidate_id="repaired",
            repaired_copy="copy",
            model_version="model",
            prompt_version="prompt",
            decision=Decision.PASS,
        )


def test_request_contracts_validate_full_referenced_models():
    repair = RepairRequest(
        audit_id="audit",
        request_id="request",
        campaign_id="campaign",
        original_candidate_id="original",
        candidate_id="original",
        ad_copy="copy",
        deadline=datetime.now(UTC),
    )
    assert repair.claims == []
    verification = VerificationRequest(
        audit_id="audit",
        request_id="request",
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase="ORIGINAL",
        ad_copy="copy",
        landing_page_url="https://raw.githubusercontent.com/Rathish-Rajendran/AdProof/main/test.html",
        context={},
        image_inspection_status="FAILED",
        deadline=datetime.now(UTC),
    )
    assert verification.evidence_documents == []


def test_typed_error_is_strict_and_machine_readable():
    error = TypedError(code=TypedErrorCode.TASK_TIMEOUT, message="expired")
    assert error.code.value == "TASK_TIMEOUT"
    with pytest.raises(ValidationError):
        TypedError(code="unknown", message="bad")
