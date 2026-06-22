import asyncio
import re
import sys
import anthropic
import click
from typing import TextIO
from .prompts import (
    ORCHESTRATOR_PROMPT,
    WORKER_PROMPT,
    SECTION_ORDER,
    SECTION_TITLES,
    FORMAT_HINTS,
)

# Orkiestrator zwraca plan XML (<analysis> + 3× <task>). Przy wielu/dużych dokumentach
# analiza bywa długa — 1024 ucinało plan przed domknięciem <tasks> (→ pusty plan → fallback).
_MAX_TOKENS_ORCHESTRATOR = 4096
# Worker generuje jedną sekcję raportu; 8192 daje zapas dla zestawów wielu dokumentów.
_MAX_TOKENS_WORKER = 8192


class DocumentAnalysisPipeline:
    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        output: TextIO | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._output = output or sys.stdout

    async def run(self, text: str) -> str:
        self._echo("[1/2] Orkiestrator planuje analizę...")
        analysis, tasks = await self._orchestrate(text)
        self._echo(f"      {analysis[:120]}")

        n = len(tasks)
        self._echo(f"\n[2/2] Workery analizują {n} sekcji równolegle...")
        for i, task in enumerate(tasks, 1):
            self._echo(f"      [{i}/{n}] {task['type']}...")

        results_list = await asyncio.gather(
            *[self._work(text, analysis, task, i, n)
              for i, task in enumerate(tasks, 1)]
        )
        results = {task["type"]: content for task, content in zip(tasks, results_list)}
        return _assemble_report(results)

    async def _orchestrate(self, text: str) -> tuple[str, list[dict]]:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS_ORCHESTRATOR,
            messages=[{"role": "user", "content": ORCHESTRATOR_PROMPT.format(document=text)}],
        )
        raw = response.content[0].text
        analysis = _extract_xml(raw, "analysis") or "Dokument prawny"
        tasks = _parse_tasks(_extract_xml(raw, "tasks"))
        return analysis, tasks or _fallback_tasks()

    async def _work(
        self, text: str, analysis: str, task: dict, idx: int, total: int
    ) -> str:
        task_type = task["type"]
        prompt = WORKER_PROMPT.format(
            analysis=analysis,
            task_description=task["description"],
            format_hint=FORMAT_HINTS.get(task_type, ""),
            document=text,
        )
        chunks: list[str] = []
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=_MAX_TOKENS_WORKER,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for chunk in stream.text_stream:
                chunks.append(chunk)

        self._echo(f"      ✓ [{idx}/{total}] {task_type}")
        return "".join(chunks)

    def _echo(self, msg: str = "", nl: bool = True) -> None:
        click.echo(msg, file=self._output, nl=nl)


def _extract_xml(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_tasks(tasks_xml: str) -> list[dict]:
    tasks = []
    for m in re.finditer(r"<task>(.*?)</task>", tasks_xml, re.DOTALL):
        body = m.group(1)
        type_m = re.search(r"<type>(.*?)</type>", body)
        desc_m = re.search(r"<description>(.*?)</description>", body, re.DOTALL)
        if type_m and desc_m:
            tasks.append({
                "type": type_m.group(1).strip().lower(),
                "description": desc_m.group(1).strip(),
            })
    return tasks


def _assemble_report(results: dict[str, str]) -> str:
    sections = [
        f"{SECTION_TITLES[key]}\n\n{results.get(key, '_Brak danych._')}"
        for key in SECTION_ORDER
    ]
    return "\n\n---\n\n".join(sections)


def _fallback_tasks() -> list[dict]:
    return [
        {"type": t, "description": "Przeanalizuj dokument pod kątem tej sekcji raportu."}
        for t in SECTION_ORDER
    ]
