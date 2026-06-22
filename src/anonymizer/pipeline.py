from dataclasses import dataclass
from typing import Callable
from src.config import AnonymizerConfig
from . import regex_rules, semantic_ner
from .mappings import AnonymizationMappings

StageCallback = Callable[[str], None]
StageDoneCallback = Callable[[str, int], None]
ProgressCallback = Callable[[int, int], None]


@dataclass
class AnonymizationResult:
    text: str
    mappings: AnonymizationMappings


def anonymize(
    text: str,
    config: AnonymizerConfig,
    on_start: StageCallback | None = None,
    on_done: StageDoneCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> AnonymizationResult:
    mappings = AnonymizationMappings()
    stage_name = "GLiNER (NER semantyczny)"

    if on_start:
        on_start(stage_name)

    count_before = mappings.total_count()

    # Przebieg 1: GLiNER — dane semantyczne (imiona, nazwiska, firmy, ulice, miasta).
    # Spany znakowe → podstawienie deterministyczne, bez parafrazowania.
    finder = semantic_ner.make_layer(
        config.gliner_model, config.gliner_threshold, on_progress=on_progress,
    )
    text = finder(text, mappings)

    # Przebieg 2: deterministyczna siatka regex — dane zawsze prywatne (PESEL, e-mail,
    # telefon, konto, kod pocztowy, dowód itd.). Gwarancja pokrycia.
    text = regex_rules.apply(text, mappings, kinds=regex_rules.ALWAYS_PRIVATE)

    # Przebieg 3: NIP/REGON kontekstowo — anonimizowane poza instytucjami publicznymi
    # i znanymi bankami/ubezpieczycielami (stoplista nazw).
    text = regex_rules.apply_nip_regon(text, mappings)

    if on_done:
        on_done(stage_name, mappings.total_count() - count_before)

    return AnonymizationResult(text=text, mappings=mappings)
