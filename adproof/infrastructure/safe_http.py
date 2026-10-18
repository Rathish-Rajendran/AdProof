from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from adproof.domain.models import TypedErrorCode

MAX_REDIRECTS = 3


class SafeFetchError(RuntimeError):
    def __init__(self, code: TypedErrorCode, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchedSource:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes


def _configured_allowlist(value: str | None) -> dict[str, tuple[str, ...]] | None:
    if not value or not value.strip():
        return None
    allowlist: dict[str, list[str]] = {}
    for entry in value.split(","):
        host, separator, path = entry.strip().partition("=")
        host = host.lower().rstrip(".")
        if not host:
            raise ValueError("ADPROOF_SOURCE_ALLOWLIST entries require a hostname")
        allowlist.setdefault(host, []).append(path or "/" if separator else "/")
    return {host: tuple(paths) for host, paths in allowlist.items()}


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise SafeFetchError(
            TypedErrorCode.UNSAFE_SOURCE, "connected peer address is invalid"
        ) from exc
    return ip.is_global


def _validate_response_peer(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    address = stream.get_extra_info("server_addr") if stream is not None else None
    if isinstance(address, (tuple, list)):
        address = address[0] if address else None
    if not isinstance(address, str) or not _is_public_address(address):
        raise SafeFetchError(
            TypedErrorCode.UNSAFE_SOURCE,
            "connected peer did not resolve to a public address",
        )


def validate_public_url(url: str, allowlist: dict[str, tuple[str, ...]] | None = None) -> str:
    allowlist = (
        _configured_allowlist(os.getenv("ADPROOF_SOURCE_ALLOWLIST"))
        if allowlist is None
        else allowlist
    )
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise SafeFetchError(
            TypedErrorCode.UNSAFE_SOURCE, "only public HTTPS URLs on port 443 are allowed"
        )
    if allowlist is not None:
        prefixes = allowlist.get(host)
        if prefixes is None or not any(parsed.path.startswith(prefix) for prefix in prefixes):
            raise SafeFetchError(
                TypedErrorCode.UNSAFE_SOURCE, "source host or path is not allowlisted"
            )
    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = {
                result[4][0] for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise SafeFetchError(
                TypedErrorCode.UNSAFE_SOURCE, "source host did not resolve safely"
            ) from exc
    else:
        addresses = {str(literal_address)}
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise SafeFetchError(
                TypedErrorCode.UNSAFE_SOURCE, "source resolved to a non-public address"
            )
    return url


class SafeHttpClient:
    def __init__(
        self,
        *,
        allowlist: dict[str, tuple[str, ...]] | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.allowlist = (
            allowlist
            if allowlist is not None
            else _configured_allowlist(os.getenv("ADPROOF_SOURCE_ALLOWLIST"))
        )
        self.timeout = timeout
        self.client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout),
            headers={"Accept-Encoding": "identity", "User-Agent": "AdProof/0.1"},
            trust_env=False,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def fetch(self, url: str, *, max_bytes: int) -> FetchedSource:
        current = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            validate_public_url(current, self.allowlist)
            try:
                async with self.client.stream("GET", current, timeout=self.timeout) as response:
                    _validate_response_peer(response)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        if redirect_count == MAX_REDIRECTS:
                            raise SafeFetchError(TypedErrorCode.UNSAFE_SOURCE, "too many redirects")
                        location = response.headers.get("location")
                        if not location:
                            raise SafeFetchError(
                                TypedErrorCode.SOURCE_UNAVAILABLE, "redirect has no location"
                            )
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    encoding = response.headers.get("content-encoding", "identity").lower()
                    if encoding not in ("", "identity"):
                        raise SafeFetchError(
                            TypedErrorCode.SOURCE_TOO_LARGE, "compressed responses are unsupported"
                        )
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        raise SafeFetchError(
                            TypedErrorCode.SOURCE_TOO_LARGE, "source exceeds byte limit"
                        )
                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > max_bytes:
                            raise SafeFetchError(
                                TypedErrorCode.SOURCE_TOO_LARGE, "source exceeds byte limit"
                            )
                        chunks.append(chunk)
                    return FetchedSource(
                        url=str(response.url),
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        content=b"".join(chunks),
                    )
            except SafeFetchError:
                raise
            except (TimeoutError, httpx.HTTPError, OSError) as exc:
                raise SafeFetchError(
                    TypedErrorCode.SOURCE_UNAVAILABLE, "source could not be fetched"
                ) from exc
        raise SafeFetchError(TypedErrorCode.UNSAFE_SOURCE, "too many redirects")
