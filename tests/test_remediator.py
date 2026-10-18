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
