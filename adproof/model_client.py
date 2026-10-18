from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from adproof.domain.models import TypedError, TypedErrorCode
from adproof.infrastructure.budget import BudgetExhausted, ModelCallBudget

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
        model: str = "gemini-3.8-flash",
        budget: ModelCallBudget | None = None,
    ):
        self.model = model
        self.budget = budget
        self.call_records: list[dict[str, Any]] = []
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
                self.call_records.append(
                    {
                        "purpose": purpose,
                        "model": self.model,
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
                code = (
                    TypedErrorCode.MODEL_AUTH
                    if status_text in {"401", "403"}
                    else TypedErrorCode.MODEL_UNAVAILABLE
                )
                self.call_records.append(
                    {
                        "purpose": purpose,
                        "model": self.model,
                        "latency_seconds": time.monotonic() - call_started,
                        "error": code.value,
                        "http_status": status_text,
                    }
                )
                raise ModelClientError(
                    TypedError(
                        code=code,
                        message=f"Gemini request failed ({status or type(exc).__name__})",
                        retryable=code == TypedErrorCode.MODEL_UNAVAILABLE,
                    )
                ) from exc
            try:
                parsed = json.loads(response.text or "")
                data = _validate_output(parsed, schema)
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                self.call_records.append(
                    {
                        "purpose": purpose,
                        "model": self.model,
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
            self.call_records.append(
                {
                    "purpose": purpose,
                    "model": getattr(response, "model_version", None) or self.model,
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
