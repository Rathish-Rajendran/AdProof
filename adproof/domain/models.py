from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Decision(StrEnum):
    PASS = "PASS"
    FIX_REQUIRED = "FIX_REQUIRED"
    BLOCK = "BLOCK"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Phase(StrEnum):
    ORIGINAL = "ORIGINAL"
    REPAIRED = "REPAIRED"


class ExecutionMode(StrEnum):
    LIVE = "LIVE"
    MOCK = "MOCK"
    TRANSPORT_TEST = "TRANSPORT_TEST"


class WorkflowStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class InspectionStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_PROVIDED = "NOT_PROVIDED"


class ObservationKind(StrEnum):
    VISIBLE_TEXT = "visible_text"
    VISUAL_OBSERVATION = "visual_observation"
    INFERRED_CLAIM = "inferred_claim"


class ClaimStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ClaimSource(StrEnum):
    AD_TEXT = "ad_text"
    IMAGE = "image"


class ClaimType(StrEnum):
    PRICE = "price"
    DISCOUNT = "discount"
    QUANTITATIVE_SPECIFICATION = "quantitative_specification"
    PERFORMANCE = "performance"
    HEALTH = "health"
    COMPARISON = "comparison"
    ENDORSEMENT = "endorsement"
    GUARANTEE = "guarantee"
    ENVIRONMENTAL = "environmental"
    URGENCY_SCARCITY = "urgency_scarcity"
    OTHER_OBJECTIVE = "other_objective"


class LandingPageConsistency(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    NOT_ASSESSED = "NOT_ASSESSED"


class EvidenceQuality(StrEnum):
    DIRECT = "DIRECT"
    QUALIFIED = "QUALIFIED"
    WEAK = "WEAK"
    NONE = "NONE"


class IssueCategory(StrEnum):
    UNSUPPORTED_OBJECTIVE_CLAIM = "UNSUPPORTED_OBJECTIVE_CLAIM"
    PRICE_DISCOUNT_MISMATCH = "PRICE_DISCOUNT_MISMATCH"
    UNVERIFIED_ENDORSEMENT = "UNVERIFIED_ENDORSEMENT"
    MISSING_REQUIRED_DISCLOSURE = "MISSING_REQUIRED_DISCLOSURE"
    AD_LANDING_PAGE_CONTRADICTION = "AD_LANDING_PAGE_CONTRADICTION"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueAction(StrEnum):
    FIX = "FIX"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class CoverageStatus(StrEnum):
    CHECKED = "CHECKED"
    PARTIAL = "PARTIAL"
    NOT_CHECKED = "NOT_CHECKED"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PolicyReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class PolicyEnforcement(StrEnum):
    FIX = "FIX"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class TypedErrorCode(StrEnum):
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_AUTH = "MODEL_AUTH"
    MODEL_MALFORMED_OUTPUT = "MODEL_MALFORMED_OUTPUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    TIMEOUT = "TIMEOUT"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    WORKFLOW_INTERRUPTED = "WORKFLOW_INTERRUPTED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    UNSAFE_SOURCE = "UNSAFE_SOURCE"
    SOURCE_TOO_LARGE = "SOURCE_TOO_LARGE"
    INVALID_IMAGE = "INVALID_IMAGE"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    UNSUPPORTED_CONTEXT = "UNSUPPORTED_CONTEXT"
    INTERNAL = "INTERNAL"


class TypedError(StrictModel):
    code: TypedErrorCode
    message: str
    retryable: bool = False
    source: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CampaignContext(StrictModel):
    platform: str | None = None
    jurisdiction: str | None = None
    language: str | None = None
    audience: str | None = None
    product_category: str | None = None


class CreativeInput(StrictModel):
    image_url: str = Field(min_length=1, max_length=2048)
    ad_copy: str = Field(min_length=1, max_length=4096)


class SupportingDocument(StrictModel):
    document_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    url: str = Field(min_length=1, max_length=2048)
    source_type: str


class CampaignInput(StrictModel):
    schema_version: str = "1.0"
    request_id: str = Field(min_length=1, max_length=128)
    campaign_id: str = Field(min_length=1, max_length=128)
    creative_version: int = Field(ge=1)
    creative: CreativeInput
    landing_page_url: str = Field(min_length=1, max_length=2048)
    context: CampaignContext
    evidence_documents: list[SupportingDocument] = Field(default_factory=list, max_length=3)
    product_context: dict[str, Any] = Field(default_factory=dict)
    repair_mode: str = "audit_only"

    @field_validator("evidence_documents")
    @classmethod
    def unique_document_ids(cls, docs: list[SupportingDocument]) -> list[SupportingDocument]:
        ids = [doc.document_id for doc in docs]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence document IDs must be unique")
        return docs


class CreativeCandidate(StrictModel):
    campaign_id: str
    candidate_id: str
    creative_version: int = Field(ge=1)
    phase: Phase
    ad_copy: str = Field(max_length=4096)
    source_image_sha256: str
    model_input_sha256: str
    asset_ref: str
    context: CampaignContext
    transformation_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ImageRegion(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class Observation(StrictModel):
    observation_id: str
    kind: ObservationKind
    text: str
    region: ImageRegion | None = None
    uncertainty_note: str | None = None


class InspectionResult(StrictModel):
    candidate_id: str
    image_sha256: str
    model_version: str
    prompt_version: str
    status: InspectionStatus
    observations: list[Observation] = Field(default_factory=list)
    readability: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    errors: list[TypedError] = Field(default_factory=list)


class VerificationRequest(StrictModel):
    schema_version: str = "1.0"
    audit_id: str
    request_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int = Field(ge=1)
    phase: Phase
    ad_copy: str = Field(max_length=4096)
    landing_page_url: str
    evidence_documents: list[SupportingDocument] = Field(default_factory=list, max_length=3)
    context: CampaignContext
    product_context: dict[str, Any] = Field(default_factory=dict)
    image_observations: list[Observation] = Field(default_factory=list)
    image_inspection_status: InspectionStatus
    deadline: datetime


class Evidence(StrictModel):
    id: str
    source_url: str
    excerpt: str
    source_type: str
    retrieved_at: datetime
    document_id: str | None = None
    snapshot_id: str
    content_sha256: str
    locator: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)


class Claim(StrictModel):
    id: str
    claim: str
    source: ClaimSource
    claim_type: ClaimType
    status: ClaimStatus
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str
    original_wording: str | None = None
    location: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    observation_id: str | None = None
    uncertainty: str | None = None
    derivation: dict[str, Any] = Field(default_factory=dict)
    landing_page_consistency: LandingPageConsistency = LandingPageConsistency.NOT_ASSESSED
    evidence_quality: EvidenceQuality = EvidenceQuality.NONE
    confidence: float | None = Field(default=None, ge=0, le=1)


class Issue(StrictModel):
    id: str
    claim_id: str | None = None
    category: IssueCategory
    subtype: str | None = None
    severity: Severity
    explanation: str
    suggested_fix: str | None = None
    action: IssueAction
    policy_reference: str | None = None


class RepairRequest(StrictModel):
    schema_version: str = "1.0"
    audit_id: str
    request_id: str
    campaign_id: str
    original_candidate_id: str
    candidate_id: str
    ad_copy: str = Field(max_length=4096)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    deadline: datetime


class CoverageItem(StrictModel):
    status: CoverageStatus
    reason: str | None = None


class Coverage(StrictModel):
    ad_text: CoverageItem
    landing_page: CoverageItem
    supporting_documents: CoverageItem
    image: CoverageItem
    platform_policy: CoverageItem


class PolicyCheck(StrictModel):
    rule_id: str
    applicable: bool
    review_status: PolicyReviewStatus
    enforcement: PolicyEnforcement
    checked: bool
    finding: str | None = None
    predicate_established: bool = False


class VerificationResult(StrictModel):
    schema_version: str = "1.0"
    audit_id: str
    campaign_id: str
    candidate_id: str
    creative_version: int
    phase: Phase
    decision: Decision
    audit_complete: bool
    evidence_scope: str
    scope_notes: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    coverage: Coverage
    policy_checks: list[PolicyCheck] = Field(default_factory=list)
    policy_catalog_version: str
    errors: list[TypedError] = Field(default_factory=list)
    ignored_statements: list[dict[str, str]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class RepairChange(StrictModel):
    issue_ids: list[str] = Field(min_length=1)
    before: str
    after: str
    rationale: str


class RepairResult(StrictModel):
    audit_id: str
    original_candidate_id: str
    candidate_id: str
    repaired_copy: str = Field(max_length=4096)
    changes: list[RepairChange] = Field(default_factory=list)
    unresolved_issue_ids: list[str] = Field(default_factory=list)
    image_edit_instructions: list[str] = Field(default_factory=list)
    model_version: str
    prompt_version: str
    errors: list[TypedError] = Field(default_factory=list)


class AuditReport(StrictModel):
    audit_id: str
    execution_mode: ExecutionMode
    workflow_status: WorkflowStatus
    scope: str
    original_candidate: CreativeCandidate
    original_audit: VerificationResult | None = None
    repair_proposal: RepairResult | None = None
    revised_candidate: CreativeCandidate | None = None
    revised_audit: VerificationResult | None = None
    selected_candidate_id: str
    final_decision: Decision
    final_decision_basis: str
    repair_verified: bool
    unresolved_issues: list[Issue] = Field(default_factory=list)
    coverage: Coverage | None = None
    errors: list[TypedError] = Field(default_factory=list)
    source_versions: dict[str, str] = Field(default_factory=dict)
    model_provider: str = "unknown"
    configured_model: str = "unknown"
    model_specs: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    timestamps: dict[str, datetime] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)


class ReportSelection(StrictModel):
    selected_candidate_id: str
    final_decision: Decision
    final_decision_basis: str
    workflow_status: WorkflowStatus
    repair_verified: bool
    unresolved_issues: list[Issue] = Field(default_factory=list)
    coverage: Coverage | None = None
    errors: list[TypedError] = Field(default_factory=list)


class PriceDerivation(StrictModel):
    original_price: Decimal
    current_price: Decimal
    percent_off: Decimal
    currency: str
    quantity: int = 1
    variant: str | None = None
    region: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
