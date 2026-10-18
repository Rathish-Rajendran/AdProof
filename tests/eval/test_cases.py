from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from adproof.domain.models import (
    CampaignInput,
    Coverage,
    CoverageItem,
    CoverageStatus,
    Decision,
    ExecutionMode,
    InspectionStatus,
    Issue,
    IssueAction,
    IssueCategory,
    Phase,
    RepairResult,
    Severity,
    TypedError,
    TypedErrorCode,
    VerificationResult,
)
from adproof.eval import _reported_model_versions
from adproof.infrastructure.budget import ModelCallBudget
from adproof.infrastructure.safe_http import FetchedSource
from adproof.infrastructure.settings import Settings
from adproof.infrastructure.store import SQLiteStore
from adproof.orchestrator.workflow import WorkflowDependencies, run_campaign

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    1: (
        "unsafe copy + neutral image",
        (
            (
                "tests/test_verifier.py",
                "test_contradicted_landing_page_assessment_establishes_active_rule",
            ),
            (
                "tests/test_verifier.py",
                "test_price_arithmetic_flags_forty_percent_when_page_computes_twenty_five",
            ),
        ),
    ),
    2: (
        "one copy repair + neutral image",
        (
            ("tests/eval/test_cases.py", "test_copy_repair_reverifies_without_changing_image"),
            ("tests/test_verifier.py", "test_up_to_conditions_are_preserved_on_supported_claim"),
        ),
    ),
    3: (
        "copy repair + original Only-$49 image",
        (
            ("tests/eval/test_cases.py", "test_copy_repair_reverifies_without_changing_image"),
            ("tests/test_remediator.py", "test_image_issue_remains_unresolved_by_copy_only_repair"),
        ),
    ),
    4: (
        "correct original copy + neutral image",
        (
            ("tests/test_decision.py", "test_report_selection_branches"),
            ("tests/test_verifier.py", "test_up_to_conditions_are_preserved_on_supported_claim"),
        ),
    ),
    5: (
        "missing endorsement support",
        (
            (
                "tests/test_verifier.py",
                "test_unsubstantiated_endorsement_and_health_claims_route_safely",
            ),
        ),
    ),
    6: (
        "seller repeats clinically-proven claim",
        (
            (
                "tests/test_verifier.py",
                "test_unsubstantiated_endorsement_and_health_claims_route_safely",
            ),
        ),
    ),
    7: (
        "blurry material price",
        (
            (
                "tests/test_inspector.py",
                "test_materially_unreadable_image_produces_partial_coverage_without_ocr",
            ),
        ),
    ),
    8: (
        "page unavailable or empty",
        (("tests/test_verifier.py", "test_unavailable_landing_page_is_typed_and_requires_review"),),
    ),
    9: (
        "one bounded transient retry",
        (
            (
                "tests/test_retries.py",
                "test_genai_client_retries_one_transient_503_and_charges_both_calls",
            ),
            (
                "tests/test_retries.py",
                "test_uagents_gateway_retries_with_new_task_id_attempt_and_trace_headers",
            ),
        ),
    ),
    10: (
        "re-audit failure keeps original last verified",
        (("tests/test_decision.py", "test_report_selection_branches"),),
    ),
    11: (
        "duplicate ACP message or action",
        (
            (
                "tests/test_store.py",
                "test_chat_message_dedupe_and_card_action_idempotency_survive_restart",
            ),
            (
                "tests/test_cards.py",
                "test_duplicate_run_repair_action_never_starts_a_second_repair",
            ),
        ),
    ),
    12: (
        "forged, late, or wrong-candidate specialist response",
        (
            (
                "tests/test_transport.py",
                "test_result_from_separate_handler_correlates_against_sender_and_task",
            ),
        ),
    ),
    13: (
        "currency, variant, or ANC condition mismatch",
        (
            (
                "tests/test_verifier.py",
                "test_discount_context_mismatch_requires_review_without_arithmetic",
            ),
            ("tests/test_verifier.py", "test_claim_context_mismatches_prevent_price_comparison"),
        ),
    ),
    14: (
        "up-to and operating conditions",
        (
            ("tests/test_verifier.py", "test_up_to_conditions_are_preserved_on_supported_claim"),
            (
                "tests/test_remediator.py",
                "test_copy_repair_cannot_drop_coupon_subscription_or_up_to_conditions",
            ),
        ),
    ),
    15: (
        "prompt injection in source",
        (
            (
                "tests/test_verifier.py",
                "test_injected_quote_is_rejected_as_invalid_evidence_and_routes_to_review",
            ),
        ),
    ),
    16: (
        "private IP, redirect, oversize, or fake image",
        (
            (
                "tests/test_infrastructure_safety.py",
                "test_redirect_is_revalidated_before_second_request",
            ),
            ("tests/test_infrastructure_safety.py", "test_connected_private_peer_is_rejected"),
            (
                "tests/test_infrastructure_safety.py",
                "test_image_freezing_canonicalizes_png_and_rejects_html",
            ),
        ),
    ),
    17: (
        "invalid evidence quote",
        (
            (
                "tests/test_verifier.py",
                "test_injected_quote_is_rejected_as_invalid_evidence_and_routes_to_review",
            ),
        ),
    ),
    18: (
        "unsupported campaign context",
        (("tests/test_verifier.py", "test_unsupported_context_requires_human_review"),),
    ),
    19: (
        "Sentry unavailable",
        (("tests/test_telemetry.py", "test_sentry_init_failure_and_absent_dsn_do_not_raise"),),
    ),
    20: (
        "owner-bound audit lookup",
        (
            ("tests/test_store.py", "test_store_binds_ownership_idempotency_and_retention"),
            ("tests/test_cards.py", "test_card_action_is_owner_and_session_bound"),
        ),
    ),
    21: (
        "no invented universal disclosure or white-coat violation",
        (
            (
                "tests/test_decision.py",
                "test_severity_never_causes_block_and_uncertainty_precedes_repair",
            ),
        ),
    ),
    22: (
        "decision precedence",
        (
            (
                "tests/test_decision.py",
                "test_decision_precedence_requires_applicable_active_blocking_predicate",
            ),
        ),
    ),
    23: (
        "missing key, malformed JSON, or auth error",
        (
            ("tests/test_retries.py", "test_genai_quota_429_is_non_retryable_and_does_not_repeat"),
            (
                "tests/test_verifier.py",
                "test_model_unavailable_returns_incomplete_audit_for_human_review",
            ),
            ("tests/eval/test_cases.py", "test_quota_failure_stops_further_attempts_for_one_case"),
        ),
    ),
    24: (
        "session restart, retention, or replay",
        (
            (
                "tests/test_store.py",
                "test_chat_message_dedupe_and_card_action_idempotency_survive_restart",
            ),
            ("tests/test_store.py", "test_store_binds_ownership_idempotency_and_retention"),
        ),
    ),
}


def test_reported_model_versions_use_successful_provider_calls_only() -> None:
    calls = [
        {
            "model": "gemini-3.6-flash",
            "reported_model_version": "gemini-3.6-flash",
            "purpose": "image_inspection",
        },
        {"model": "gemini-3.5-flash", "reported_model_version": None},
        {"model": "gemini-3.5-flash", "error": "MODEL_UNAVAILABLE"},
    ]

    assert _reported_model_versions(calls) == ["gemini-3.6-flash"]


def _test_names(path: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


@pytest.mark.parametrize("case_number", range(1, 25))
def test_case_has_offline_regression_coverage(case_number):
    title, references = CASES[case_number]
    assert title
    assert references
    for path, test_name in references:
        assert test_name in _test_names(path), (
            f"case {case_number} references missing test {path}::{test_name}"
        )


@pytest.mark.parametrize(
    ("case_number", "expected_image", "expected_mode"),
    [
        (1, "aerobeat-neutral.png", "repair_once"),
        (2, "aerobeat-neutral.png", "audit_only"),
        (3, "aerobeat-only49.png", "repair_once"),
        (4, "aerobeat-neutral.png", "audit_only"),
    ],
)
def test_first_four_case_fixtures_match_the_demo_matrix(case_number, expected_image, expected_mode):
    filenames = {
        1: "case01_unsafe_neutral.json",
        2: "case02_supported_neutral.json",
        3: "case03_unsafe_only49.json",
        4: "case04_correct_neutral.json",
    }
    fixture = ROOT / "data/fixtures/cases" / filenames[case_number]
    campaign = CampaignInput.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert campaign.creative.image_url.endswith(expected_image)
    assert campaign.repair_mode == expected_mode
    assert "/d3bebf537bb2ac8826a2fa0ba339fcbdfd723efe/" in campaign.creative.image_url
    assert "/d3bebf537bb2ac8826a2fa0ba339fcbdfd723efe/" in campaign.landing_page_url
    if case_number in {1, 3}:
        assert campaign.creative.ad_copy.startswith("AeroBeat headphones are completely waterproof")
    if case_number == 1:
        demo = CampaignInput.model_validate_json(
            (ROOT / "data/fixtures/demo_campaign.json").read_text(encoding="utf-8")
        )
        assert demo == campaign


@pytest.mark.asyncio
async def test_quota_failure_stops_further_attempts_for_one_case(tmp_path):
    campaign = CampaignInput.model_validate_json(
        (ROOT / "data/fixtures/cases/case01_unsafe_neutral.json").read_text(encoding="utf-8")
    )
    image_bytes = (ROOT / "data/fixtures/public/aerobeat-neutral.png").read_bytes()

    class FakeHttp:
        async def fetch(self, url, *, max_bytes):
            return FetchedSource(
                url=url,
                status_code=200,
                headers={"content-type": "image/png"},
                content=image_bytes,
            )

    class FakeInspector:
        calls = 0

        async def inspect(self, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                status=InspectionStatus.FAILED,
                observations=[],
                model_version="gemini-3.8-flash",
                errors=[
                    TypedError(
                        code=TypedErrorCode.MODEL_UNAVAILABLE,
                        message="quota exhausted",
                        retryable=False,
                    )
                ],
            )

    class FakeGateway:
        verify_calls = 0
        repair_calls = 0

        async def verify(self, request):
            self.verify_calls += 1

        async def repair(self, request):
            self.repair_calls += 1

    http = FakeHttp()
    inspector = FakeInspector()
    gateway = FakeGateway()
    dependencies = WorkflowDependencies(
        http=http,
        inspector=inspector,
        gateway=gateway,
        store=SQLiteStore(tmp_path / "quota.sqlite3"),
        budget=ModelCallBudget(2),
        settings=Settings(runtime_dir=tmp_path),
        execution_mode=ExecutionMode.LIVE,
    )
    report = await run_campaign(
        campaign,
        owner="owner",
        session_id="session",
        dependencies=dependencies,
    )
    assert inspector.calls == 1
    assert gateway.verify_calls == gateway.repair_calls == 0
    assert report.final_decision == Decision.HUMAN_REVIEW
    assert any(error.code == TypedErrorCode.MODEL_UNAVAILABLE for error in report.errors)


@pytest.mark.parametrize(
    ("case_number", "expected_decision"),
    [(1, Decision.PASS), (3, Decision.FIX_REQUIRED)],
)
@pytest.mark.asyncio
async def test_copy_repair_reverifies_without_changing_image(
    tmp_path, case_number, expected_decision
):
    filenames = {1: "case01_unsafe_neutral.json", 3: "case03_unsafe_only49.json"}
    campaign = CampaignInput.model_validate_json(
        (ROOT / "data/fixtures/cases" / filenames[case_number]).read_text(encoding="utf-8")
    )
    image_name = "aerobeat-neutral.png" if case_number == 1 else "aerobeat-only49.png"
    image_bytes = (ROOT / "data/fixtures/public" / image_name).read_bytes()
    coverage = Coverage(
        ad_text=CoverageItem(status=CoverageStatus.CHECKED),
        landing_page=CoverageItem(status=CoverageStatus.CHECKED),
        supporting_documents=CoverageItem(status=CoverageStatus.NOT_APPLICABLE),
        image=CoverageItem(status=CoverageStatus.CHECKED),
        platform_policy=CoverageItem(status=CoverageStatus.CHECKED),
    )
    image_issue = Issue(
        id="image-price",
        category=IssueCategory.PRICE_DISCOUNT_MISMATCH,
        severity=Severity.HIGH,
        explanation="The frozen image still says Only $49.",
        action=IssueAction.FIX,
    )

    class FakeHttp:
        async def fetch(self, url, *, max_bytes):
            return FetchedSource(
                url=url,
                status_code=200,
                headers={"content-type": "image/png"},
                content=image_bytes,
            )

    class FakeInspector:
        async def inspect(self, **kwargs):
            return SimpleNamespace(
                status=InspectionStatus.COMPLETE,
                observations=[],
                model_version="fake-model",
                errors=[],
            )

    class FakeGateway:
        def __init__(self):
            self.verification_requests = []

        async def verify(self, request):
            self.verification_requests.append(request)
            revised = request.phase == Phase.REPAIRED
            decision = expected_decision if revised else Decision.FIX_REQUIRED
            return VerificationResult(
                audit_id=request.audit_id,
                campaign_id=request.campaign_id,
                candidate_id=request.candidate_id,
                creative_version=request.creative_version,
                phase=request.phase,
                decision=decision,
                audit_complete=True,
                evidence_scope="Fake bounded test evidence.",
                issues=[image_issue] if case_number == 3 else [],
                coverage=coverage,
                policy_catalog_version="fake-policy",
            )

        async def repair(self, request):
            return RepairResult(
                audit_id=request.audit_id,
                original_candidate_id=request.original_candidate_id,
                candidate_id="candidate-repaired",
                repaired_copy="AeroBeat AB-01 headphones are splash-resistant.",
                model_version="fake-model",
                prompt_version="test",
                unresolved_issue_ids=[image_issue.id] if case_number == 3 else [],
            )

    gateway = FakeGateway()
    dependencies = WorkflowDependencies(
        http=FakeHttp(),
        inspector=FakeInspector(),
        gateway=gateway,
        store=SQLiteStore(tmp_path / f"case-{case_number}.sqlite3"),
        budget=ModelCallBudget(4),
        settings=Settings(runtime_dir=tmp_path),
        execution_mode=ExecutionMode.MOCK,
    )
    report = await run_campaign(
        campaign,
        owner="owner",
        session_id="session",
        dependencies=dependencies,
    )

    assert len(gateway.verification_requests) == 2
    assert report.final_decision == expected_decision
    assert report.revised_candidate is not None
    assert (
        report.original_candidate.source_image_sha256
        == report.revised_candidate.source_image_sha256
    )
    assert (
        report.original_candidate.model_input_sha256 == report.revised_candidate.model_input_sha256
    )
    assert report.revised_candidate.transformation_metadata["image_unchanged"] is True
