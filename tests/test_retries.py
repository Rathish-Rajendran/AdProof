from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from adproof.domain.models import (
    CampaignContext,
    InspectionStatus,
    Phase,
    RepairRequest,
    TypedError,
    TypedErrorCode,
    VerificationRequest,
)
from adproof.infrastructure.budget import ModelCallBudget
from adproof.model_client import GoogleGenAIClient, ModelClientError
from adproof.orchestrator.gateway import LocalGateway, UAgentsGateway
from adproof.transport.models import SpecialistOperation, SpecialistResult, SpecialistTask
from adproof.transport.pending import PendingTaskRegistry


class _Request(BaseModel):
    request_id: str


class _Response(BaseModel):
    ok: bool


class _FakeContext:
    def __init__(self, pending):
        self.pending = pending
        self.tasks: list[SpecialistTask] = []

    async def send(self, address, task, timeout):
        self.tasks.append(task)
        common = {
            "schema_version": "1.0",
            "audit_id": task.audit_id,
            "task_id": task.task_id,
            "request_id": task.request_id,
            "campaign_id": task.campaign_id,
            "candidate_id": task.candidate_id,
            "creative_version": task.creative_version,
            "phase": task.phase,
            "operation": task.operation,
            "attempt": task.attempt,
            "execution_mode": task.execution_mode,
        }
        if task.attempt == 1:
            result = SpecialistResult(
                **common,
                error_json=TypedError(
                    code=TypedErrorCode.MODEL_UNAVAILABLE,
                    message="temporary",
                    retryable=True,
                ).model_dump_json(),
            )
        else:
            result = SpecialistResult(**common, payload_json='{"ok":true}')
        assert await self.pending.accept(address, result)
        return SimpleNamespace(status=SimpleNamespace(value="success"))


@pytest.mark.asyncio
async def test_uagents_gateway_retries_with_new_task_id_attempt_and_trace_headers(monkeypatch):
    import adproof.orchestrator.gateway as gateway_module

    monkeypatch.setattr(
        gateway_module,
        "trace_headers",
        lambda: {"sentry-trace": "trace", "baggage": "bag"},
    )
    pending = PendingTaskRegistry()
    context = _FakeContext(pending)
    gateway = UAgentsGateway(
        context=context,  # type: ignore[arg-type]
        pending=pending,
        verifier_address="verifier",
        remediator_address="remediator",
        budget=ModelCallBudget(20),
        execution_mode="LIVE",
    )

    result = await gateway._dispatch(
        operation=SpecialistOperation.VERIFY,
        request=_Request(request_id="request"),
        response_model=_Response,
        audit_id="audit",
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase="ORIGINAL",
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )

    assert result.ok is True
    assert [task.attempt for task in context.tasks] == [1, 2]
    assert context.tasks[0].task_id != context.tasks[1].task_id
    assert all(
        task.trace_headers == {"sentry-trace": "trace", "baggage": "bag"} for task in context.tasks
    )


@pytest.mark.asyncio
async def test_successful_repair_result_is_not_retried(monkeypatch):
    import adproof.orchestrator.gateway as gateway_module

    monkeypatch.setattr(gateway_module, "trace_headers", lambda: None)
    pending = PendingTaskRegistry()
    context = _FakeContext(pending)

    async def send_once(address, task, timeout):
        context.tasks.append(task)
        result = SpecialistResult(
            schema_version="1.0",
            audit_id=task.audit_id,
            task_id=task.task_id,
            request_id=task.request_id,
            campaign_id=task.campaign_id,
            candidate_id=task.candidate_id,
            creative_version=task.creative_version,
            phase=task.phase,
            operation=task.operation,
            attempt=task.attempt,
            execution_mode=task.execution_mode,
            payload_json='{"ok":true}',
        )
        assert await pending.accept(address, result)
        return SimpleNamespace(status=SimpleNamespace(value="success"))

    context.send = send_once
    gateway = UAgentsGateway(
        context=context,  # type: ignore[arg-type]
        pending=pending,
        verifier_address="verifier",
        remediator_address="remediator",
        budget=ModelCallBudget(20),
        execution_mode="LIVE",
    )

    result = await gateway._dispatch(
        operation=SpecialistOperation.REPAIR,
        request=_Request(request_id="request"),
        response_model=_Response,
        audit_id="audit",
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase="REPAIR",
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )

    assert result.ok is True
    assert len(context.tasks) == 1


@pytest.mark.asyncio
async def test_local_gateway_retries_retryable_verification_and_repair_errors(monkeypatch):
    import adproof.remediator.remediator as remediator_module
    import adproof.verifier.verifier as verifier_module

    deadline = datetime.now(UTC) + timedelta(seconds=10)
    verification_request = VerificationRequest(
        audit_id="audit",
        request_id="request",
        campaign_id="campaign",
        candidate_id="candidate",
        creative_version=1,
        phase=Phase.ORIGINAL,
        ad_copy="Copy",
        landing_page_url="https://example.com",
        context=CampaignContext(
            platform="google_ads",
            jurisdiction="US",
            language="en",
            audience="adults",
            product_category="electronics",
        ),
        image_inspection_status=InspectionStatus.COMPLETE,
        deadline=deadline,
    )
    repair_request = RepairRequest(
        audit_id="audit",
        request_id="request",
        campaign_id="campaign",
        original_candidate_id="candidate",
        candidate_id="candidate",
        ad_copy="Copy",
        deadline=deadline,
    )
    retryable_error = TypedError(
        code=TypedErrorCode.MODEL_UNAVAILABLE,
        message="temporary",
        retryable=True,
    )
    verify_calls = 0
    repair_calls = 0

    async def fake_verify(request, dependencies):
        nonlocal verify_calls
        verify_calls += 1
        return SimpleNamespace(errors=[retryable_error] if verify_calls == 1 else [])

    async def fake_repair(**kwargs):
        nonlocal repair_calls
        repair_calls += 1
        return SimpleNamespace(errors=[retryable_error] if repair_calls == 1 else [])

    monkeypatch.setattr(verifier_module, "verify_campaign", fake_verify)
    monkeypatch.setattr(remediator_module, "remediate_copy", fake_repair)
    gateway = LocalGateway(object(), object())

    await gateway.verify(verification_request)
    await gateway.repair(repair_request)

    assert verify_calls == 2
    assert repair_calls == 2


class _Output(BaseModel):
    ok: bool


class _ModelApiError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.status_code = code


def _model_client(handler, budget=None):
    client = GoogleGenAIClient(api_key="unit-test-key", budget=budget)
    client.client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=handler))
    )
    return client


@pytest.mark.asyncio
async def test_genai_client_retries_one_transient_503_and_charges_both_calls(monkeypatch):
    import adproof.model_client as model_module

    monkeypatch.setattr(model_module.random, "uniform", lambda low, high: 0.0)
    calls = 0

    async def generate_content(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _ModelApiError(503, "UNAVAILABLE")
        return SimpleNamespace(
            text='{"ok":true}',
            model_version="gemini-3.8-flash",
            usage_metadata=None,
        )

    budget = ModelCallBudget(2)
    model = _model_client(generate_content, budget)
    response = await model.generate_json(
        ["prompt"],
        _Output,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
        purpose="test",
    )

    assert response.data.ok is True
    assert calls == 2
    assert budget.consumed == 2


@pytest.mark.asyncio
async def test_genai_quota_429_is_non_retryable_and_does_not_repeat(monkeypatch):
    calls = 0

    async def generate_content(**kwargs):
        nonlocal calls
        calls += 1
        raise _ModelApiError(
            429,
            "429 RESOURCE_EXHAUSTED: exceeded your current quota, check plan and billing",
        )

    model = _model_client(generate_content, ModelCallBudget(2))
    with pytest.raises(ModelClientError) as error:
        await model.generate_json(
            ["prompt"],
            _Output,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
            purpose="test",
        )

    assert calls == 1
    assert error.value.error.code == TypedErrorCode.MODEL_UNAVAILABLE
    assert error.value.error.retryable is False
    assert error.value.error.details["quota_exhausted"] is True
