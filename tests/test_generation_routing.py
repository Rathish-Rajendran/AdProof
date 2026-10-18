from adproof.infrastructure.settings import Settings
from adproof.model_client import OllamaClient, RoutingModelClient


def test_ad_generation_uses_its_job_specific_model_spec():
    settings = Settings(
        model_default="gemini:gemini-3.5-flash",
        model_ad_generation="ollama:qwen2.5:3b",
    )
    client = RoutingModelClient(settings)._client_for("ad_generation")
    assert isinstance(client, OllamaClient)
    assert client.model == "qwen2.5:3b"
