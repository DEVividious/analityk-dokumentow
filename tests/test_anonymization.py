"""Testy anonimizacji na realnych dokumentach PDF.

Zakres:
- siatka regex (`regex_rules`) — dane zawsze prywatne + NIP/REGON
- pełny pipeline z GLiNER — opcjonalnie (marker `pipeline`, wolne):

    uv run pytest tests/test_anonymization.py -q -m "not pipeline"   # szybkie (regex)
    uv run pytest tests/test_anonymization.py -q -m pipeline          # pełny pipeline
"""
import pytest
from pathlib import Path
from src.extractor import extract
from src.anonymizer.mappings import AnonymizationMappings
from src.anonymizer import regex_rules
from src.anonymizer.deanonymize import deanonymize
from src.config import AnonymizerConfig

_TESTS_DIR = Path(__file__).parent
_PDF_TELECOM = _TESTS_DIR / "contract_template_polish.pdf"
_PDF_WATER = _TESTS_DIR / "contract_template_2_polish.pdf"


# ---------------------------------------------------------------------------
# Fixtures — tekst z PDF-ów (wczytany raz na sesję testową)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def telecom_text() -> str:
    return "\n".join(p.text for p in extract(_PDF_TELECOM))


@pytest.fixture(scope="session")
def water_text() -> str:
    return "\n".join(p.text for p in extract(_PDF_WATER))


@pytest.fixture(scope="session")
def telecom_regex(telecom_text):
    """Tekst po pełnej siatce regex (wszystkie wzorce) + mapowania."""
    m = AnonymizationMappings()
    return regex_rules.apply(telecom_text, m), m


@pytest.fixture(scope="session")
def water_regex(water_text):
    m = AnonymizationMappings()
    return regex_rules.apply(water_text, m), m


# ---------------------------------------------------------------------------
# Siatka regex — umowa telekomunikacyjna
# ---------------------------------------------------------------------------

class TestRegexTelecom:
    def test_pesel_anonymized(self, telecom_regex):
        result, _ = telecom_regex
        assert "12345678912" not in result
        assert "[PESEL_1]" in result

    def test_nip_anonymized(self, telecom_regex):
        result, _ = telecom_regex
        assert "8551588795" not in result
        assert "[NIP_1]" in result

    def test_email_anonymized(self, telecom_regex):
        result, _ = telecom_regex
        assert "nowak@domena.pl" not in result
        assert "[EMAIL_1]" in result

    def test_amounts_preserved(self, telecom_regex):
        result, _ = telecom_regex
        assert "49,90 zł" in result

    def test_date_preserved(self, telecom_regex):
        result, _ = telecom_regex
        assert "02-01-2020" in result

    def test_mappings_contain_pesel(self, telecom_regex):
        _, m = telecom_regex
        reverse = m.as_reverse_map()
        assert reverse.get("[PESEL_1]") == "12345678912"

    def test_mappings_contain_email(self, telecom_regex):
        _, m = telecom_regex
        reverse = m.as_reverse_map()
        assert any("nowak@domena.pl" == v for v in reverse.values())


# ---------------------------------------------------------------------------
# Siatka regex — wniosek wodociągowy
# ---------------------------------------------------------------------------

class TestRegexWater:
    def test_pesel_anonymized(self, water_regex):
        result, _ = water_regex
        assert "12345678901" not in result
        assert "[PESEL_1]" in result

    def test_nip_anonymized(self, water_regex):
        result, _ = water_regex
        assert "6641808503" not in result
        assert "[NIP_1]" in result

    def test_email_wnioskodawcy_anonymized(self, water_regex):
        result, _ = water_regex
        assert "JAN.KOWALSKI@WP.PL" not in result

    def test_email_iod_anonymized(self, water_regex):
        result, _ = water_regex
        assert "iod@pwik.starachowice.pl" not in result

    def test_emails_in_mappings(self, water_regex):
        # PDF zawiera co najmniej 2 prywatne emaile (wnioskodawcy + IOD)
        _, m = water_regex
        email_values = {
            v for k, v in m.as_reverse_map().items() if k.startswith("[EMAIL_")
        }
        assert len(email_values) >= 2

    def test_date_preserved(self, water_regex):
        result, _ = water_regex
        assert "14.10.2020" in result


# ---------------------------------------------------------------------------
# NIP/REGON kontekstowo — stoplista instytucji publicznych/banków
# ---------------------------------------------------------------------------

class TestNipRegonContext:
    def test_private_firm_nip_anonymized(self):
        m = AnonymizationMappings()
        out = regex_rules.apply_nip_regon("Firma XYZ Sp. z o.o., NIP 8551588795.", m)
        assert "8551588795" not in out

    def test_known_bank_nip_preserved(self):
        m = AnonymizationMappings()
        out = regex_rules.apply_nip_regon("ING Bank Śląski S.A., NIP 1234563218.", m)
        assert "1234563218" in out

    def test_word_boundary_not_substring(self):
        # 'ing' w 'Consulting' nie może być traktowane jak bank ING
        m = AnonymizationMappings()
        out = regex_rules.apply_nip_regon("XYZ Consulting Sp. z o.o., NIP 8551588795.", m)
        assert "8551588795" not in out

    def test_is_public_org(self):
        assert regex_rules.is_public_org("ING Bank Śląski S.A.")
        assert not regex_rules.is_public_org("AC Systemy Spółka z o.o.")
        assert not regex_rules.is_public_org("XYZ Consulting")


# ---------------------------------------------------------------------------
# Pełny pipeline z GLiNER — opcjonalny (wolny, ładuje model)
# ---------------------------------------------------------------------------

@pytest.mark.pipeline
class TestFullPipeline:
    def _run(self, text):
        from src.anonymizer.pipeline import anonymize
        return anonymize(text, AnonymizerConfig())

    def test_no_raw_pesel_email(self, telecom_text):
        res = self._run(telecom_text)
        assert "12345678912" not in res.text
        assert "nowak@domena.pl" not in res.text

    def test_names_anonymized(self, telecom_text):
        res = self._run(telecom_text)
        assert "Jan Kowalski" not in res.text
        assert "Jan Nowak" not in res.text

    def test_roundtrip_restores_originals(self, telecom_text):
        res = self._run(telecom_text)
        back = deanonymize(res.text, res.mappings)
        for original in ("12345678912", "nowak@domena.pl", "Jan Kowalski"):
            assert original in back
