"""STELLA sleep phase — consolidate new knowledge without forgetting old.

Stella's implementation of the two stages in Google Research's sleep
framework ("The sleep framework: A new way for LLMs to retain
knowledge in continual learning", blog Oct 27, 2026; "Language Models
Need Sleep", Behrouz et al., arXiv 2606.03979):

1. CONSOLIDATION — distill fragile short-term memory (the new rows
   added since the last sleep) into a NEW low-rank LoRA adapter. The
   base and all prior adapters stay frozen; each cycle's adapter
   lives in its own folder.
2. DREAMING — the local model writes its own practice examples,
   seeded by real ones. Stella keeps only the rows that pass the
   same validation as real data, dedupes them, and caps them at the
   number of real rows in the cycle.

The replay check is what makes this sleep and not just another
training run: before a cycle is accepted, the new adapter is
evaluated on a held-out mix of OLD validation rows (kept from prior
cycles) and NEW validation rows. If the old loss degrades beyond a
threshold (default +10% relative), the cycle is flagged DEGRADED —
still saved, never silently accepted as good.

Honest limits (also in the README — do not oversell this):
- Google published NO code and their numbers are the authors' own,
  not independently reproduced. Stella implements the same two
  stages at its own scale; it does not reproduce Google's results.
- No RL refinement (not feasible on CPU at this scale — SFT only).
- No MoE routing: Ollama cannot route LoRA experts. Adapters merge
  into the base through the existing GGUF export path.
- Dreaming quality depends entirely on the local model doing the
  dreaming; dreamed rows are capped and validated, never trusted.

Layout (under the project dir):

    sleep/
      manifest.json     # slept row hashes, dreamed hashes, old val
                        # rows, per-cycle summaries
      cycle-N/
        adapter/        # this cycle's LoRA adapter
        checkpoints/    # consolidation checkpoints (resume)
        train_rows.jsonl  # the cycle's training rows (messages format)
        val_rows.jsonl    # held-out new val rows for the replay check
        cycle_input.json  # real/dreamed hashes + counts for resume
        report.json     # full cycle report (losses, status, settings)
        train_log.jsonl # consolidation step log

One model at a time, always: the replay check loads the base ONCE
and evaluates old-then-new sequentially (adapter swapping on the
one loaded base). Loading two models at once is the probe's known
P0 (~7 GB for two LFM3 loads on an 8 GB machine) — sleep must
never repeat it. The test suite proves the single load.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

from .job_lock import job_lock
from .model import STELLA_VERSION, StellaError, Store, utc_now
from .train import (
    TrainController,
    load_dataset,
    resolve_dataset_ref,
    split_dataset,
    train_project,
    validate_dataset_row,
)

# Held-out old validation rows kept in the manifest (most recent
# first-come cap — enough to smell forgetting, small enough to keep
# the manifest readable).
MAX_OLD_VAL_ROWS = 50

# Dreaming: one generation call per cycle, at most this many rows,
# and never more dreamed rows than real rows in the cycle.
MAX_DREAMED_PER_CALL = 10

# Forgetting threshold: a cycle is DEGRADED when the old loss rises
# more than this (relative) after consolidation.
DEFAULT_THRESHOLD = 0.10

# Ollama generation budget for one dream call. A local CPU model is
# slow; 120s lets a small model finish, and a timeout still fails
# fast into "dreaming skipped" instead of hanging the cycle.
DREAM_TIMEOUT_SECONDS = 120.0

SLEEP_VERSION = "0.3"


# -- paths + manifest -----------------------------------------------

def sleep_dir(store: Store, profile: str, project: str) -> Path:
    return store.project_dir(profile, project) / "sleep"


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _empty_manifest() -> dict:
    return {
        "stella_version": SLEEP_VERSION,
        "slept_hashes": [],
        "dreamed_hashes": [],
        "old_val_rows": [],
        "cycles": [],
    }


def load_sleep_manifest(store: Store, profile: str, project: str) -> dict:
    """Read the sleep manifest (reconciled, not written).

    A cycle dir with a report.json but no manifest entry (a crash
    between the report write and the manifest update) is healed
    back into the cycle list from its report.
    """
    path = sleep_dir(store, profile, project) / "manifest.json"
    manifest = _empty_manifest()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            for key in manifest:
                if key in data:
                    manifest[key] = data[key]
    known = {c.get("cycle") for c in manifest["cycles"] if isinstance(c, dict)}
    sdir = sleep_dir(store, profile, project)
    if sdir.is_dir():
        for cdir in sorted(sdir.iterdir()):
            if not cdir.is_dir() or not cdir.name.startswith("cycle-"):
                continue
            report_path = cdir / "report.json"
            if not report_path.is_file():
                continue
            try:
                number = int(cdir.name.split("-", 1)[1])
            except ValueError:
                continue
            if number in known:
                continue
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            manifest["cycles"].append(_cycle_summary(report))
            known.add(number)
    manifest["cycles"].sort(key=lambda c: c.get("cycle", 0))
    return manifest


def save_sleep_manifest(store: Store, profile: str, project: str, manifest: dict) -> None:
    _atomic_write_json(
        sleep_dir(store, profile, project) / "manifest.json", manifest
    )


def _cycle_summary(report: dict) -> dict:
    return {
        "cycle": report.get("cycle", 0),
        "status": report.get("status", "OK"),
        "timestamp": report.get("timestamp", ""),
        "real_rows": report.get("real_rows", 0),
        "dreamed_rows": report.get("dreamed_rows", 0),
        "old_loss_before": report.get("old_loss_before"),
        "old_loss_after": report.get("old_loss_after"),
        "new_loss": report.get("new_loss"),
        "steps": report.get("steps", 0),
    }


def list_sleep_cycles(store: Store, profile: str, project: str) -> list[dict]:
    """Per-cycle summaries, oldest first (from the manifest)."""
    return list(load_sleep_manifest(store, profile, project)["cycles"])


def read_cycle_report(
    store: Store, profile: str, project: str, cycle: int
) -> dict:
    """The full report.json for one cycle."""
    report_path = (
        sleep_dir(store, profile, project) / f"cycle-{cycle}" / "report.json"
    )
    if not report_path.is_file():
        raise StellaError(f"no sleep report for cycle {cycle}")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StellaError(f"cycle {cycle} report is not valid JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise StellaError(f"cycle {cycle} report must hold a JSON object")
    return report


# -- row hashing ----------------------------------------------------

def row_hash(example: dict) -> str:
    """Content hash of one normalized example ({"messages": [...]})."""
    canonical = json.dumps(example, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _example_from_messages(messages: list[dict]) -> dict:
    return {"messages": [{"role": m["role"], "content": m["content"]} for m in messages]}


# -- dreaming -------------------------------------------------------

def _dream_prompt(seeds: list[dict], count: int) -> str:
    seed_lines = "\n".join(
        json.dumps(_example_from_messages(ex["messages"]), ensure_ascii=False)
        for ex in seeds
    )
    return (
        "You write training examples for a fine-tuning dataset. Each "
        "example is ONE JSON object on ONE line, in exactly this shape:\n"
        '{"messages": [{"role": "user", "content": "..."}, '
        '{"role": "assistant", "content": "..."}]}\n'
        f"Write {count} NEW examples in the same style and on the same "
        "topics as these real examples. One JSON object per line, "
        "nothing else — no intro, no numbering, no markdown.\n"
        "Real examples:\n"
        f"{seed_lines}\n"
        "New examples:\n"
    )


def _ollama_generate(
    model_tag: str, prompt: str, url: str | None, timeout: float
) -> str:
    """One /api/generate call, no streaming. Raises on any failure —
    the caller turns every failure into 'dreaming skipped'."""
    from .ollama import ollama_url

    base = (url or ollama_url()).rstrip("/")
    payload = json.dumps(
        {
            "model": model_tag,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.8, "num_predict": 2048},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = body.get("response") if isinstance(body, dict) else None
    if not isinstance(text, str):
        raise ValueError("Ollama returned no text")
    return text


def dream_rows(
    seeds: list[dict],
    *,
    model_tag: str,
    count: int,
    exclude_hashes: set[str] | frozenset = frozenset(),
    ollama_url: str | None = None,
    timeout: float = DREAM_TIMEOUT_SECONDS,
) -> tuple[list[dict], str | None]:
    """Ask the local Ollama model for synthetic practice examples.

    Returns (rows, skipped_reason). `skipped_reason` is None when
    dreaming ran; on ANY failure it names the reason and rows holds
    what survived (possibly empty). Dreaming never raises — a failed
    dream is a skipped dream, and sleep still runs on real rows.

    Every kept row passes the same validation as real data
    (validate_dataset_row) and dedupes against `exclude_hashes`
    (real rows, slept rows, already-dreamed rows).
    """
    if not model_tag:
        return [], (
            "no Ollama model tag. Set one on the profile or pass "
            "--dream-model"
        )
    if count <= 0:
        return [], "nothing to dream (no new real rows)"
    if not seeds:
        return [], "no seed examples to dream from"
    try:
        raw = _ollama_generate(
            model_tag, _dream_prompt(seeds[:3], count), ollama_url, timeout
        )
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        return [], f"Ollama unreachable ({exc}) . Dreaming skipped"
    kept: list[dict] = []
    seen = set(exclude_hashes)
    for line_no, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            _fmt, messages = validate_dataset_row(row, line_no)
        except StellaError:
            continue
        example = _example_from_messages(messages)
        h = row_hash(example)
        if h in seen:
            continue
        seen.add(h)
        kept.append(example)
        if len(kept) >= count:
            break
    return kept, None


# -- replay check (the forgetting guard) -----------------------------

def replay_check(
    store: Store,
    profile: str,
    project: str,
    cycle_dir: str | Path,
    old_val: list[dict],
    new_val: list[dict],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    prev_adapter: str | Path | None = None,
    _model_loader=None,
    _dtype: str = "bfloat16",
    max_seq_len: int = 1024,
) -> dict:
    """Evaluate a cycle's adapter against old + new validation rows.

    ONE MODEL AT A TIME (hard rule): the base loads once, and the
    old-then-new evaluations run sequentially by adapter swapping on
    that one loaded base. Never two models at once — the probe's
    double-load is a known P0 on this 8 GB machine.

    "Before" is the previous cycle's adapter (or the bare base on
    cycle 1); "after" is this cycle's adapter. A cycle is DEGRADED
    when the old loss rises more than `threshold` (relative).
    """
    from .train import evaluate_loss, load_base_model, require_training_deps

    require_training_deps()
    prof = store.get_profile(profile)
    base_ref = prof.get("base_ref") or ""
    if not base_ref:
        from .train import LFM3_HF_REPO

        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    cycle_dir = Path(cycle_dir)
    new_adapter = cycle_dir / "adapter"
    if not (new_adapter / "adapter_config.json").is_file():
        raise StellaError(
            f"cycle {cycle_dir.name} has no trained adapter yet. "
            "consolidation must finish before the replay check"
        )

    # The single load. Everything below reuses this one model.
    if _model_loader is not None:
        base_model, tokenizer = _model_loader()
    else:
        base_model, tokenizer = load_base_model(base_ref, dtype=_dtype)

    from peft import PeftModel

    prev = Path(prev_adapter) if prev_adapter is not None else None
    if prev is not None and (prev / "adapter_config.json").is_file():
        model = PeftModel.from_pretrained(base_model, str(prev), adapter_name="prev")
        old_before = evaluate_loss(
            model, tokenizer, old_val, max_seq_len=max_seq_len
        )
        model.load_adapter(str(new_adapter), adapter_name="new")
        model.set_adapter("new")
        old_after = evaluate_loss(
            model, tokenizer, old_val, max_seq_len=max_seq_len
        )
        new_after = evaluate_loss(
            model, tokenizer, new_val, max_seq_len=max_seq_len
        )
    else:
        old_before = evaluate_loss(
            base_model, tokenizer, old_val, max_seq_len=max_seq_len
        )
        model = PeftModel.from_pretrained(base_model, str(new_adapter))
        old_after = evaluate_loss(
            model, tokenizer, old_val, max_seq_len=max_seq_len
        )
        new_after = evaluate_loss(
            model, tokenizer, new_val, max_seq_len=max_seq_len
        )

    status = "OK"
    delta = None
    if old_before is not None and old_after is not None:
        # Rounded before comparing: 1.10 - 1.0 is 0.10000000000000009
        # in floats, and a cycle exactly AT the threshold must not be
        # flagged DEGRADED by float noise.
        delta = round((old_after - old_before) / max(old_before, 1e-6), 4)
        if delta > threshold:
            status = "DEGRADED"
    return {
        "old_loss_before": old_before,
        "old_loss_after": old_after,
        "new_loss": new_after,
        "old_delta_relative": delta,
        "status": status,
        "threshold": threshold,
        "old_val_rows": len(old_val),
        "new_val_rows": len(new_val),
    }


# -- consolidation (one sleep cycle) --------------------------------

def _split_cycle_rows(rows: list[dict], seed: int = 42) -> tuple[list[dict], list[dict], bool]:
    """Split cycle rows into train + held-out new val for the replay
    check. Tiny cycles (< 4 rows) keep all rows for training and
    reuse them in-sample for the check (flagged in the report)."""
    if len(rows) < 4:
        return list(rows), list(rows), True
    train, val = split_dataset(rows, 0.2, seed)
    if not val:
        val = [train.pop()]
    return train, val, False


def _write_rows_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(_example_from_messages(ex["messages"]), ensure_ascii=False) + "\n"
            for ex in rows
        ),
        encoding="utf-8",
    )


def _load_rows_file(path: Path) -> list[dict]:
    """Read back a persisted cycle rows file (train or val).

    Unlike load_dataset, this has no minimum-row rule — a val file
    legitimately holds a single held-out row, and resume must be
    able to read it back.
    """
    examples: list[dict] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise StellaError(f"cannot read {path.name}: {exc}") from exc
    for line_no, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StellaError(
                f"{path.name} line {line_no}: not valid JSON: {exc}"
            ) from exc
        _fmt, messages = validate_dataset_row(row, line_no)
        examples.append({"messages": messages})
    return examples


def _find_unfinished_cycle(
    store: Store, profile: str, project: str
) -> tuple[int, Path] | None:
    """An unfinished cycle has its rows AND its input file persisted
    but no report yet (interrupted consolidation). Returns (number,
    dir) or None.

    All three input files must be present: the fresh-cycle path
    writes train_rows, val_rows, then cycle_input in sequence, so a
    crash between the writes leaves a partial dir. A partial dir is
    NOT resumable — it is ignored here, and the next fresh cycle
    reuses its number and overwrites it (safe: no checkpoints or
    adapter can exist before cycle_input.json is written, because
    training only starts after it).
    """
    sdir = sleep_dir(store, profile, project)
    if not sdir.is_dir():
        return None
    best = None
    for cdir in sorted(sdir.iterdir()):
        if not cdir.is_dir() or not cdir.name.startswith("cycle-"):
            continue
        try:
            number = int(cdir.name.split("-", 1)[1])
        except ValueError:
            continue
        if (cdir / "report.json").is_file():
            continue
        if not (cdir / "train_rows.jsonl").is_file():
            continue
        if not (cdir / "val_rows.jsonl").is_file():
            continue
        if not (cdir / "cycle_input.json").is_file():
            continue
        if best is None or number > best[0]:
            best = (number, cdir)
    return best


def sleep_project(
    store: Store,
    profile: str,
    project: str,
    *,
    dream: bool = False,
    dream_model: str | None = None,
    rows_path: str | Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    on_event=None,
    controller: TrainController | None = None,
    _model_loader=None,
    _dtype: str = "bfloat16",
    _ollama_url: str | None = None,
) -> dict:
    """Run one sleep cycle for a project. Returns the cycle report.

    Cheap checks run before the dependency gate, so a missing
    dataset or "nothing new" is reported even on a base install
    (the train CLI's gate-first ordering masked real errors — the
    sleep CLI does not repeat that).
    """
    from .train import LFM3_HF_REPO

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    project_dir = store.project_dir(profile, project)
    base_ref = prof.get("base_ref") or ""
    if not base_ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )

    manifest = load_sleep_manifest(store, profile, project)
    slept = set(manifest["slept_hashes"])
    dreamed_known = set(manifest["dreamed_hashes"])

    # Resume first: an unfinished cycle reuses its persisted rows
    # (no re-dreaming, no re-counting — the cycle is the same one).
    unfinished = _find_unfinished_cycle(store, profile, project)
    if unfinished is not None:
        cycle_no, cycle_dir = unfinished
        try:
            cycle_input = json.loads(
                (cycle_dir / "cycle_input.json").read_text(encoding="utf-8")
            )
            real_hashes = cycle_input["real_hashes"]
            dreamed_hashes = cycle_input["dreamed_hashes"]
            real_count = cycle_input["real_rows"]
            dreamed_count = cycle_input["dreamed_rows"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise StellaError(
                f"sleep cycle {cycle_no} was interrupted and its input "
                f"file is damaged ({exc}). Delete "
                f"{cycle_dir} and run sleep again. No rows are lost, "
                "they are still in the dataset."
            ) from exc
        train_rows = _load_rows_file(cycle_dir / "train_rows.jsonl")
        val_rows = _load_rows_file(cycle_dir / "val_rows.jsonl")
        in_sample = cycle_input.get("new_val_in_sample", False)
        resumed = True
    else:
        # Fresh cycle: which rows are new?
        if rows_path is not None:
            rows_file = Path(rows_path).expanduser()
            if not rows_file.is_file():
                raise StellaError(f"rows file not found: {rows_file}")
            all_rows, _info = load_dataset(rows_file)
        else:
            dataset_ref = proj.get("dataset_ref") or ""
            if not dataset_ref:
                raise StellaError(
                    f"project {project!r} has no dataset set. Pick a "
                    ".jsonl dataset in the Train panel, or pass --rows"
                )
            data_path = resolve_dataset_ref(
                store, profile, project, dataset_ref
            )
            all_rows, _info = load_dataset(data_path)
        new_rows = [ex for ex in all_rows if row_hash(ex) not in slept]
        if not new_rows:
            raise StellaError(
                "No new rows to sleep on. Every row in the dataset "
                "has already been slept on. Add rows to the dataset "
                "or pass --rows with a file of new rows."
            )

        # Dream (best effort, never fatal).
        dreamed_rows: list[dict] = []
        dream_note = None
        if dream:
            tag = dream_model or prof.get("ollama_tag") or ""
            want = min(len(new_rows), MAX_DREAMED_PER_CALL)
            exclude = {row_hash(ex) for ex in all_rows} | dreamed_known
            dreamed_rows, dream_note = dream_rows(
                new_rows,
                model_tag=tag,
                count=want,
                exclude_hashes=exclude,
                ollama_url=_ollama_url,
            )
            if dream_note is not None:
                emit({"type": "dream_skipped", "reason": dream_note})
            else:
                emit(
                    {
                        "type": "dream",
                        "requested": want,
                        "kept": len(dreamed_rows),
                    }
                )

        cycle_rows = list(new_rows) + dreamed_rows
        if len(cycle_rows) < 2:
            raise StellaError(
                "A sleep cycle needs at least 2 rows. Only "
                f"{len(cycle_rows)} new row(s) found. Add more rows "
                "or try --dream for synthetic ones."
            )
        train_rows, val_rows, in_sample = _split_cycle_rows(cycle_rows)
        real_hashes = [row_hash(ex) for ex in new_rows]
        dreamed_hashes = [row_hash(ex) for ex in dreamed_rows]
        real_count = len(new_rows)
        dreamed_count = len(dreamed_rows)
        cycle_no = max([c.get("cycle", 0) for c in manifest["cycles"]], default=0) + 1
        cycle_dir = sleep_dir(store, profile, project) / f"cycle-{cycle_no}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        _write_rows_jsonl(cycle_dir / "train_rows.jsonl", train_rows)
        _write_rows_jsonl(cycle_dir / "val_rows.jsonl", val_rows)
        _atomic_write_json(
            cycle_dir / "cycle_input.json",
            {
                "real_hashes": real_hashes,
                "dreamed_hashes": dreamed_hashes,
                "real_rows": real_count,
                "dreamed_rows": dreamed_count,
                "new_val_in_sample": in_sample,
                "stella_version": STELLA_VERSION,
            },
        )
        resumed = False

    if controller is not None and controller.stop_requested:
        raise StellaError(
            "Sleep paused before training started. Run sleep again "
            "to start this cycle."
        )

    emit(
        {
            "type": "started",
            "cycle": cycle_no,
            "new_rows": real_count,
            "dreamed_rows": dreamed_count,
            "resumed": resumed,
        }
    )

    # Consolidate: the train engine, into this cycle's dir. Sleep
    # rank is capped at 8 (micro-LoRA); the project status is left
    # alone — sleep is a background job, not a retrain.
    settings = dict(proj.get("settings", {}) or {})
    sleep_rank = min(int(settings.get("rank", 8)), 8)

    def _forward(event: dict):
        # Step/checkpoint/val/progress flow through; "done" and
        # "paused" are sleep's to report, not the loop's. Warnings
        # (T99: over-long rows cut short) flow through too.
        if event.get("type") in ("started", "step", "checkpoint", "val", "warning"):
            emit(event)

    has_checkpoints = (cycle_dir / "checkpoints").is_dir() and any(
        (cycle_dir / "checkpoints").iterdir()
    )
    # One job at a time (T29): sleep loads models twice (the
    # consolidation train, then the replay check), so the whole
    # cycle holds the home's job lock. The inner train call
    # skips its own lock: this one already covers it.
    with job_lock(store.home, f"sleep {profile}/{project}"):
        summary = train_project(
            store,
            profile,
            project,
            dataset_path=cycle_dir / "train_rows.jsonl",
            on_event=_forward,
            controller=controller,
            _model_loader=_model_loader,
            _dtype=_dtype,
            work_dir=cycle_dir,
            update_status=False,
            resume=(resumed and has_checkpoints),
            settings_override={"rank": sleep_rank},
            _skip_job_lock=True,
        )
        if summary["stopped"]:
            emit({"type": "paused", "cycle": cycle_no, "step": summary["steps"]})
            return {
                "cycle": cycle_no,
                "status": "paused",
                "steps": summary["steps"],
                "real_rows": real_count,
                "dreamed_rows": dreamed_count,
                "resumed": resumed,
            }

        # Replay check: one model at a time, old then new.
        emit({"type": "replay", "cycle": cycle_no})
        prev_adapter = None
        if cycle_no > 1:
            prev_dir = sleep_dir(store, profile, project) / f"cycle-{cycle_no - 1}" / "adapter"
            if (prev_dir / "adapter_config.json").is_file():
                prev_adapter = prev_dir
        old_val = [
            _example_from_messages(ex["messages"])
            for ex in manifest["old_val_rows"]
        ]
        replay = replay_check(
            store,
            profile,
            project,
            cycle_dir,
            old_val,
            val_rows,
            threshold=threshold,
            prev_adapter=prev_adapter,
            _model_loader=_model_loader,
            _dtype=_dtype,
            max_seq_len=int(settings.get("max_seq_len", 1024)),
        )
        emit({"type": "replay_done", **replay})

        report = {
            "stella_version": STELLA_VERSION,
            "cycle": cycle_no,
            "timestamp": utc_now(),
            "status": replay["status"],
            "real_rows": real_count,
            "dreamed_rows": dreamed_count,
            "steps": summary["steps"],
            "final_loss": summary["final_loss"],
            "old_loss_before": replay["old_loss_before"],
            "old_loss_after": replay["old_loss_after"],
            "new_loss": replay["new_loss"],
            "old_delta_relative": replay["old_delta_relative"],
            "threshold": threshold,
            "old_val_rows": replay["old_val_rows"],
            "new_val_rows": replay["new_val_rows"],
            "new_val_in_sample": in_sample,
            "rank": sleep_rank,
            "trainable_params": summary["trainable_params"],
            "ram_estimate_gb": summary["ram_estimate_gb"],
            "resumed": resumed,
        }
        _atomic_write_json(cycle_dir / "report.json", report)

        # Manifest: mark the real rows slept, bank the dreamed hashes,
        # and keep this cycle's val rows as tomorrow's old val rows.
        manifest["slept_hashes"] = sorted(slept | set(real_hashes))
        manifest["dreamed_hashes"] = sorted(dreamed_known | set(dreamed_hashes))
        kept_val = manifest["old_val_rows"] + [
            _example_from_messages(ex["messages"]) for ex in val_rows
        ]
        manifest["old_val_rows"] = kept_val[-MAX_OLD_VAL_ROWS:]
        manifest["cycles"] = [
            c for c in manifest["cycles"] if c.get("cycle") != cycle_no
        ]
        manifest["cycles"].append(_cycle_summary(report))
        manifest["cycles"].sort(key=lambda c: c.get("cycle", 0))
        save_sleep_manifest(store, profile, project, manifest)

        emit({"type": "done", "cycle": cycle_no, "status": replay["status"]})
        return report


# -- status ---------------------------------------------------------

def sleep_status(store: Store, profile: str, project: str) -> dict:
    """Per-cycle stats + unslept row count. No torch needed."""
    store.get_profile(profile)
    proj = store.get_project(profile, project)
    manifest = load_sleep_manifest(store, profile, project)
    slept = set(manifest["slept_hashes"])
    total = None
    unslept = None
    dataset_ref = proj.get("dataset_ref") or ""
    if dataset_ref:
        try:
            data_path = resolve_dataset_ref(store, profile, project, dataset_ref)
            examples, _info = load_dataset(data_path)
            total = len(examples)
            unslept = sum(1 for ex in examples if row_hash(ex) not in slept)
        except StellaError:
            total = None
            unslept = None
    return {
        "profile": profile,
        "project": project,
        "cycles": manifest["cycles"],
        "slept_rows": len(slept),
        "dreamed_rows": len(manifest["dreamed_hashes"]),
        "old_val_rows": len(manifest["old_val_rows"]),
        "total_rows": total,
        "unslept_rows": unslept,
    }
