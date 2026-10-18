from datetime import UTC, datetime, timedelta

import pytest

from adproof.inspector.inspector import ImageInspector
from adproof.model_client import ModelResponse


class RecordingModel:
    model = "recording-model"

    def __init__(self):
        self.prompt_parts = []

    async def generate_json(self, prompt_parts, schema, *, deadline, purpose):
        self.prompt_parts = prompt_parts
        return ModelResponse(
            data=schema.model_validate({"readable": True}),
            model_version=self.model,
            usage={},
            latency=0.0,
        )


@pytest.mark.asyncio
async def test_inspector_passes_image_and_text_as_distinct_prompt_parts():
    model = RecordingModel()
    image = b"frozen image bytes"

    await ImageInspector(model).inspect(
        candidate_id="candidate",
        image_sha256="image-hash",
        image_bytes=image,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )

    assert model.prompt_parts[0] == (image, "image/png")
    assert isinstance(model.prompt_parts[1], str)
