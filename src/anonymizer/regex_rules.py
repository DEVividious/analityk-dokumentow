import re
from dataclasses import dataclass
from .mappings import AnonymizationMappings


@dataclass(frozen=True)
class _Pattern:
    kind: str
    regex: re.Pattern
    keyed: bool = False  # True: wartość do anonimizacji w grupie 1, nie w całym match


@dataclass
class Candidate:
    kind: str
    value: str
    context: str  # fragment tekstu z okolicą dopasowania


_PATTERNS: list[_Pattern] = [
    # ADE jako pierwszy — żeby nie był fragmentowany przez inne wzorce
    _Pattern("ADE",   re.compile(r"\bAE:[A-Z]{2}-\d{5}-\d{5}-[A-Za-z0-9]+-\d+\b")),
    _Pattern("PESEL", re.compile(r"\b\d{11}\b")),
    # NIP — kontekstowy (wymaga słowa kluczowego), żeby nie łapać KRS/REGON
    _Pattern("NIP",   re.compile(
        r"\bNIP\b\s*:?\s*(\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2})",
        re.IGNORECASE,
    ), keyed=True),
    # REGON — kontekstowy po słowie kluczowym, zachowuje etykietę
    _Pattern("REGON", re.compile(
        r"\bREGON\b\s*:?\s*(\d{9}(?:\d{5})?)",
        re.IGNORECASE,
    ), keyed=True),
    # Numer dowodu osobistego — kontekstowy (zachowuje etykietę) + samodzielny format 3L+6C
    _Pattern("ID", re.compile(
        r"(?:seria\s+i\s+numer\s+(?:dowodu|dokumentu)|numer\s+dowodu|nr\.?\s+dowodu|dowod[uó]?\s+osobist\w*)\s*[:\s]*([A-Z]{3}[ ]?\d{6})",
        re.IGNORECASE,
    ), keyed=True),
    _Pattern("ID", re.compile(r"\b[A-Z]{3}[ ]?\d{6}\b")),
    _Pattern("KONTO", re.compile(r"\bPL\d{26}\b")),
    # NRB — polski numer rachunku (26 cyfr) po słowie kluczowym "rachunek/konto"
    _Pattern("KONTO", re.compile(
        r"(?:numer|nr)[\s.]*rachunku[\s\w]*:\s*(\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4})",
        re.IGNORECASE,
    ), keyed=True),
    # Kod pocztowy — format XX-XXX
    _Pattern("ADRES", re.compile(r"\b\d{2}-\d{3}\b")),
    # TEL: +48 + 9 cyfr LUB 9-cyfrowy numer zaczynający się od 4-9 (polskie mobile/stacjonarne)
    # Nie łapie 0000... (KRS) ani innych sekwencji zaczynających się od 0
    _Pattern("TEL",   re.compile(
        r"\+48[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{3}"
        r"|\b[4-9]\d{2}[\s-]?\d{3}[\s-]?\d{3}\b",
    )),
    _Pattern("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # SWIFT/BIC — kontekstowy, zachowuje słowo kluczowe, zastępuje tylko kod
    _Pattern("SWIFT", re.compile(
        r"(?:kod\s+)?(?:SWIFT\s*\(BIC\)|BIC\s*\(SWIFT\)|SWIFT/BIC|BIC/SWIFT|SWIFT|BIC)"
        r"\s*[\-–—:]\s*"
        r"([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)",
        re.IGNORECASE,
    ), keyed=True),
    # Księga wieczysta: np. GD1G/00123456/7
    _Pattern("KW",    re.compile(r"\b[A-Z]{2}[0-9A-Z]{1,3}/\d{8}/\d\b")),
    # Identyfikatory po słowie kluczowym + dwukropek (dłuższe alternatywy pierwsze)
    _Pattern("ID",    re.compile(
        r"(?:numer\s+wniosku|numer\s+umowy|numer\s+referencyjny|numer\s+ref|numer\s+sprawy|numer\s+klienta"
        r"|wniosek\s+nr|nr\s+wniosku|nr\s+umowy|nr\s+referencyjny|nr\s+ref|nr\s+sprawy|nr\s+klienta"
        r"|identyfikator\s+klienta|identyfikator|numer|nr)"
        r"\s*:\s*([A-Z0-9][A-Z0-9\-/_.]{2,})",
        re.IGNORECASE,
    ), keyed=True),
    # Numer dokumentu po "nr"/"numer" BEZ dwukropka — tylko długie sekwencje cyfr (min. 10)
    _Pattern("ID",    re.compile(r"(?:numer|nr)\s+(\d{10,})", re.IGNORECASE), keyed=True),
]


# Typy zawsze prywatne — podstawiane deterministycznie regexem (brak niejednoznaczności kontekstu)
ALWAYS_PRIVATE = frozenset({"PESEL", "EMAIL", "TEL", "ADRES", "KONTO", "SWIFT", "ADE", "KW", "ID"})
# Typy wymagające weryfikacji kontekstem (prywatna firma vs. instytucja publiczna)
VERIFY_CONTEXT = frozenset({"NIP", "REGON"})

# Instytucje publiczne, znane banki i ubezpieczyciele — ich NIP/REGON NIE są anonimizowane
# (podmioty publicznie identyfikowalne, potrzebne dla kontekstu analizy). Słowo kluczowe
# sprawdzane w linii zawierającej dopasowanie NIP/REGON.
#
# UWAGA: lista zawiera WYŁĄCZNIE nazwy konkretnych podmiotów publicznych/banków/ubezpieczycieli.
# Świadomie NIE ma tu ogólnych terminów prawno-rejestrowych (KRS, Sąd, Rejestr, Urząd Skarbowy),
# bo występują w boilerplate KAŻDEJ prywatnej spółki i powodowałyby pozostawienie jej NIP-u
# (wyciek). Zasada: w razie wątpliwości anonimizuj — pozostawienie tylko dla pewnych podmiotów.
_PUBLIC_INSTITUTION = frozenset({
    # instytucje państwowe o jednoznacznych nazwach
    "zus", "nfz", "nbp", "krus", "pfron",
    # znane banki
    "ing", "pko bp", "pko bank", "santander", "mbank", "pekao", "bnp paribas", "alior",
    "millennium", "citi", "credit agricole", "bos bank", "velobank", "bank śląski",
    # znani ubezpieczyciele
    "pzu", "allianz", "nationale-nederlanden", "warta", "generali", "uniqa",
})


def apply_nip_regon(
    text: str,
    mappings: AnonymizationMappings,
    public_keywords: frozenset[str] = _PUBLIC_INSTITUTION,
) -> str:
    """Deterministycznie anonimizuje NIP/REGON, pomijając instytucje publiczne i znane banki.

    Decyzja per-linia: jeśli linia z dopasowaniem zawiera słowo kluczowe instytucji
    publicznej/banku — numer zostaje; w przeciwnym razie jest podstawiany. Zastępuje
    kontekstową decyzję, którą wcześniej podejmował SLM.
    """
    for p in _PATTERNS:
        if p.kind in VERIFY_CONTEXT:
            text = _sub_with_kind(text, p, mappings, public_keywords)
    return text


def is_public_org(name: str) -> bool:
    """True, jeśli nazwa to znana instytucja publiczna / bank / ubezpieczyciel.

    Używane też przez warstwę GLiNER, by NIE anonimizować nazw takich podmiotów
    (potrzebne dla kontekstu analizy — np. że to kredyt w ING).
    """
    return _has_public_keyword(name.lower(), _PUBLIC_INSTITUTION)


def _has_public_keyword(text_lower: str, keywords: frozenset[str]) -> bool:
    # Dopasowanie po granicy słowa (a nie podłańcuchem), żeby 'ing' nie trafiało
    # w 'consulting'/'leasing' i nie zostawiało przez pomyłkę NIP-u prywatnej firmy.
    return any(
        re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text_lower) for kw in keywords
    )


def _sub_with_kind(
    text: str,
    pattern: "_Pattern",
    mappings: AnonymizationMappings,
    public_keywords: frozenset[str],
) -> str:
    def replacer(m: re.Match) -> str:
        line = _line_of(m.string, m.start(), m.end()).lower()
        if _has_public_keyword(line, public_keywords):
            return m.group()
        placeholder = mappings.add(pattern.kind, m.group(1))
        return m.group().replace(m.group(1), placeholder, 1)

    return pattern.regex.sub(replacer, text)


def _line_of(s: str, start: int, end: int) -> str:
    line_start = s.rfind("\n", 0, start)
    line_start = line_start + 1 if line_start != -1 else 0
    line_end = s.find("\n", end)
    line_end = line_end if line_end != -1 else len(s)
    return s[line_start:line_end]


def find_candidates(text: str) -> list[Candidate]:
    """Zwraca kandydatów do anonimizacji znalezionych przez wyrażenia regularne.

    Nie modyfikuje tekstu — wynik trafia do promptu SLM jako podpowiedź.
    """
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for p in _PATTERNS:
        for m in p.regex.finditer(text):
            value = m.group(1) if p.keyed else m.group()
            if value in seen:
                continue
            seen.add(value)

            # Pobierz linię zawierającą dopasowanie jako kontekst
            line_start = text.rfind("\n", 0, m.start())
            line_start = line_start + 1 if line_start != -1 else 0
            line_end = text.find("\n", m.end())
            line_end = line_end if line_end != -1 else len(text)
            context = text[line_start:line_end].strip()[:120]

            candidates.append(Candidate(kind=p.kind, value=value, context=context))

    return candidates


def apply(
    text: str,
    mappings: AnonymizationMappings,
    kinds: frozenset[str] | None = None,
) -> str:
    """Deterministyczne podstawienie placeholderów regexem.

    Gdy `kinds` podane — przetwarza wyłącznie wzorce tych typów. Używane jako
    siatka bezpieczeństwa po przebiegu SLM (kinds=ALWAYS_PRIVATE): gwarantuje
    podstawienie danych zawsze prywatnych, których model mógł nie wykryć.
    Bez `kinds` przetwarza wszystkie wzorce (zachowane dla testów jednostkowych).
    """
    for p in _PATTERNS:
        if kinds is not None and p.kind not in kinds:
            continue
        if p.keyed:
            text = _replace_keyed(text, p.kind, p.regex, mappings)
        else:
            text = _replace_all(text, p.kind, p.regex, mappings)
    return text


def _replace_all(text: str, kind: str, regex: re.Pattern, mappings: AnonymizationMappings) -> str:
    return regex.sub(lambda m: mappings.add(kind, m.group()), text)


def _replace_keyed(text: str, kind: str, regex: re.Pattern, mappings: AnonymizationMappings) -> str:
    def replacer(m: re.Match) -> str:
        placeholder = mappings.add(kind, m.group(1))
        return m.group().replace(m.group(1), placeholder, 1)
    return regex.sub(replacer, text)
