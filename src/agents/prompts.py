ORCHESTRATOR_PROMPT = """\
Jesteś analitykiem dokumentów prawnych i finansowych.

Przeanalizuj poniższy zanonimizowany dokument (dane osobowe zastąpiono placeholderami, \
np. [IMIĘ_1], [PESEL_1], [ADRES_1]). Zaplanuj analizę dla 3 sekcji raportu.

Dokument zawiera placeholdery anonimizacji ([IMIĘ_1], [NAZWISKO_1], [PESEL_1] itd.). \
W opisach zadań używaj tych placeholderów wprost — nie pisz "dane zanonimizowane" ani "osoba oznaczona numerem".

Odpowiedz WYŁĄCZNIE w formacie XML bez żadnego dodatkowego tekstu:

<analysis>Typ dokumentu i 1-2 zdania charakterystyki — czego dotyczy, główny przedmiot umowy</analysis>
<tasks>
  <task>
    <type>streszczenie</type>
    <description>Co streścić i jakie kluczowe wartości (kwoty, terminy, stopy, daty) wyeksponować — \
pełne podsumowanie bez osobnej tabeli</description>
  </task>
  <task>
    <type>zagrozenia_i_pytania</type>
    <description>Które klauzule są ryzykowne lub niejasne, i przy których z nich warto zadać konkretne pytanie \
drugiej stronie — tylko pytania dotyczące specyfiki tej umowy, nie ogólnej wiedzy</description>
  </task>
  <task>
    <type>slownik</type>
    <description>Które pojęcia branżowe, prawne lub finansowe z tego dokumentu laik może nie znać \
i warto je doczytać</description>
  </task>
</tasks>

Dokument:
{document}
"""

WORKER_PROMPT = """\
Jesteś ekspertem od analizy dokumentów prawnych i finansowych.
Kontekst dokumentu: {analysis}

Twoje zadanie: {task_description}

WAŻNE — zasady dotyczące danych osobowych:
Dokument zawiera placeholdery anonimizacji (np. [IMIĘ_1], [NAZWISKO_1], [PESEL_1], [ADRES_1], \
[FIRMA_1], [KW_1], [ID_1] itd.). Używaj tych dokładnych placeholderów w swojej odpowiedzi \
wszędzie tam, gdzie odnosisz się do zanonimizowanych danych. \
NIE pisz ogólnikowo "dane zanonimizowane", "osoba oznaczona numerem" ani podobnych opisów — \
zamiast tego wstaw konkretny placeholder, np. [IMIĘ_1] [NAZWISKO_1] lub [PESEL_1].

Odpowiedz WYŁĄCZNIE treścią sekcji w formacie Markdown — bez tytułu sekcji, bez wstępu.
{format_hint}

Dokument (zanonimizowany):
{document}
"""

SECTION_ORDER = [
    "streszczenie",
    "zagrozenia_i_pytania",
    "slownik",
]

SECTION_TITLES = {
    "streszczenie":        "## 1. Streszczenie",
    "zagrozenia_i_pytania": "## 2. Zagrożenia i pytania do drugiej strony",
    "slownik":             "## 3. Pojęcia warte doczytania",
}

FORMAT_HINTS = {
    "streszczenie": (
        "Napisz zwięzłe streszczenie — od razu do rzeczy, bez zbędnych wstępów. "
        "Uwzględnij: strony umowy, główny przedmiot, wszystkie istotne wartości liczbowe "
        "(kwoty, terminy, daty, stopy procentowe, okresy, kary). "
        "Użyj listy punktorów lub krótkich akapitów tematycznych."
    ),
    "zagrozenia_i_pytania": (
        "Odpowiedz WYŁĄCZNIE tabelą Markdown:\n"
        "| Zagrożenie | Pytanie do drugiej strony |\n"
        "|------------|---------------------------|\n\n"
        "Zasady:\n"
        "- Każdy wiersz to jedno konkretne ryzyko lub niejasna klauzula z tego dokumentu.\n"
        "- Kolumna 'Pytanie' — wpisz pytanie TYLKO jeśli dotyczy specyfiki tej konkretnej umowy "
        "(nieoczywistej klauzuli, niestandardowego warunku, braku istotnej informacji). "
        "Pomiń pytanie (zostaw puste lub wpisz '—') gdy odpowiedź to powszechna wiedza "
        "lub gdy pytanie byłoby trywialne. "
        "NIE pytaj o ogólne mechanizmy finansowe (np. jak działa WIBOR), "
        "NIE pytaj 'czy można negocjować cenę' bez konkretnego powodu."
    ),
    "slownik": (
        "Lista pojęć w formacie: `- **Pojęcie:** wyjaśnienie w prostym języku (1-2 zdania)`.\n"
        "Uwzględnij tylko terminy branżowe, prawne lub finansowe specyficzne dla tego dokumentu, "
        "których znaczenie w tym kontekście laik może nie znać. "
        "Pomijaj słowa powszechnie znane."
    ),
}
