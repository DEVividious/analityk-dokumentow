class AnonymizationMappings:
    """Stores placeholder→original mappings and per-type counters."""

    def __init__(self) -> None:
        self._data: dict[str, dict[int, str]] = {}

    def add(self, kind: str, value: str) -> str:
        existing = self._find(kind, value)
        if existing:
            return existing
        idx = self._next_index(kind)
        self._data.setdefault(kind, {})[idx] = value
        return _placeholder(kind, idx)

    def as_context_lines(self) -> list[str]:
        return [
            f"[{kind}_{idx}] = {value}"
            for kind, entries in self._data.items()
            for idx, value in entries.items()
        ]

    def next_indices(self) -> dict[str, int]:
        return {kind: max(entries.keys()) + 1 for kind, entries in self._data.items()}

    def total_count(self) -> int:
        return sum(len(entries) for entries in self._data.values())

    def as_reverse_map(self) -> dict[str, str]:
        return {
            _placeholder(kind, idx): value
            for kind, entries in self._data.items()
            for idx, value in entries.items()
        }

    def register(self, kind: str, num: int, value: str) -> None:
        """Register a specific placeholder (used when SLM assigns its own numbers)."""
        self._data.setdefault(kind, {}).setdefault(num, value)

    def _find(self, kind: str, value: str) -> str | None:
        for idx, v in self._data.get(kind, {}).items():
            if v.lower() == value.lower():
                return _placeholder(kind, idx)
        return None

    def _next_index(self, kind: str) -> int:
        return max(self._data.get(kind, {}).keys(), default=0) + 1


def _placeholder(kind: str, idx: int) -> str:
    return f"[{kind}_{idx}]"
