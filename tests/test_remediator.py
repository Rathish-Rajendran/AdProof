from datetime import UTC, datetime, timedelta

import pytest

from adproof.domain.models import (
    Claim,
    ClaimSource,
    ClaimStatus,
    ClaimType,
    Issue,
    IssueAction,
    IssueCategory,
    Severity,
)
from adproof.model_client import FakeModelClient
from adproof.remediator.remediator import _RepairOutput, remediate_copy


@pytest.mark.asyncio
async def test_image_issue_remains_unresolved_by_copy_only_repair():
    issue = Issue(
        id="image-offer",
        claim_id="image-claim",
        category=IssueCategory.PRICE_DISCOUNT_MISMATCH,
        severity=Severity.HIGH,
        explanation="Image says $49; page says $60.",
        action=IssueAction.FIX,
    )
    claim = Claim(
        id="image-claim",
        claim="Only $49",
        source=ClaimSource.IMAGE,
        claim_type=ClaimType.PRICE,
        status=ClaimStatus.CONTRADICTED,
        explanation="Price mismatch",
    )
    result = await remediate_copy(
        audit_id="audit",
        candidate_id="candidate",
        ad_copy="AeroBeat headphones",
        issues=[issue],
        claims=[claim],
        evidence=[],
        model=FakeModelClient(
            [
                _RepairOutput(
                    repaired_copy="AeroBeat headphones",
                    changes=[],
                    unresolved_issue_ids=[],
                )
            ]
        ),
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert "image-offer" in result.unresolved_issue_ids
    assert result.image_edit_instructions


@pytest.mark.asyncio
async def test_copy_repair_cannot_drop_coupon_subscription_or_up_to_conditions():
    copy = (
        "AeroBeat is $60 with coupon and subscription, with up to 30 hours "
        "of battery life when noise cancellation is off."
    )
    issue = Issue(
        id="qualified-claim",
        claim_id="claim-qualified",
        category=IssueCategory.UNSUPPORTED_OBJECTIVE_CLAIM,
        severity=Severity.HIGH,
        explanation="The offer and performance conditions must be preserved.",
        action=IssueAction.FIX,
    )
    claim = Claim(
        id="claim-qualified",
        claim=copy,
        source=ClaimSource.AD_TEXT,
        claim_type=ClaimType.QUANTITATIVE_SPECIFICATION,
        status=ClaimStatus.CONTRADICTED,
        explanation="Conditions apply.",
        conditions={
            "condition_terms": {
                "coupon": "required",
                "subscription": "required",
                "noise_cancellation": "off",
            }
        },
    )
    result = await remediate_copy(
        audit_id="audit",
        candidate_id="candidate",
        ad_copy=copy,
        issues=[issue],
        claims=[claim],
        evidence=[],
        model=FakeModelClient(
            [
                _RepairOutput(
                    repaired_copy="AeroBeat is $60, with up to 30 hours of battery life.",
                    changes=[],
                    unresolved_issue_ids=[],
                )
            ]
        ),
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert "qualified-claim" in result.unresolved_issue_ids
