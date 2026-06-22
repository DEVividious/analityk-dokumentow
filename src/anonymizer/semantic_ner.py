"""Finder semantyczny oparty na GLiNER — wykrywanie encji + deterministyczne podstawienie.

Wykrywa dane semantyczne (imiona, nazwiska, nazwy prywatnych firm, ulice, miejscowości),
których nie widzi regex. GLiNER zwraca SPANY znakowe, więc podstawienie jest
deterministyczne (po offsetach) — bez parafrazowania i bez problemu z dopasowaniem
mapowań. Model (~0.3B) działa na CPU, nie zajmuje VRAM.
"""
import contextlib
import functools
import os
import re
import warnings
from typing import Callable, TYPE_CHECKING

from .mappings import AnonymizationMappings
from .regex_rules import is_public_org

if TYPE_CHECKING:
    from gliner import GLiNER

# Etykiety zero-shot przekazywane do GLiNER (po polsku — backbone mDeBERTa zna polski)
_LABELS = ["imię i nazwisko", "osoba", "nazwa firmy", "ulica", "miejscowość"]

# Mapowanie etykiety GLiNER → typ placeholdera. "PERSON" rozbijany na IMIĘ+NAZWISKO.
_LABEL_TO_KIND: dict[str, str] = {
    "imię i nazwisko": "PERSON",
    "osoba": "PERSON",
    "nazwa firmy": "FIRMA",
    "ulica": "ULICA",
    "miejscowość": "MIASTO",
}

# Role/funkcje stron umowy — GLiNER taguje je jako "osoba", ale to nie dane osobowe
_ROLE_STOPLIST = frozenset({
    "abonent", "abonenta", "abonentowi", "abonentem", "abonenci",
    "dostawca", "dostawcy", "dostawcą", "dostawca usług", "dostawcą usług",
    "użytkownik", "użytkownika", "użytkownik końcowy", "użytkownika końcowego",
    "strona", "strony", "stroną", "klient", "klienta", "konsument", "konsumenta",
    "kupujący", "sprzedający", "najemca", "wynajmujący", "zamawiający", "wykonawca",
    "zleceniodawca", "zleceniobiorca", "wnioskodawca", "wnioskodawcy",
    "pełnomocnik", "pełnomocnika", "powód", "pozwany", "świadek", "operator",
})

# GLiNER ucina wejście do max_len=384 tokenów — po cichu gubiąc encje z ogona (gęste
# dokumenty: tabele/liczby mają więcej tokenów na znak, więc chunkowanie po ZNAKACH
# bywało zawodne). Tniemy po LICZBIE TOKENÓW: proxy regexowy liczy tokeny ≥ tokenizera
# GLiNER (zweryfikowane), więc limit jest gwarantowany, z marginesem do 384.
_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
_MAX_TOKENS = 320

ProgressCallback = Callable[[int, int], None]  # (przetworzone_chunki, wszystkie_chunki)


@contextlib.contextmanager
def _silence_native_stderr():
    """Tłumi komunikaty pisane wprost na fd 2 przez kod natywny.

    onnxruntime (zależność GLiNER) przy `import` próbuje wykryć GPU i loguje
    ostrzeżenia `device_discovery` na stderr — zanim Python może ustawić poziom
    logowania. Wyciszamy je tylko na czas importu.
    """
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


@functools.lru_cache(maxsize=2)
def _load_model(model_name: str) -> "GLiNER":
    # Leniwy import: startu aplikacji nie obciąża ciężki stos GLiNER/onnxruntime/torch.
    # Wyciszamy: ostrzeżenia onnxruntime (native stderr), paski postępu i deprecation
    # warningi huggingface_hub. Pobieranie modelu przy 1. uruchomieniu jest więc ciche —
    # informuje o nim komunikat spinnera w UI.
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    with _silence_native_stderr(), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from gliner import GLiNER
        return GLiNER.from_pretrained(model_name)


def make_layer(
    model_name: str,
    threshold: float = 0.5,
    on_progress: ProgressCallback | None = None,
) -> Callable[[str, AnonymizationMappings], str]:
    def layer(text: str, mappings: AnonymizationMappings) -> str:
        model = _load_model(model_name)
        chunks = _split_chunks(text)
        parts = []
        # Wyciszenie komunikatów inferencji (HF unauthenticated, ewentualne UserWarning).
        # Postęp idzie na stdout (fd 1), więc spinner nadal działa.
        with _silence_native_stderr(), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for i, chunk in enumerate(chunks):
                entities = model.predict_entities(chunk, _LABELS, threshold=threshold)
                kept = _dedupe_overlaps([e for e in entities if _keep(e)])
                parts.append(_substitute(chunk, kept, mappings))
                if on_progress:
                    on_progress(i + 1, len(chunks))
        return "".join(parts)

    return layer


def _split_chunks(text: str, max_tokens: int = _MAX_TOKENS) -> list[str]:
    """Dzieli tekst tak, by każdy kawałek miał ≤ max_tokens tokenów (gwarancja braku
    ucięcia przez GLiNER). Podział na granicach linii; pojedynczą zbyt długą linię tnie
    po tokenach. Połączenie kawałków odtwarza oryginalny tekst (po podstawieniach)."""
    out: list[str] = []
    cur: list[str] = []
    cur_tok = 0
    for line in text.splitlines(keepends=True):
        n = len(_TOKEN_RE.findall(line))
        if n > max_tokens:
            if cur:
                out.append("".join(cur))
                cur, cur_tok = [], 0
            out.extend(_split_long_line(line, max_tokens))
        elif cur and cur_tok + n > max_tokens:
            out.append("".join(cur))
            cur, cur_tok = [line], n
        else:
            cur.append(line)
            cur_tok += n
    if cur:
        out.append("".join(cur))
    return out


def _split_long_line(line: str, max_tokens: int) -> list[str]:
    """Tnie pojedynczą linię na granicach tokenów, zachowując dokładnie wszystkie znaki."""
    toks = list(_TOKEN_RE.finditer(line))
    if len(toks) <= max_tokens:
        return [line]
    out: list[str] = []
    prev = 0
    for j in range(max_tokens, len(toks), max_tokens):
        cut = toks[j].start()
        out.append(line[prev:cut])
        prev = cut
    out.append(line[prev:])
    return out


def _keep(entity: dict) -> bool:
    if entity["label"] not in _LABEL_TO_KIND:
        return False
    value = entity["text"].strip().lower()
    if not value:
        return False
    # Odfiltruj role stron (Abonent, Dostawca itd.) tagowane jako osoba
    if value in _ROLE_STOPLIST or any(value.startswith(s + " ") for s in _ROLE_STOPLIST):
        return False
    # Nazwy znanych banków/instytucji/ubezpieczycieli NIE są anonimizowane (kontekst analizy)
    if _LABEL_TO_KIND[entity["label"]] == "FIRMA" and is_public_org(entity["text"]):
        return False
    return True


def _dedupe_overlaps(entities: list[dict]) -> list[dict]:
    """Usuwa nakładające się spany — preferuje dłuższe, potem pewniejsze.

    Dzięki temu 'AC Systemy Spółka z o.o.' wygrywa z krótszym 'AC Systemy'.
    """
    chosen: list[dict] = []
    for e in sorted(entities, key=lambda x: (-(x["end"] - x["start"]), -x["score"])):
        if not any(e["start"] < c["end"] and c["start"] < e["end"] for c in chosen):
            chosen.append(e)
    return chosen


def _substitute(chunk: str, entities: list[dict], mappings: AnonymizationMappings) -> str:
    """Podstawia spany od końca (malejące offsety), żeby pozycje pozostały ważne."""
    for e in sorted(entities, key=lambda x: x["start"], reverse=True):
        kind = _LABEL_TO_KIND[e["label"]]
        value = chunk[e["start"]:e["end"]]
        chunk = chunk[:e["start"]] + _placeholder(kind, value, mappings) + chunk[e["end"]:]
    return chunk


def _placeholder(kind: str, value: str, mappings: AnonymizationMappings) -> str:
    if kind != "PERSON":
        return mappings.add(kind, value)
    tokens = value.split()
    if len(tokens) == 1:
        return mappings.add("IMIĘ", tokens[0])
    first = mappings.add("IMIĘ", tokens[0])
    last = mappings.add("NAZWISKO", " ".join(tokens[1:]))
    return f"{first} {last}"
