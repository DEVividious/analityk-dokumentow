"""Trwałość zanonimizowanych dokumentów.

Po anonimizacji zapisujemy DWA pliki w `docs/zanonimizowane/`:

- `<stem>.md`        — zanonimizowana treść (placeholdery). Bezpieczna; to ona trafia
                       do Claude. NIE zawiera żadnych oryginalnych danych.
- `<stem>.map.json`  — słownik `placeholder → oryginał`. Sekret potrzebny lokalnie do
                       de-anonimizacji raportu. NIGDY nie jest wysyłany do chmury.

Rozdział na dwa pliki to celowa decyzja bezpieczeństwa (defense-in-depth): plik
karmiący Claude'a fizycznie nie zawiera oryginałów, więc nawet błąd parsowania nie
może ich ujawnić. Folder jest poza repozytorium (zob. .gitignore).
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .mappings import AnonymizationMappings
from .pipeline import AnonymizationResult

_ANON_DIR = Path(__file__).resolve().parents[2] / "docs" / "zanonimizowane"
_SUFFIX = "__anon__"
_MAP_EXT = ".map.json"
_PLACEHOLDER = re.compile(r"\[([A-ZŻŹĄĆĘŁŃÓŚ]+)_(\d+)\]")


@dataclass(frozen=True)
class AnonymizedDoc:
    path: Path        # ścieżka do pliku .md (treść)
    source: str       # oryginalna nazwa pliku, np. "umowa.pdf"
    created: datetime
    count: int        # liczba zastąpień


def save(source_name: str, result: AnonymizationResult) -> Path:
    """Zapisuje treść (.md) i słownik mapowań (.map.json). Zwraca ścieżkę do .md."""
    _ANON_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stem = f"{Path(source_name).stem}{_SUFFIX}{now:%Y%m%d-%H%M%S}"
    text_path = _ANON_DIR / f"{stem}.md"
    map_path = _ANON_DIR / f"{stem}{_MAP_EXT}"

    reverse = result.mappings.as_reverse_map()

    # Plik treści — TYLKO zanonimizowany tekst + metadane (zero oryginałów).
    text_path.write_text("\n".join([
        "---",
        f"source: {source_name}",
        f"created: {now.isoformat(timespec='seconds')}",
        f"zastapienia: {len(reverse)}",
        "---",
        "",
        result.text,
        "",
    ]), encoding="utf-8")

    # Plik-słownik — oryginały (sekret).
    map_path.write_text(
        json.dumps(reverse, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return text_path


def list_all() -> list[AnonymizedDoc]:
    """Zanonimizowane dokumenty (pliki .md), najnowsze pierwsze."""
    if not _ANON_DIR.exists():
        return []
    docs = [read_meta(p) for p in _ANON_DIR.glob(f"*{_SUFFIX}*.md")]
    return sorted([d for d in docs if d], key=lambda d: d.created, reverse=True)


def load(path: Path) -> tuple[str, AnonymizationMappings]:
    """Wczytuje (zanonimizowany tekst z .md, mapowania z sąsiedniego .map.json).

    Tekst pochodzi WYŁĄCZNIE z .md (bez frontmatter) — to on idzie do Claude.
    Mapowania z osobnego pliku służą tylko lokalnej de-anonimizacji.
    """
    text = _strip_frontmatter(path.read_text(encoding="utf-8")).strip("\n")

    mappings = AnonymizationMappings()
    map_path = path.with_name(path.stem + _MAP_EXT)
    if map_path.exists():
        reverse = json.loads(map_path.read_text(encoding="utf-8"))
        for placeholder, value in reverse.items():
            ph = _PLACEHOLDER.match(placeholder)
            if ph:
                mappings.register(ph.group(1), int(ph.group(2)), value)

    return text, mappings


_PLACEHOLDER_FULL = re.compile(r"\[[A-ZŻŹĄĆĘŁŃÓŚ]+_\d+\]")


def load_combined(paths: list[Path]) -> tuple[str, AnonymizationMappings]:
    """Łączy kilka artefaktów w jeden kontekst z PRZENUMEROWANIEM placeholderów.

    Każdy artefakt ma własną numerację (`[IMIĘ_1]` w różnych plikach = różne osoby),
    więc naiwne sklejenie powodowałoby kolizje. Przenumerowujemy placeholdery do
    jednego, wspólnego słownika z deduplikacją po wartości — dzięki czemu ten sam
    podmiot występujący w kilku dokumentach dostaje ten sam placeholder (spójność
    cross-dokument), a kolizje znikają. Zwraca (sklejony tekst, wspólne mapowania).
    """
    combined = AnonymizationMappings()
    blocks: list[str] = []
    for path in paths:
        text, local = load(path)
        remap = {
            ph: combined.add(m.group(1), value)
            for ph, value in local.as_reverse_map().items()
            if (m := _PLACEHOLDER.match(ph))
        }
        text = _PLACEHOLDER_FULL.sub(lambda mm: remap.get(mm.group(0), mm.group(0)), text)
        meta = read_meta(path)
        name = meta.source if meta else path.name
        blocks.append(f"=== DOKUMENT: {name} ===\n\n{text}")
    return "\n\n".join(blocks), combined


def read_meta(path: Path) -> AnonymizedDoc | None:
    meta: dict[str, str] = {}
    for line in _frontmatter(path.read_text(encoding="utf-8")).splitlines():
        key, sep, val = line.partition(":")
        if sep:
            meta[key.strip()] = val.strip()
    try:
        return AnonymizedDoc(
            path=path,
            source=meta.get("source", path.name),
            created=datetime.fromisoformat(meta["created"]),
            count=int(meta.get("zastapienia", "0")),
        )
    except (KeyError, ValueError):
        return None


def _frontmatter(raw: str) -> str:
    if not raw.startswith("---\n"):
        return ""
    end = raw.find("\n---\n", 4)
    return raw[4:end] if end != -1 else ""


def _strip_frontmatter(raw: str) -> str:
    if not raw.startswith("---\n"):
        return raw
    end = raw.find("\n---\n", 4)
    return raw[end + 5:] if end != -1 else raw
