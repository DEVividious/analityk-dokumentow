import os
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class AnonymizerConfig:
    gliner_model: str = "urchade/gliner_multi-v2.1"
    gliner_threshold: float = 0.5


@dataclass
class ClaudeConfig:
    model: str
    api_key: str | None = None


@dataclass
class AppConfig:
    anonymizer: AnonymizerConfig
    claude: ClaudeConfig
    passwords: list[str] = field(default_factory=list)


def load(config_path: Path = Path("config.yaml")) -> AppConfig:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return AppConfig(
        anonymizer=_load_anonymizer(data),
        claude=_load_claude(data),
        passwords=data.get("passwords", []),
    )


def _load_anonymizer(data: dict) -> AnonymizerConfig:
    anon = data.get("anonymizer", {})
    return AnonymizerConfig(
        gliner_model=os.environ.get("GLINER_MODEL", anon.get("gliner_model", "urchade/gliner_multi-v2.1")),
        gliner_threshold=float(anon.get("gliner_threshold", 0.5)),
    )


def _load_claude(data: dict) -> ClaudeConfig:
    claude = data.get("claude", {})
    # Klucz: env ANTHROPIC_API_KEY (w tym z .env) ma pierwszeństwo, potem config.
    # Gdy None — SDK i tak czyta ANTHROPIC_API_KEY ze środowiska.
    api_key = os.environ.get("ANTHROPIC_API_KEY") or claude.get("api_key") or None
    return ClaudeConfig(
        model=os.environ.get("CLAUDE_MODEL", claude.get("model", "claude-sonnet-4-6")),
        api_key=api_key,
    )
