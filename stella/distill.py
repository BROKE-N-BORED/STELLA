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
# S4: how long the teacher stays loaded after each answer. Every
# prompt's call refreshes it, so 30 minutes spans the gaps between
# prompts without ever pinning the model forever: on an 8 GB PC
# the teacher must unload after the run, so never -1 (forever).
DISTILL_KEEP_ALIVE = "30m"


def _read_prompts(path: str | Path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        raise StellaError(
            f"No prompts file at {path}. Make a plain text file with "
            "one prompt per line."
        )
    prompts = [
        line.strip()
        # R85: utf-8-sig strips a leading byte-order mark, so a
        # prompts file saved with a BOM does not send an invisible
        # character as the first character of prompt 1. BOM-less
        # files read byte-identical.
        for line in path.read_text(encoding="utf-8-sig").splitlines()
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


def _plain_teacher_error(exc: Exception) -> str:
    """A teacher failure in plain words, naming the real cause
    (R30). A timeout is not Ollama being down — Ollama is running,
    just slow — so the generic "Is Ollama running on this PC?
    (timed out)" is reworded here, in the distill-facing message,
    instead of rewriting the shared Ollama error other callers
    rely on."""
    text = str(exc)
    if "timed out" in text.lower():
        return (
            "the teacher took too long to answer (it timed out). "
            "The teacher may still have been loading, or the "
            "prompt may need a longer wait."
        )
    return text


def _ask_teacher(_generate, tag: str, prompt: str) -> tuple[str, bool]:
    """One teacher answer: (text, truncated). The generate seam
    returns either plain text (the old shape, no truncation info)
    or a {"text", "done_reason"} dict (R35: generate_full's
    shape) — a done_reason of "length" means the answer was cut
    off at the token cap."""
    reply = _generate(tag, prompt)
    if isinstance(reply, dict):
        text = reply.get("text") or ""
        return text, reply.get("done_reason") == "length"
    return reply if isinstance(reply, str) else "", False


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
    should_stop=None,
    _generate=None,
) -> dict:
    """Ask the teacher every prompt and save the answers as a dataset.

    Writes project_dir/distilled.jsonl (appending one row at a time,
    so a stop mid-run keeps its progress) and points the project at
    it. Returns a report: prompts, asked, skipped counts, failed
    prompts, rows, and the dataset path. Raises StellaError in plain
    words when the teacher is missing, the prompts file is empty, or
    fewer than 2 good rows come back (training needs at least 2).
    `should_stop` (a no-arg callable, T74) cancels between prompts:
    the answers so far stay saved, and a re-run picks up where it
    stopped. `timeout` (S3) is how long to wait for each answer, in
    seconds. Every prompt's call also carries keep_alive (S4,
    DISTILL_KEEP_ALIVE): the teacher stays loaded across prompts
    instead of reloading on each one, and unloads on its own
    after the run.

    A failed prompt (R30) no longer aborts the run: it is retried
    once, then skipped, counted, and reported at the end — the
    prompts after it are still asked, and the message says plainly
    that the saved answers are kept and a re-run resumes. A
    truncated answer (R35: the teacher hit the token cap
    mid-answer) is never saved as a full answer: it is skipped,
    counted, and reported the same way.
    """
    store.get_profile(profile)
    store.get_project(profile, project)
    prompts = _read_prompts(prompts_path)
    _check_teacher(teacher_tag, ollama_url)

    project_dir = store.project_dir(profile, project)
    out_path = project_dir / DISTILLED_FILENAME
    answered = _read_answered_prompts(out_path)

    if _generate is None:
        def _generate(tag: str, prompt: str) -> dict:
            return ollama_client.generate_full(
                tag, prompt, url=ollama_url, timeout=timeout,
                keep_alive=DISTILL_KEEP_ALIVE,
            )

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    asked = 0
    skipped_empty = 0
    skipped_dup = 0
    skipped_resumed = 0
    skipped_truncated = 0
    failed: list[dict] = []
    kept = 0
    asked_this_run: set[str] = set()
    with out_path.open("a", encoding="utf-8") as handle:
        for index, prompt in enumerate(prompts, 1):
            if should_stop is not None and should_stop():
                # Cancelled between prompts (T74): the answers so
                # far are already on disk, and a re-run skips them.
                raise StellaError(
                    "Cancelled. The answers so far are saved; run it "
                    "again to pick up where it stopped."
                )
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
            # R30: one bad prompt must not kill hours of work — a
            # failure is retried once, then skipped and reported,
            # and the run goes on to the next prompt.
            reply = None
            truncated = False
            last_error: str | None = None
            for _attempt in range(2):
                try:
                    reply, truncated = _ask_teacher(
                        _generate, teacher_tag, prompt
                    )
                    last_error = None
                    break
                except StellaError as exc:
                    last_error = _plain_teacher_error(exc)
            if last_error is not None:
                failed.append(
                    {"prompt": prompt, "error": last_error}
                )
                emit({
                    "type": "warning",
                    "message": (
                        f"prompt {index} of {len(prompts)} got no "
                        f"answer ({last_error}). The answers so far "
                        "are saved; run it again to pick up where "
                        "it stopped."
                    ),
                })
                continue
            asked += 1
            # R35: a truncated answer is cut off mid-sentence — it
            # is skipped, never saved as a full training example.
            if truncated:
                skipped_truncated += 1
                emit({
                    "type": "warning",
                    "message": (
                        f"prompt {index} of {len(prompts)} got an "
                        "answer that was cut off mid-sentence (the "
                        "teacher hit its length limit), so it was "
                        "not saved. Ask it again with a shorter "
                        "prompt, or raise the limit."
                    ),
                })
                continue
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

    if failed:
        emit({
            "type": "warning",
            "message": (
                f"{len(failed)} prompt(s) got no answer from the "
                "teacher. The answers so far are saved; run it "
                "again to pick up where it stopped."
            ),
        })
    if skipped_truncated:
        emit({
            "type": "warning",
            "message": (
                f"{skipped_truncated} answer(s) were cut off "
                "mid-sentence and were not saved."
            ),
        })

    # v0.35.0 (N7): the success gate looks at THIS run, not at
    # the whole file. Rows left over from an older run (for
    # prompts that are not even in this run's file) must not turn
    # a run where every prompt failed into a success: no new kept
    # rows plus failures means refuse, without pointing the
    # project at the dataset or saying done.
    if kept == 0 and failed:
        raise StellaError(
            "None of this run's prompts got a usable answer from "
            f"the teacher ({len(failed)} prompt(s) failed), so no "
            "new dataset was made. The answers saved from earlier "
            "runs are still on disk; run it again to pick up where "
            "it stopped."
        )
    # The whole file must be a valid training dataset. This also
    # catches a file the user hand-edited into a bad state. When
    # failures left too few rows, the refusal names the resume
    # behaviour too — the answers so far are still on disk.
    try:
        _examples, info = load_dataset(out_path)
    except StellaError as exc:
        if failed:
            raise StellaError(
                f"{exc} {len(failed)} prompt(s) got no answer from "
                "the teacher. The answers so far are saved; run it "
                "again to pick up where it stopped."
            ) from exc
        raise
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
        "skipped_truncated": skipped_truncated,
        "failed": len(failed),
        "failed_prompts": failed,
        "rows": info["count"],
        "dataset": str(out_path),
    }
