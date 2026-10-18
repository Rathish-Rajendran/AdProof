from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    title: str
    url: str
    doc_type: str
    text: str
    sha256: str
    product_id: str | None = None


@dataclass(frozen=True)
class CorpusChunk:
    chunk_id: str
    doc_id: str
    title: str
    heading: str
    url: str
    text: str
    sha256: str


def parse_document(path: Path) -> CorpusDocument:
    content = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(content)
    if not match:
        raise ValueError(f"{path} is missing YAML front matter")
    metadata = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"Invalid front matter in {path}")
        metadata[key.strip()] = value.strip()
    required = ("doc_id", "title", "url", "doc_type")
    if any(not metadata.get(key) for key in required):
        raise ValueError(f"{path} is missing required front matter")
    body = match.group(2).strip()
    return CorpusDocument(
        doc_id=metadata["doc_id"],
        title=metadata["title"],
        url=metadata["url"],
        doc_type=metadata["doc_type"],
        text=body,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        product_id=metadata.get("product_id"),
    )


def _windows(text: str, size: int, overlap: int) -> list[str]:
    sentences = SENTENCE.split(text.strip())
    result: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > size:
            cut = sentence.rfind(" ", 0, size)
            cut = cut if cut > 0 else size
            piece, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if piece:
                result.append(piece)
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > size:
            result.append(current)
            tail = current[-overlap:]
            boundary = tail.find(" ")
            current = f"{tail[boundary + 1 :] if boundary >= 0 else tail} {sentence}".strip()
        else:
            current = candidate
    if current:
        result.append(current)
    return result


def chunk_document(
    document: CorpusDocument, *, chunk_size: int = 800, overlap: int = 120
) -> list[CorpusChunk]:
    sections: list[tuple[str, str]] = []
    cursor = 0
    heading_path: list[tuple[int, str]] = []
    current_heading = document.title
    for match in HEADING.finditer(document.text):
        if match.start() > cursor:
            sections.append((current_heading, document.text[cursor : match.start()].strip()))
        depth = len(match.group(1))
        heading_path = [(level, title) for level, title in heading_path if level < depth]
        heading_path.append((depth, match.group(2)))
        current_heading = " / ".join(title for _, title in heading_path)
        cursor = match.end()
    if cursor < len(document.text):
        sections.append((current_heading, document.text[cursor:].strip()))

    chunks: list[CorpusChunk] = []
    for heading, section in sections:
        prefix = f"{document.title} — {heading}\n"
        for part in _windows(section, max(80, chunk_size - len(prefix)), overlap):
            text = f"{prefix}{part}".strip()
            number = len(chunks) + 1
            chunks.append(
                CorpusChunk(
                    chunk_id=f"{document.doc_id}#{number}",
                    doc_id=document.doc_id,
                    title=document.title,
                    heading=heading,
                    url=document.url,
                    text=text,
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
    return chunks


def load_corpus(directory: Path) -> list[CorpusDocument]:
    return [parse_document(path) for path in sorted(directory.glob("*.md"))]
