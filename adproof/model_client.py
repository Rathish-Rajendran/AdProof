from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from adproof.domain.models import TypedError, TypedErrorCode
from adproof.infrastructure.budget import BudgetExhausted, ModelCallBudget
from adproof.infrastructure.settings import ModelSpec, Settings
from adproof.infrastructure.telemetry import record_event

PROMPT_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class ModelResponse:
    data: Any
    model_version: str
    usage: dict[str, int | None]
    latency: float


class ModelClient(Protocol):
    async def generate_json(
        self,
        prompt_parts: Sequence[str | tuple[bytes, str]],
        schema: type[BaseModel] | dict[str, Any],
        *,
        deadline: datetime,
        purpose: str,
    ) -> ModelResponse: ...


class ModelClientError(RuntimeError):
    def __init__(self, error: TypedError):
        super().__init__(error.message)
        self.error = error


def _schema_for(schema: type[BaseModel] | dict[str, Any]) -> dict[str, Any]:
    return schema.model_json_schema() if isinstance(schema, type) else schema


def _validate_output(value: Any, schema: type[BaseModel] | dict[str, Any]) -> Any:
    return schema.model_validate(value) if isinstance(schema, type) else value


class GoogleGenAIClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-3.5-flash",
        budget: ModelCallBudget | None = None,
        record_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.model = model
        self.budget = budget
        self.call_records: list[dict[str, Any]] = []
        self._record_callback = record_callback
        key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        if not key:
            raise ModelClientError(
                TypedError(
                    code=TypedErrorCode.MODEL_AUTH, message="GEMINI_API_KEY is not configured"
                )
            )
        try:
            from google import genai

            self.client = genai.Client(api_key=key)
        except Exception as exc:
            raise ModelClientError(
                TypedError(
                    code=TypedErrorCode.MODEL_UNAVAILABLE,
                    message="Google Gen AI client could not be initialized",
                    retryable=True,
                )
            ) from exc

    def _record_call(self, record: dict[str, Any]) -> None:
        self.call_records.append(record)
        if self._record_callback is not None:
            self._record_callback(record)

    async def generate_json(
        self,
        prompt_parts: Sequence[str | tuple[bytes, str]],
        schema: type[BaseModel] | dict[str, Any],
        *,
        deadline: datetime,
        purpose: str,
    ) -> ModelResponse:
        from google.genai import types

        schema_json = _schema_for(schema)
        contents: list[Any] = []
        for part in prompt_parts:
            if isinstance(part, tuple):
                contents.append(types.Part.from_bytes(data=part[0], mime_type=part[1]))
            else:
                contents.append(part)
        start = time.monotonic()
        correction = False
        transport_retries = 0
        while True:
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise ModelClientError(
                    TypedError(code=TypedErrorCode.TIMEOUT, message="model call deadline expired")
                )
            if correction:
                contents.append(
                    "Your previous response did not validate. Return corrected JSON matching the schema exactly."
                )
            if self.budget:
                try:
                    await self.budget.reserve()
                    await self.budget.consume()
                except BudgetExhausted as exc:
                    raise ModelClientError(
                        TypedError(code=TypedErrorCode.BUDGET_EXHAUSTED, message=str(exc))
                    ) from exc
            try:
                call_started = time.monotonic()
                response = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_json_schema=schema_json,
                            thinking_config=types.ThinkingConfig(thinking_level="low"),
                        ),
                    ),
                    timeout=remaining,
                )
            except TimeoutError as exc:
                self._record_call(
                    {
                        "purpose": purpose,
                        "model": self.model,
                        "reported_model_version": None,
                        "latency_seconds": time.monotonic() - call_started,
                        "error": TypedErrorCode.TIMEOUT.value,
                    }
                )
                raise ModelClientError(
                    TypedError(
                        code=TypedErrorCode.TIMEOUT, message="model call timed out", retryable=True
                    )
                ) from exc
            except Exception as exc:
                status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                status_text = str(status)
                error_text = str(exc)
                quota_exhausted = (
                    "429" in status_text or "resource_exhausted" in error_text.casefold()
                ) and bool(
                    re.search(
                        r"quota|billing|resource[_ -]?exhausted|exceeded.*limit",
                        error_text,
                        re.IGNORECASE,
                    )
                )
                code = (
                    TypedErrorCode.MODEL_AUTH
                    if status_text in {"401", "403"}
                    else TypedErrorCode.MODEL_UNAVAILABLE
                )
                retryable = code == TypedErrorCode.MODEL_UNAVAILABLE and not quota_exhausted
                self._record_call(
                    {
                        "purpose": purpose,
                        "model": self.model,
                        "reported_model_version": None,
                        "latency_seconds": time.monotonic() - call_started,
                        "error": code.value,
                        "http_status": status_text,
                        "quota_exhausted": quota_exhausted,
                    }
                )
                remaining = (deadline - datetime.now(UTC)).total_seconds()
                delay = random.uniform(0.25, 0.75)
                if retryable and transport_retries == 0 and remaining > delay + 0.1:
                    transport_retries += 1
                    record_event(
                        "retry_scheduled",
                        role="model_client",
                        stage=purpose,
                        duration=delay,
                        result=code.value,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise ModelClientError(
                    TypedError(
                        code=code,
                        message=(
                            "Gemini quota is exhausted."
                            if quota_exhausted
                            else f"Gemini request failed ({status or type(exc).__name__})"
                        ),
                        retryable=retryable,
                        details={
                            "http_status": status_text,
                            "quota_exhausted": quota_exhausted,
                        },
                    )
                ) from exc
            try:
                parsed = json.loads(response.text or "")
                data = _validate_output(parsed, schema)
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                self._record_call(
                    {
                        "purpose": purpose,
                        "model": self.model,
                        "reported_model_version": getattr(response, "model_version", None),
                        "latency_seconds": time.monotonic() - call_started,
                        "error": TypedErrorCode.MODEL_MALFORMED_OUTPUT.value,
                    }
                )
                if correction:
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.MODEL_MALFORMED_OUTPUT,
                            message=f"model output did not validate for {purpose}",
                        )
                    ) from exc
                correction = True
                continue
            usage = getattr(response, "usage_metadata", None)
            usage_values = {
                "prompt_tokens": getattr(usage, "prompt_token_count", None),
                "candidate_tokens": getattr(usage, "candidates_token_count", None),
            }
            reported_model_version = getattr(response, "model_version", None)
            self._record_call(
                {
                    "purpose": purpose,
                    "model": reported_model_version or self.model,
                    "reported_model_version": reported_model_version,
                    "latency_seconds": time.monotonic() - call_started,
                    "usage": usage_values,
                }
            )
            return ModelResponse(
                data=data,
                model_version=getattr(response, "model_version", None) or self.model,
                usage=usage_values,
                latency=time.monotonic() - start,
            )


class OllamaClient:
    def __init__(
        self,
        *,
        model: str = "qwen2.5vl:3b",
        base_url: str = "http://127.0.0.1:11434",
        budget: ModelCallBudget | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        record_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.budget = budget
        self.transport = transport
        self.call_records: list[dict[str, Any]] = []
        self._record_callback = record_callback

    def _record_call(self, record: dict[str, Any]) -> None:
        self.call_records.append(record)
        if self._record_callback is not None:
            self._record_callback(record)

    async def generate_json(
        self,
        prompt_parts: Sequence[str | tuple[bytes, str]],
        schema: type[BaseModel] | dict[str, Any],
        *,
        deadline: datetime,
        purpose: str,
    ) -> ModelResponse:
        schema_json = _schema_for(schema)
        text_parts = [str(part) for part in prompt_parts if not isinstance(part, tuple)]
        images = [
            base64.b64encode(part[0]).decode("ascii")
            for part in prompt_parts
            if isinstance(part, tuple)
        ]
        prompt = "\n\n".join(text_parts)
        started = time.monotonic()
        correction = False
        transport_retries = 0
        async with httpx.AsyncClient(
            transport=self.transport, trust_env=False, timeout=None
        ) as client:
            while True:
                remaining = (deadline - datetime.now(UTC)).total_seconds()
                if remaining <= 0:
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.TIMEOUT,
                            message="model call deadline expired",
                        )
                    )
                content = prompt
                if correction:
                    content = (
                        f"{prompt}\n\nYour previous response did not validate. "
                        "Return corrected JSON matching the schema exactly."
                    )
                if self.budget:
                    try:
                        await self.budget.reserve()
                        await self.budget.consume()
                    except BudgetExhausted as exc:
                        raise ModelClientError(
                            TypedError(code=TypedErrorCode.BUDGET_EXHAUSTED, message=str(exc))
                        ) from exc

                call_started = time.monotonic()
                try:
                    response = await asyncio.wait_for(
                        client.post(
                            f"{self.base_url}/api/chat",
                            json={
                                "model": self.model,
                                "messages": [
                                    {"role": "user", "content": content, "images": images}
                                ],
                                "format": schema_json,
                                "stream": False,
                                "options": {"temperature": 0},
                            },
                        ),
                        timeout=remaining,
                    )
                except TimeoutError as exc:
                    self._record_call(
                        {
                            "purpose": purpose,
                            "model": self.model,
                            "reported_model_version": None,
                            "latency_seconds": time.monotonic() - call_started,
                            "error": TypedErrorCode.TIMEOUT.value,
                        }
                    )
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.TIMEOUT,
                            message="model call timed out",
                            retryable=True,
                        )
                    ) from exc
                except httpx.TransportError as exc:
                    self._record_call(
                        {
                            "purpose": purpose,
                            "model": self.model,
                            "reported_model_version": None,
                            "latency_seconds": time.monotonic() - call_started,
                            "error": TypedErrorCode.MODEL_UNAVAILABLE.value,
                            "http_status": None,
                        }
                    )
                    delay = random.uniform(0.25, 0.75)
                    if (
                        transport_retries == 0
                        and (deadline - datetime.now(UTC)).total_seconds() > delay + 0.1
                    ):
                        transport_retries += 1
                        record_event(
                            "retry_scheduled",
                            role="model_client",
                            stage=purpose,
                            duration=delay,
                            result=TypedErrorCode.MODEL_UNAVAILABLE.value,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.MODEL_UNAVAILABLE,
                            message=f"Ollama request failed ({type(exc).__name__})",
                            retryable=True,
                        )
                    ) from exc

                response_text = response.text
                model_not_found = "model not found" in response_text.casefold()
                if response.status_code == 404 or model_not_found:
                    self._record_call(
                        {
                            "purpose": purpose,
                            "model": self.model,
                            "reported_model_version": None,
                            "latency_seconds": time.monotonic() - call_started,
                            "error": TypedErrorCode.MODEL_UNAVAILABLE.value,
                            "http_status": response.status_code,
                        }
                    )
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.MODEL_UNAVAILABLE,
                            message=f"Ollama model {self.model} is not pulled",
                            retryable=False,
                            details={"http_status": response.status_code},
                        )
                    )
                if response.status_code >= 500:
                    self._record_call(
                        {
                            "purpose": purpose,
                            "model": self.model,
                            "reported_model_version": None,
                            "latency_seconds": time.monotonic() - call_started,
                            "error": TypedErrorCode.MODEL_UNAVAILABLE.value,
                            "http_status": response.status_code,
                        }
                    )
                    delay = random.uniform(0.25, 0.75)
                    if (
                        transport_retries == 0
                        and (deadline - datetime.now(UTC)).total_seconds() > delay + 0.1
                    ):
                        transport_retries += 1
                        record_event(
                            "retry_scheduled",
                            role="model_client",
                            stage=purpose,
                            duration=delay,
                            result=TypedErrorCode.MODEL_UNAVAILABLE.value,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.MODEL_UNAVAILABLE,
                            message=f"Ollama request failed (HTTP {response.status_code})",
                            retryable=True,
                            details={"http_status": response.status_code},
                        )
                    )
                if response.is_error:
                    self._record_call(
                        {
                            "purpose": purpose,
                            "model": self.model,
                            "reported_model_version": None,
                            "latency_seconds": time.monotonic() - call_started,
                            "error": TypedErrorCode.MODEL_UNAVAILABLE.value,
                            "http_status": response.status_code,
                        }
                    )
                    raise ModelClientError(
                        TypedError(
                            code=TypedErrorCode.MODEL_UNAVAILABLE,
                            message=f"Ollama request failed (HTTP {response.status_code})",
                            retryable=False,
                            details={"http_status": response.status_code},
                        )
                    )

                reported_model_version: str | None = None
                try:
                    envelope = response.json()
                    if not isinstance(envelope, dict):
                        raise TypeError("Ollama response must be a JSON object")
                    reported_model_version = envelope.get("model")
                    message = envelope["message"]
                    if (
                        not isinstance(reported_model_version, str)
                        or not reported_model_version
                        or not isinstance(message, dict)
                        or not isinstance(message.get("content"), str)
                    ):
                        raise TypeError("Ollama response is missing model or message content")
                    parsed = json.loads(message["content"])
                    data = _validate_output(parsed, schema)
                except (json.JSONDecodeError, KeyError, TypeError, ValidationError) as exc:
                    self._record_call(
                        {
                            "purpose": purpose,
                            "model": self.model,
                            "reported_model_version": reported_model_version,
                            "latency_seconds": time.monotonic() - call_started,
                            "error": TypedErrorCode.MODEL_MALFORMED_OUTPUT.value,
                        }
                    )
                    if correction:
                        raise ModelClientError(
                            TypedError(
                                code=TypedErrorCode.MODEL_MALFORMED_OUTPUT,
                                message=f"model output did not validate for {purpose}",
                            )
                        ) from exc
                    correction = True
                    continue

                prompt_tokens = envelope.get("prompt_eval_count")
                candidate_tokens = envelope.get("eval_count")
                usage_values = {
                    "prompt_tokens": prompt_tokens if isinstance(prompt_tokens, int) else None,
                    "candidate_tokens": candidate_tokens
                    if isinstance(candidate_tokens, int)
                    else None,
                }
                self._record_call(
                    {
                        "purpose": purpose,
                        "model": self.model,
                        "reported_model_version": reported_model_version,
                        "latency_seconds": time.monotonic() - call_started,
                        "usage": usage_values,
                    }
                )
                return ModelResponse(
                    data=data,
                    model_version=reported_model_version,
                    usage=usage_values,
                    latency=time.monotonic() - started,
                )


class RoutingModelClient(ModelClient):
    def __init__(self, settings: Settings, budget: ModelCallBudget | None = None):
        self.settings = settings
        self.budget = budget
        self._clients: dict[str, ModelClient] = {}
        self.call_records: list[dict[str, Any]] = []

    def _record_call(self, spec: ModelSpec, record: dict[str, Any]) -> None:
        self.call_records.append({**record, "provider": spec.provider, "model_spec": str(spec)})

    def _client_for(self, purpose: str) -> ModelClient:
        spec = ModelSpec.parse(self.settings.model_spec_for(purpose))
        key = str(spec)
        client = self._clients.get(key)
        if client is None:

            def callback(record: dict[str, Any]) -> None:
                self._record_call(spec, record)

            if spec.provider == "ollama":
                client = OllamaClient(
                    model=spec.model,
                    base_url=self.settings.ollama_base_url,
                    budget=self.budget,
                    record_callback=callback,
                )
            else:
                client = GoogleGenAIClient(
                    model=spec.model,
                    budget=self.budget,
                    record_callback=callback,
                )
            self._clients[key] = client
        return client

    async def generate_json(
        self,
        prompt_parts: Sequence[str | tuple[bytes, str]],
        schema: type[BaseModel] | dict[str, Any],
        *,
        deadline: datetime,
        purpose: str,
    ) -> ModelResponse:
        return await self._client_for(purpose).generate_json(
            prompt_parts,
            schema,
            deadline=deadline,
            purpose=purpose,
        )


def build_model_client(settings: Settings, budget: ModelCallBudget | None = None) -> ModelClient:
    return RoutingModelClient(settings, budget)


class FakeModelClient:
    def __init__(self, responses: Sequence[Any], *, model_version: str = "fake-model"):
        self.responses = list(responses)
        self.model_version = model_version
        self.calls: list[str] = []

    async def generate_json(
        self,
        prompt_parts: Sequence[str | tuple[bytes, str]],
        schema: type[BaseModel] | dict[str, Any],
        *,
        deadline: datetime,
        purpose: str,
    ) -> ModelResponse:
        if datetime.now(UTC) >= deadline:
            raise ModelClientError(
                TypedError(code=TypedErrorCode.TIMEOUT, message="model call deadline expired")
            )
        self.calls.append(purpose)
        if not self.responses:
            raise ModelClientError(
                TypedError(
                    code=TypedErrorCode.MODEL_UNAVAILABLE, message="no fake response configured"
                )
            )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        data = _validate_output(response, schema)
        return ModelResponse(data=data, model_version=self.model_version, usage={}, latency=0.0)
