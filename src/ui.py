"""Interaktywny TUI dla Analityka Dokumentów."""
import asyncio
import re
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator
from rich.console import Console
from rich.panel import Panel

from src import report
from src.agents.pipeline import DocumentAnalysisPipeline
from src.anonymizer import store
from src.anonymizer.deanonymize import deanonymize
from src.anonymizer.pipeline import AnonymizationResult, anonymize
from src.config import AnonymizerConfig, load as load_config
from src.extractor import extract

load_dotenv()

console = Console()

_SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
_QMARK = "▸"   # znak podczas pytania
_AMARK = "✓"   # znak po udzieleniu odpowiedzi (zamiast domyślnego „?”)
_STAGE_HINT = "osoby, firmy, adresy + siatka regex"


def run() -> None:
    _run()


def _run() -> None:
    console.print()
    console.print(Panel.fit("[bold]Analityk Dokumentów[/bold]", style="bold blue"))
    console.print()

    config = load_config()

    action = inquirer.select(
        message="Co chcesz zrobić?",
        choices=[
            Choice(value="anon", name="Anonimizuj dokument(y)"),
            Choice(value="analyze", name="Analizuj zanonimizowany dokument  →  Claude"),
        ],
        mandatory=False,
        qmark=_QMARK, amark=_AMARK,
    ).execute()

    if action == "anon":
        _anonymize_flow(config)
    elif action == "analyze":
        _analyze_flow(config)


# ---------------------------------------------------------------------------
# Tryb 1 — anonimizacja (lokalnie; zapis artefaktu do docs/zanonimizowane/)
# ---------------------------------------------------------------------------

def _anonymize_flow(config) -> None:
    path = _pick_file()
    if not path:
        return

    files = _collect_files(path)
    if not files:
        console.print("[bold red]Nie znaleziono plików PDF ani DOCX.[/bold red]")
        return

    if path.is_dir() and len(files) > 1:
        selected = inquirer.checkbox(
            message=f"Znaleziono {len(files)} {_pl_plik(len(files))}. Odznacz niepotrzebne:",
            choices=[Choice(value=f, name=f.name, enabled=True) for f in files],
            enabled_symbol="[x]",
            disabled_symbol="[ ]",
            instruction="(spacja = zaznacz/odznacz  ·  enter = zatwierdź  ·  esc = anuluj)",
            mandatory=False,
            qmark=_QMARK, amark=_AMARK,
        ).execute()
        if selected is None:
            return
        files = selected or files

    # 1. Anonimizacja wszystkich plików (jeszcze bez zapisu).
    anonymized = []
    for file in files:
        res = _anonymize_one(file, config)
        if res:
            anonymized.append(res)

    if not anonymized:
        return

    # 2. Cross-dokumentowy skan bezpieczeństwa — może domknąć wartości przeoczone w
    #    jednym dokumencie, a wykryte w innym. Mutuje teksty/mapy przed zapisem.
    console.print("\n[bold]Skan bezpieczeństwa (cross-dokumentowy)[/bold]")
    _verify_no_leaks_cross(anonymized)

    # 3. Zapis artefaktów (już po ewentualnym domknięciu).
    created = []
    for file, anon in anonymized:
        out = store.save(file.name, anon)
        total = anon.mappings.total_count()
        console.print(
            f"  [green]✓[/green] Zapisano artefakt: [bold]{out.name}[/bold] "
            f"[dim]({total} {_pl_zastąpień(total)} · {out.parent})[/dim]"
        )
        meta = store.read_meta(out)
        if meta:
            created.append(meta)

    if not created:
        return

    # 4. Nie wychodzimy od razu — pytamy, czy przeanalizować świeże artefakty.
    go = inquirer.confirm(
        message=f"Przeanalizować zanonimizowane dokumenty ({len(created)}) przez Claude teraz?",
        default=True,
        mandatory=False,
        qmark=_QMARK, amark=_AMARK,
    ).execute()
    if go:
        _analyze_docs(created, config)


def _anonymize_one(file: Path, config):
    """Anonimizuje jeden plik (BEZ zapisu). Zwraca (file, AnonymizationResult) lub None.

    Zapis następuje dopiero po cross-dokumentowym skanie bezpieczeństwa w _anonymize_flow.
    """
    console.print()
    console.print(Panel(f"[bold]{file.name}[/bold]", style="bold blue"))

    try:
        pages = _extract_with_password_prompt(file, config.passwords)
    except PermissionError as e:
        console.print(f"[bold red]{e}[/bold red]")
        return None

    full_text = "\n".join(p.text for p in pages)
    anon = _anonymize_with_progress(full_text, config.anonymizer)
    return file, anon


# ---------------------------------------------------------------------------
# Tryb 2 — analiza zanonimizowanego dokumentu przez Claude
# ---------------------------------------------------------------------------

def _analyze_flow(config) -> None:
    docs = store.list_all()
    if not docs:
        console.print(
            "[yellow]Brak zanonimizowanych dokumentów.[/yellow] "
            "Najpierw użyj trybu „Anonimizuj dokument(y)”."
        )
        return

    result = inquirer.checkbox(
        message="Zaznacz dokument(y) do analizy:",
        choices=[Choice(value=d, name=_doc_label(d), enabled=False) for d in docs],
        enabled_symbol="[x]",
        disabled_symbol="[ ]",
        instruction="(spacja = zaznacz  ·  ctrl+a = wszystkie  ·  enter = zatwierdź  ·  esc = anuluj)",
        mandatory=False,
        qmark=_QMARK, amark=_AMARK,
    ).execute()
    if not result:
        return

    # InquirerPy zwraca wartość Choice jako dict pól dataclassy ({'path':…, 'source':…}),
    # więc dopasowujemy z powrotem po unikalnej ścieżce (lub labelu / obiekcie).
    by_path = {str(d.path): d for d in docs}
    by_label = {_doc_label(d): d for d in docs}
    selected: list = []
    for item in result:
        if isinstance(item, dict):
            d = by_path.get(str(item.get("path"))) or by_label.get(item.get("name"))
        elif item in docs:
            d = item
        else:
            d = by_label.get(item) if isinstance(item, str) else None
        if d:
            selected.append(d)

    if not selected:
        console.print(
            "[red]Nie rozpoznano zaznaczenia — nic nie wybrano do analizy.[/red] "
            f"[dim](otrzymano: {[type(x).__name__ for x in result]})[/dim]"
        )
        return

    _analyze_docs(selected, config)


def _analyze_docs(selected: list, config) -> None:
    """Analiza wybranych artefaktów: wczytanie → potwierdzenie → Claude → raport.

    Wspólna dla trybu „Analizuj” oraz dla pytania po anonimizacji.
    """
    if len(selected) == 1:
        doc = selected[0]
        text, mappings = store.load(doc.path)
        report_base = doc.path.with_name(Path(doc.source).stem)
        label = doc.source
    else:
        text, mappings = store.load_combined([d.path for d in selected])
        report_base = selected[0].path.with_name(f"zestaw_{datetime.now():%Y%m%d-%H%M%S}")
        label = f"zestaw {len(selected)} dokumentów ({', '.join(d.source for d in selected)})"

    console.print(
        f"\n  Do analizy: [bold]{label}[/bold] "
        f"[dim]({mappings.total_count()} zastąpień łącznie)[/dim]"
    )

    # Wysyłka do chmury ZAWSZE wymaga ręcznego potwierdzenia.
    confirmed = inquirer.confirm(
        message="Wysłać zanonimizowaną treść do Claude?",
        default=False,
        mandatory=True,
        qmark=_QMARK, amark=_AMARK,
    ).execute()
    if not confirmed:
        console.print("  [yellow]Anulowano — nic nie wysłano.[/yellow]")
        return

    report_md = _analyze_with_progress(text, config.claude)
    report_md = deanonymize(report_md, mappings)

    out = report.save(report_base, report_md)
    console.print(f"\n  [green]✓[/green] Raport: [bold]{out}[/bold]")


# ---------------------------------------------------------------------------
# Wspólne
# ---------------------------------------------------------------------------

def _pick_file() -> Path | None:
    current = Path.home()

    while True:
        try:
            entries = sorted(current.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        except PermissionError:
            console.print("  [red]Brak dostępu do katalogu.[/red]")
            if current.parent != current:
                current = current.parent
            else:
                return None
            continue

        dirs = [e for e in entries if e.is_dir() and not e.name.startswith(".")]
        files = [e for e in entries if e.is_file() and e.suffix.lower() in _SUPPORTED_EXTENSIONS]

        if not dirs and not files:
            if current.parent == current:
                return None
            current = current.parent
            continue

        choices: list = []
        if current.parent != current:
            choices.append(Choice(value="__UP__", name="⬆   .."))
        for d in dirs:
            choices.append(Choice(value=d, name=f"📁  {d.name}/"))
        for f in files:
            choices.append(Choice(value=f, name=f"📄  {f.name}"))
        if files:
            n = len(files)
            choices.append(Separator())
            choices.append(Choice(value=current, name=f"📂  Przetwórz cały folder  ({n} {_pl_plik(n)})"))

        selected = inquirer.select(
            message=str(current),
            choices=choices,
            instruction="(↑↓ = nawigacja  ·  enter = wybierz  ·  esc = wyżej)",
            mandatory=False,
            qmark=_QMARK, amark=_AMARK,
        ).execute()

        if selected is None:  # ESC = go up
            if current.parent != current:
                current = current.parent
            else:
                return None
            continue

        if selected == "__UP__":
            if current.parent != current:
                current = current.parent
            continue

        if isinstance(selected, Path) and selected.is_dir() and selected != current:
            current = selected
            continue

        return selected


def _extract_with_password_prompt(file: Path, config_passwords: list[str]):
    try:
        return extract(file, config_passwords)
    except PermissionError:
        console.print("  [yellow]Plik zaszyfrowany — hasło nie jest w konfiguracji.[/yellow]")
        while True:
            password = inquirer.secret(
                message=f"Hasło do {file.name}:",
                mandatory=False,
                qmark=_QMARK, amark=_AMARK,
            ).execute()
            if not password:
                raise PermissionError(f"Nie podano hasła dla '{file.name}'.")
            try:
                return extract(file, [password])
            except PermissionError:
                console.print("  [bold red]Nieprawidłowe hasło.[/bold red] Spróbuj ponownie.")


def _anonymize_with_progress(text: str, config: AnonymizerConfig) -> AnonymizationResult:
    def on_start(name: str) -> None:
        status.update(f"  [bold]{name}[/bold] [dim]({_STAGE_HINT})[/dim]")

    def on_done(name: str, count: int) -> None:
        console.print(
            f"  [green]✓[/green] [bold]{name}[/bold] "
            f"[dim]({_STAGE_HINT})[/dim] — {count} {_pl_zastąpień(count)}"
        )

    def on_progress(done: int, total: int) -> None:
        status.update(
            f"  [bold]GLiNER (NER semantyczny)[/bold] "
            f"[dim](fragment {done}/{total})[/dim]"
        )

    with console.status(
        "  Ładowanie modelu GLiNER… [dim](pierwsze uruchomienie pobiera ~2.2 GB)[/dim]",
        spinner="dots",
    ) as status:
        return anonymize(
            text, config,
            on_start=on_start,
            on_done=on_done,
            on_progress=on_progress,
        )


def _verify_no_leaks_cross(anonymized: list) -> None:
    """Cross-dokumentowy skan bezpieczeństwa.

    Wartość bywa wykryta w jednym dokumencie, a przeoczona w innym (inny układ/forma).
    Budujemy wspólny zbiór oryginałów (value→kind) ze WSZYSTKICH dokumentów partii i
    skanujemy każdy z nich (case-insensitive, po granicy słowa). Każdą resztkę pokazujemy
    operatorowi z kontekstem i pytamy y/n; „tak” podstawia placeholder w tym dokumencie
    (rejestrując go w mapie tego dokumentu, jeśli go tam nie było — de-anon nadal działa).

    `anonymized`: lista (Path, AnonymizationResult).
    """
    # Wspólny słownik oryginał → typ placeholdera (ze wszystkich map w partii).
    global_values: dict[str, str] = {}
    for _file, anon in anonymized:
        for placeholder, value in anon.mappings.as_reverse_map().items():
            v = value.strip()
            if len(v) >= 3:
                global_values.setdefault(v, _placeholder_kind(placeholder))
    # dłuższe wartości najpierw — żeby „AC Systemy” zeszło przed „AC”
    values_sorted = sorted(global_values, key=len, reverse=True)

    # 1. Zbierz UNIKALNE wartości wciąż obecne (z listą dokumentów + kontekstem).
    #    Każda wartość = jedna decyzja, niezależnie od liczby wystąpień/dokumentów.
    leftovers: dict[str, tuple] = {}
    for value in values_sorted:
        hits = [(file, anon) for file, anon in anonymized if _word_present(value, anon.text)]
        if hits:
            leftovers[value] = (global_values[value], hits, _snippet(hits[0][1].text, value))

    if not leftovers:
        console.print(
            "  [green]✓[/green] [dim]Skan cross-dokumentowy: brak oryginałów w żadnym dokumencie.[/dim]"
        )
        return

    # 2. Najpierw liczba UNIKALNYCH wartości do zatwierdzenia.
    n = len(leftovers)
    console.print(
        f"  [yellow]⚠ Do ręcznego zatwierdzenia: {n} {_pl_wartość(n)}[/yellow] "
        f"[dim](oryginały wciąż w tekście)[/dim]"
    )

    # 3. Jedno pytanie na wartość; „tak” anonimizuje ją we WSZYSTKICH dokumentach.
    for i, (value, (kind, hits, snip)) in enumerate(leftovers.items(), 1):
        files = ", ".join(sorted({file.name for file, _ in hits}))
        console.print(
            f"  [{i}/{n}] [bold red]{value}[/bold red] [dim]({kind})[/dim] "
            f"[dim]— w {len(hits)} dok.: {files}[/dim]\n"
            f"    [dim]…{snip}…[/dim]"
        )
        if inquirer.confirm(
            message=f"Zanonimizować „{value}” we wszystkich dokumentach?",
            default=True,
            mandatory=False,
            qmark=_QMARK, amark=_AMARK,
        ).execute():
            for _file, anon in hits:
                placeholder = anon.mappings.add(kind, value)
                anon.text = _word_sub(value, placeholder, anon.text)


def _placeholder_kind(placeholder: str) -> str:
    m = re.match(r"\[([A-ZŻŹĄĆĘŁŃÓŚ]+)_\d+\]", placeholder)
    return m.group(1) if m else "ID"


def _word_present(value: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.IGNORECASE) is not None


def _word_sub(value: str, placeholder: str, text: str) -> str:
    return re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", placeholder, text, flags=re.IGNORECASE)


def _snippet(text: str, value: str, width: int = 45) -> str:
    m = re.search(re.escape(value), text, re.IGNORECASE)
    if not m:
        return ""
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    return text[start:end].replace("\n", " ").strip()


def _analyze_with_progress(text: str, claude) -> str:
    # api_key=None → SDK i tak odczyta ANTHROPIC_API_KEY ze środowiska/.env
    client = anthropic.AsyncAnthropic(api_key=claude.api_key)
    pipeline = DocumentAnalysisPipeline(client, claude.model)
    with console.status("  Analiza Claude (orkiestrator + workery)…", spinner="dots"):
        return asyncio.run(pipeline.run(text))


def _doc_label(doc: store.AnonymizedDoc) -> str:
    when = doc.created.strftime("%Y-%m-%d %H:%M")
    return f"{doc.source}   ·   {when}   ·   {doc.count} {_pl_zastąpień(doc.count)}"


def _collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    # Tylko pliki z tego poziomu — dokładnie te, które liczy widok „Przetwórz cały folder”.
    # Bez zagnieżdżonych podfolderów i case-insensitive (jak w _pick_file).
    return sorted(
        (f for f in path.iterdir()
         if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTENSIONS),
        key=lambda f: f.name.lower(),
    )


def _pl_plik(n: int) -> str:
    if n == 1:
        return "plik"
    if 2 <= n <= 4:
        return "pliki"
    return "plików"


def _pl_zastąpień(n: int) -> str:
    if n == 1:
        return "zastąpienie"
    if 2 <= n <= 4:
        return "zastąpienia"
    return "zastąpień"


def _pl_wartość(n: int) -> str:
    return "wartość" if n == 1 else "wartości"
