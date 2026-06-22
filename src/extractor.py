from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz


@dataclass
class PageText:
    page: int
    text: str


def extract(path: Path, passwords: list[str] | None = None) -> list[PageText]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path, passwords or [])
    if suffix == ".docx":
        return _extract_docx(path)
    raise ValueError(f"Nieobsługiwany format: {suffix}")


def _extract_pdf(path: Path, passwords: list[str]) -> list[PageText]:
    import fitz

    with fitz.open(path) as doc:
        if doc.is_encrypted:
            _unlock(doc, path, passwords)
        return _read_pages(doc)


def _unlock(doc: fitz.Document, path: Path, passwords: list[str]) -> None:
    for pw in passwords:
        if doc.authenticate(pw):
            return
    raise PermissionError(
        f"Nie można otworzyć '{path.name}' — plik jest zaszyfrowany. "
        f"Dodaj hasło do sekcji 'passwords' w config.yaml."
    )


def _read_pages(doc: fitz.Document) -> list[PageText]:
    return [
        PageText(page=i, text=text)
        for i, page in enumerate(doc, start=1)
        if (text := page.get_text().strip())
    ]


def _extract_docx(path: Path) -> list[PageText]:
    from docx import Document

    doc = Document(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return [PageText(page=1, text="\n".join(paragraphs))]
