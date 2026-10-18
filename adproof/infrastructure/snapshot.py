from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _VisibleTextParser(HTMLParser):
    hidden_tags = {"script", "style", "nav", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.hidden_tags:
            self.hidden_depth += 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.hidden_tags and self.hidden_depth:
            self.hidden_depth -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


@dataclass(frozen=True)
class NormalizedSnapshot:
    text: str
    content_sha256: str
    snapshot_id: str


def normalize_source(
    content: bytes, *, url: str, content_type: str, max_chars: int = 30_000
) -> NormalizedSnapshot:
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path.lower()
    raw_repo_html = (
        host == "raw.githubusercontent.com"
        and path.startswith("/rathish-rajendran/adproof/")
        and path.endswith((".html", ".htm"))
    )
    is_html = "text/html" in content_type.lower() or raw_repo_html
    decoded = content.decode("utf-8", errors="replace")
    if is_html:
        parser = _VisibleTextParser()
        parser.feed(decoded)
        text = " ".join(" ".join(parser.parts).split())
    else:
        text = " ".join(decoded.split())
    text = text[:max_chars]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return NormalizedSnapshot(
        text=text, content_sha256=digest, snapshot_id=f"snapshot-{digest[:16]}"
    )
