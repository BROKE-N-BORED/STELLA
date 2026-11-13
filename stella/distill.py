"""STELLA distillation — teach a small model from a big one.

A teacher model (any model already in Ollama) answers a list of
prompts, one by one. Its answers become a JSONL dataset in the
project, and the project's dataset points at it, so the next step
is the plain `stella train` command. Training is NOT started here:
the user looks at the dataset first, then trains when ready.

One prompt makes one example: {"prompt": ..., "completion": ...}.
No chat templates in v0.5. Empty teacher replies are skipped and
counted, identical prompt/answer pairs are kept only once, and a
re-run skips the prompts already answered in the output file, so
stopping and starting again never wastes teacher time.

The student learns only what the teacher was asked about. That is
the whole point: a small model that does the jobs it was taught,
and nothing else. The quality of the result depends on the
teacher: a teacher that answers badly teaches badly.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import ollama as ollama_client
from .model import StellaError, Store
from .train import load_dataset, validate_dataset_row

DISTILLED_FILENAME = "distilled.jsonl"
DEFAULT_TIMEOUT_SECONDS = 300.0


def _read_prompts(path: str | Path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        raise StellaError(
            f"No prompts file at {path}. Make a plain text file with "
            "one prompt per line."
        )
    prompts = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not prompts:
        raise StellaError(
            f"The prompts file {path} is empty. Add one prompt per "
            "line, then run distill again."
        )
    return prompts


def _check_teacher(tag: str, url: str | None) -> None:
    """The teacher must be installed and Ollama must be running."""
    if not ollama_client.reachable(url):
        raise StellaError(
            "Ollama is not running, so the teacher cannot answer. "
            "Start Ollama and try again."
        )
    installed = ollama_client.list_models(url)
    candidates = {tag, tag + ":latest"} if ":" not in tag else {tag}
    if not candidates.intersection(installed):
        raise StellaError(
            f"Ollama does not have a model called {tag!r} installed. "
            "Check the tag, or pull the model first."
        )


def _read_answered_prompts(path: Path) -> set[str]:
    """Prompts already answered in an output file (stripped).

    Malformed lines are ignored: they stay in the file, and the
    final validation names them if they matter.
    """
    answered: set[str] = set()
    if not path.is_file():
        return answered
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        prompt = row.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            answered.add(prompt.strip())
    return answered


def distill_dataset(
    store: Store,
    profile: str,
    project: str,
    teacher_tag: str,
    prompts_path: str | Path,
    *,
    ollama_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_event=None,
    _generate=None,
) -> dict:
    """Ask the teacher every prompt and save the answers as a dataset.

    Writes project_dir/distilled.jsonl (appending one row at a time,
    so a stop mid-run keeps its progress) and points the project at
    it. Returns a report: prompts, asked, skipped counts, rows, and
    the dataset path. Raises StellaError in plain words when the
    teacher is missing, the prompts file is empty, or fewer than 2
    good rows come back (training needs at least 2).
    """
    store.get_profile(profile)
    store.get_project(profile, project)
    prompts = _read_prompts(prompts_path)
    _check_teacher(teacher_tag, ollama_url)

    project_dir = store.project_dir(profile, project)
    out_path = project_dir / DISTILLED_FILENAME
    answered = _read_answered_prompts(out_path)

    if _generate is None:
        def _generate(tag: str, prompt: str) -> str:
            return ollama_client.generate(
                tag, prompt, url=ollama_url, timeout=timeout
            )

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    asked = 0
    skipped_empty = 0
    skipped_dup = 0
    skipped_resumed = 0
    kept = 0
    asked_this_run: set[str] = set()
    with out_path.open("a", encoding="utf-8") as handle:
        for index, prompt in enumerate(prompts, 1):
            if prompt in asked_this_run:
                # Same prompt twice in the file: one answer is
                # enough, the pair would be a duplicate. This check
                # comes first: the first occurrence is already in
                # `answered` by now, and a same-run repeat is a
                # duplicate, not a resume.
                skipped_dup += 1
                continue
            if prompt in answered:
                skipped_resumed += 1
                continue
            asked_this_run.add(prompt)
            emit({
                "type": "prompt",
                "index": index,
                "total": len(prompts),
                "prompt": prompt,
            })
            reply = _generate(teacher_tag, prompt)
            asked += 1
            if not reply.strip():
                skipped_empty += 1
                continue
            row = {"prompt": prompt, "completion": reply}
            try:
                validate_dataset_row(row, index)
            except StellaError:
                skipped_empty += 1
                continue
            answered.add(prompt)
            handle.write(
                json.dumps(row, ensure_ascii=False) + "\n"
            )
            handle.flush()
            kept += 1

    # The whole file must be a valid training dataset. This also
    # catches a file the user hand-edited into a bad state.
    _examples, info = load_dataset(out_path)
    store.update_project(
        profile, project, dataset_ref=DISTILLED_FILENAME
    )
    emit({"type": "done", "rows": info["count"]})
    return {
        "teacher": teacher_tag,
        "prompts": len(prompts),
        "asked": asked,
        "skipped_empty": skipped_empty,
        "skipped_dup": skipped_dup,
        "skipped_resumed": skipped_resumed,
        "rows": info["count"],
        "dataset": str(out_path),
    }
