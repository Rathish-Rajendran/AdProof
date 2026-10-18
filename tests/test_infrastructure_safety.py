from __future__ import annotations

import io
import socket

import httpx
import pytest
from PIL import Image

from adproof.domain.models import TypedErrorCode
from adproof.infrastructure.image import ImageFreezeError, freeze_image
from adproof.infrastructure.safe_http import SafeFetchError, SafeHttpClient, validate_public_url
from adproof.infrastructure.snapshot import normalize_source


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), "#305070").save(output, format="PNG")
    return output.getvalue()


def _public_dns(*args, **kwargs):
    return [(None, None, None, None, ("8.8.8.8", 443))]


def test_image_freezing_canonicalizes_png_and_rejects_html():
    frozen = freeze_image(_png())
    assert frozen.width == 32
    assert frozen.height == 24
    assert frozen.source_image_sha256 != frozen.model_input_sha256
    with pytest.raises(ImageFreezeError) as error:
        freeze_image(b"<html>not an image</html>")
    assert error.value.code == TypedErrorCode.INVALID_IMAGE


def test_url_allowlist_and_dns_private_address_checks(monkeypatch):
    with pytest.raises(SafeFetchError):
        validate_public_url("http://127.0.0.1/private")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(SafeFetchError) as error:
        validate_public_url("https://raw.githubusercontent.com/Rathish-Rajendran/AdProof/file.png")
    assert error.value.code == TypedErrorCode.UNSAFE_SOURCE
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    with pytest.raises(SafeFetchError):
        validate_public_url("https://raw.githubusercontent.com/other/repo/file.png")


@pytest.mark.asyncio
async def test_redirect_is_revalidated_before_second_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    requested = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com/landing"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    safe = SafeHttpClient(client=client)
    try:
        with pytest.raises(SafeFetchError) as error:
            await safe.fetch(
                "https://raw.githubusercontent.com/Rathish-Rajendran/AdProof/a.png",
                max_bytes=1024,
            )
        assert error.value.code == TypedErrorCode.UNSAFE_SOURCE
        assert len(requested) == 1
    finally:
        await client.aclose()


def test_raw_github_html_plain_text_is_normalized_as_html():
    snapshot = normalize_source(
        b"<html><nav>hide</nav><p>Regular price $80.</p><script>ignore</script></html>",
        url="https://raw.githubusercontent.com/Rathish-Rajendran/AdProof/sha/page.html",
        content_type="text/plain",
    )
    assert snapshot.text == "Regular price $80."
