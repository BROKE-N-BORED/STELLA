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
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from .job_lock import job_lock, job_lock_held
from .model import STELLA_VERSION, StellaError, Store, utc_now
from .train import (
    TrainController,
    _dir_size_bytes,
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
# slow; 120s is the TOTAL budget for one call, not a fast fail —
# a slow-but-answering model may use all of it. What fails fast
# (R126) is a DEAD peer: the call streams, and if no chunk arrives
# within DREAM_SILENCE_SECONDS the dream is abandoned as skipped
# instead of waiting out the whole budget. Do not cut the 120s
# number to "fix" a stall: that budget is what lets a small CPU
# model finish dreaming at all.
DREAM_TIMEOUT_SECONDS = 120.0

# Silence budget inside one dream call (R126): give up when the
# peer sends nothing for this long. A generating model streams
# tokens continuously, so 30s of silence means the peer is hung,
# not slow — while the first token of a cold model load can take
# several seconds, well inside this.
DREAM_SILENCE_SECONDS = 30.0

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
        # R124: stella_version is the Stella that wrote this
        # manifest (it used to carry SLEEP_VERSION, "0.3" — the
        # manifest-format version, which now has its own key).
        "stella_version": STELLA_VERSION,
        "sleep_version": SLEEP_VERSION,
        "slept_hashes": [],
        "dreamed_hashes": [],
        "old_val_rows": [],
        "cycles": [],
        # Cycles with a report but no recoverable input file (R8):
        # listed here, never healed into `cycles`, so the rows
        # they slept on are never mistaken for recorded ones.
        "unhealed_cycles": [],
    }


def load_sleep_manifest(store: Store, profile: str, project: str) -> dict:
    """Read the sleep manifest (reconciled, not written).

    A cycle dir with a report.json but no manifest entry (a crash
    between the report write and the manifest update) is healed
    back into the cycle list from its report — and, since R8,
    its hash sets and old val rows are rebuilt from its own
    cycle_input.json / val_rows.jsonl, so the rows are not
    re-slept and the next replay check still has something to
    check against. When the input file is missing or damaged the
    hashes cannot be rebuilt: the cycle is NOT healed, and it is
    recorded under `unhealed_cycles` with the reason, so the
    state is visible instead of silently wrong.
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
    # Unhealed cycles are recomputed from disk on every read, like
    # the heal itself — a saved entry goes stale the moment the
    # cycle dir is deleted, so the file's copy is never trusted.
    manifest["unhealed_cycles"] = []
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
            # R8: rebuild the hash sets from the cycle's own input
            # file — the old heal restored the cycle list but left
            # slept_hashes / dreamed_hashes / old_val_rows empty,
            # so the rows were re-slept and the next replay check
            # was vacuous (empty old val -> loss None -> OK).
            try:
                cycle_input = json.loads(
                    (cdir / "cycle_input.json").read_text(encoding="utf-8")
                )
                real_hashes = cycle_input["real_hashes"]
                dreamed_hashes = cycle_input["dreamed_hashes"]
                if not isinstance(real_hashes, list) or not isinstance(
                    dreamed_hashes, list
                ):
                    raise TypeError("hash lists are not lists")
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                manifest["unhealed_cycles"].append({
                    "cycle": number,
                    "reason": (
                        "its input file is missing or damaged, so the "
                        "rows it slept on cannot be recovered"
                    ),
                })
                continue
            manifest["slept_hashes"] = sorted(
                set(manifest["slept_hashes"]) | set(real_hashes)
            )
            manifest["dreamed_hashes"] = sorted(
                set(manifest["dreamed_hashes"]) | set(dreamed_hashes)
            )
            try:
                val_rows = _load_rows_file(cdir / "val_rows.jsonl")
            except StellaError:
                # The val file is best effort: the hashes above are
                # the record that must survive, and a cycle whose
                # val rows are gone still heals (the next replay
                # check uses whatever old val rows remain).
                val_rows = []
            if val_rows:
                kept = manifest["old_val_rows"] + [
                    _example_from_messages(ex["messages"])
                    for ex in val_rows
                ]
                manifest["old_val_rows"] = kept[-MAX_OLD_VAL_ROWS:]
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
        # v0.36.0 (N27): the dream outcome, when the report has one.
        "dream": report.get("dream"),
        "old_loss_before": report.get("old_loss_before"),
        "old_loss_after": report.get("old_loss_after"),
        "new_loss": report.get("new_loss"),
        "steps": report.get("steps", 0),
    }


def list_sleep_cycles(store: Store, profile: str, project: str) -> list[dict]:
    """Per-cycle summaries, oldest first (from the manifest).

    Each entry carries `size_bytes` (R66): the cycle folder's
    disk use, computed live from the files on disk — the stored
    summary has no size, so a stored number would go stale the
    moment a file changed.
    """
    sdir = sleep_dir(store, profile, project)
    out = []
    for cycle in load_sleep_manifest(store, profile, project)["cycles"]:
        entry = dict(cycle)
        entry["size_bytes"] = _dir_size_bytes(
            sdir / f"cycle-{cycle.get('cycle', 0)}"
        )
        out.append(entry)
    return out


def delete_sleep_cycle(
    store: Store, profile: str, project: str, cycle: int
) -> dict:
    """Delete one sleep cycle, permanently (R66).

    Mirrors delete_checkpoint (T150): the point is freeing disk,
    so there is no trash here — the caller confirms first (the
    window asks, showing the size, defaulting to No). Removes
    the whole cycle folder AND the manifest entry, so the
    orphan-heal cannot resurrect it; a cycle with a report but
    no manifest entry (unhealed) deletes the same way. The
    slept-row hashes stay: deleting the adapter does not
    un-sleep the rows, so they must not sleep again. Refuses
    while a job holds the home's lock — a merge may be reading
    the cycle's adapter. Returns the cycle and the bytes freed.
    Raises StellaError when the cycle does not exist.
    """
    store.get_profile(profile)
    store.get_project(profile, project)
    if job_lock_held(store.home):
        raise StellaError(
            f"cannot delete sleep cycle {cycle} while a job is "
            "running. Wait for it to finish, then try again"
        )
    sdir = sleep_dir(store, profile, project)
    cdir = sdir / f"cycle-{cycle}"
    manifest = load_sleep_manifest(store, profile, project)
    known = any(
        c.get("cycle") == cycle
        for c in manifest["cycles"]
        if isinstance(c, dict)
    )
    if not cdir.is_dir() and not known:
        raise StellaError(
            f"no sleep cycle {cycle} for project {project!r}"
        )
    freed = _dir_size_bytes(cdir) if cdir.is_dir() else 0
    if cdir.is_dir():
        shutil.rmtree(cdir)
    if known:
        manifest["cycles"] = [
            c
            for c in manifest["cycles"]
            if not (isinstance(c, dict) and c.get("cycle") == cycle)
        ]
        save_sleep_manifest(store, profile, project, manifest)
    return {"cycle": int(cycle), "freed_bytes": freed}


def prune_sleep_cycles(
    store: Store, profile: str, project: str, keep: int = 3
) -> dict:
    """Delete all but the newest N sleep cycles (R66).

    Permanent, like delete_sleep_cycle — the caller confirms
    first, showing the size before and after. Returns the kept
    and deleted cycle numbers, the total size before and after,
    and the bytes freed. `keep` must be at least 1: pruning to
    zero would destroy every sleep adapter.
    """
    if keep < 1:
        raise StellaError(
            "pruning must keep at least 1 sleep cycle (the newest "
            "one holds the latest adapter)"
        )
    store.get_profile(profile)
    store.get_project(profile, project)
    if job_lock_held(store.home):
        raise StellaError(
            "cannot prune sleep cycles while a job is running. "
            "Wait for it to finish, then try again"
        )
    cycles = list_sleep_cycles(store, profile, project)
    total_before = sum(c.get("size_bytes") or 0 for c in cycles)
    kept = cycles[-keep:] if cycles else []
    doomed = cycles[:-keep] if len(cycles) > keep else []
    freed = 0
    deleted_numbers: list[int] = []
    for c in doomed:
        freed += c.get("size_bytes") or 0
        delete_sleep_cycle(store, profile, project, c["cycle"])
        deleted_numbers.append(c["cycle"])
    total_after = total_before - freed
    return {
        "kept": [c["cycle"] for c in kept],
        "deleted": deleted_numbers,
        "freed_bytes": freed,
        "total_before": total_before,
        "total_after": total_after,
    }


def list_sleep_adapters(store: Store, profile: str, project: str) -> list[int]:
    """Cycle numbers whose adapter can be exported (R3): the
    adapter dir exists and holds an adapter_config.json. A cycle
    whose training crashed before the adapter was written is not
    listed — there is nothing to export. Sorted oldest first."""
    sleep_dir = store.project_dir(profile, project) / "sleep"
    if not sleep_dir.is_dir():
        return []
    numbers = []
    for child in sleep_dir.iterdir():
        if not child.is_dir() or not child.name.startswith("cycle-"):
            continue
        try:
            number = int(child.name.split("-", 1)[1])
        except ValueError:
            continue
        if (child / "adapter" / "adapter_config.json").is_file():
            numbers.append(number)
    return sorted(numbers)


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
        "nothing else: no intro, no numbering, no markdown.\n"
        "Real examples:\n"
        f"{seed_lines}\n"
        "New examples:\n"
    )


def _ollama_generate(
    model_tag: str,
    prompt: str,
    url: str | None,
    timeout: float,
    silence_timeout: float = DREAM_SILENCE_SECONDS,
) -> str:
    """One streaming /api/generate call (R126). Raises on any
    failure — the caller turns every failure into 'dreaming
    skipped'.

    Two budgets: `timeout` is the total generation budget (a slow
    CPU model may use all of it), and `silence_timeout` is the
    give-up on a dead peer — the socket timeout applies per read,
    so a peer that sends nothing for that long raises while a
    streaming model keeps going. The wall-clock deadline is
    checked after every chunk, so a peer dribbling one chunk per
    silence window still cannot outlive the total budget. A
    single non-streaming JSON object parses as one chunk, so a
    server that answers all at once still works.
    """
    from .ollama import ollama_url

    base = (url or ollama_url()).rstrip("/")
    payload = json.dumps(
        {
            "model": model_tag,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": 0.8, "num_predict": 2048},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    deadline = time.monotonic() + timeout
    parts: list[str] = []
    with urllib.request.urlopen(req, timeout=silence_timeout) as resp:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "dreaming took longer than the "
                    f"{timeout:g}s generation budget"
                )
            line = resp.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(chunk, dict):
                continue
            piece = chunk.get("response")
            if isinstance(piece, str):
                parts.append(piece)
            if chunk.get("done"):
                break
    text = "".join(parts)
    if not text:
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
    silence_timeout: float = DREAM_SILENCE_SECONDS,
) -> tuple[list[dict], str | None]:
    """Ask the local Ollama model for synthetic practice examples.

    Returns (rows, skipped_reason). `skipped_reason` is None when
    dreaming ran and kept at least one row; on ANY failure it names
    the reason and rows holds what survived (possibly empty).
    Dreaming never raises — a failed dream is a skipped dream, and
    sleep still runs on real rows. v0.36.0 (N27): when the model
    answered but no row survived validation, the reason says so
    (it opens with "Dreaming ran, but") instead of reading as a
    clean run that happened to keep nothing.

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
            model_tag, _dream_prompt(seeds[:3], count), ollama_url,
            timeout, silence_timeout=silence_timeout,
        )
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        return [], f"Ollama unreachable ({exc}). Dreaming skipped"
    kept: list[dict] = []
    seen = set(exclude_hashes)
    unusable = 0
    duplicates = 0
    for line_no, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            unusable += 1
            continue
        try:
            _fmt, messages = validate_dataset_row(row, line_no)
        except StellaError:
            unusable += 1
            continue
        example = _example_from_messages(messages)
        h = row_hash(example)
        if h in seen:
            duplicates += 1
            continue
        seen.add(h)
        kept.append(example)
        if len(kept) >= count:
            break
    if kept:
        return kept, None
    # v0.36.0 (N27): the model answered but nothing survived —
    # that is not the same as a dream that ran clean, and it is
    # not a skip either. Say which it was, so the user who asked
    # for dreamed rows learns the output was unusable (or all
    # repeats), never a silent zero. The note opens with
    # "Dreaming ran, but" so the caller can tell it apart from a
    # skipped dream.
    if unusable and duplicates:
        return [], (
            "Dreaming ran, but none of the model's answers could "
            f"be used: {unusable} were not readable training "
            f"examples and {duplicates} repeated rows Stella "
            "already has, so no rows were added."
        )
    if unusable:
        return [], (
            "Dreaming ran, but none of the model's answers could "
            f"be used: {unusable} were not readable training "
            "examples, so no rows were added."
        )
    if duplicates:
        return [], (
            "Dreaming ran, but every example it made repeated a "
            "row Stella already has, so no rows were added."
        )
    return [], (
        "Dreaming ran, but the model answered with nothing that "
        "could be used, so no rows were added."
    )


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

    # v0.36.0 (N29): the replay check loads the base — check it
    # fits the RAM free right now before the load, from metadata
    # only. A test loader skips it, like the training guards do.
    if _model_loader is None:
        from .train import check_base_load_fit

        check_base_load_fit(base_ref, "The replay check")

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
        # v0.36.0 (N27): the dream outcome was saved with the
        # cycle's input, so a resumed cycle's report still says
        # what dreaming did in the first attempt.
        dream_outcome = cycle_input.get("dream")
        if not isinstance(dream_outcome, dict):
            dream_outcome = {
                "ran": False,
                "kept": dreamed_count,
                "reason": None,
                "requested": dreamed_count,
            }
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
                # R15: this error reaches CLI users too, and there
                # is no GUI panel in front of them — name the CLI
                # way, with the full command (the old tail was
                # truncated at "--rows").
                raise StellaError(
                    f"project {project!r} has no dataset set. Pass "
                    "--rows with a .jsonl file of examples, for "
                    "example: stella "
                    f"sleep {profile} {project} --rows my-data.jsonl"
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
        # v0.36.0 (N27): the cycle's dream outcome, saved into
        # cycle_input.json and the final report — a skipped or
        # empty dream must stay visible after the live events are
        # gone, in the report the user can reopen.
        dream_outcome = {
            "ran": False,
            "kept": 0,
            "reason": None,
            "requested": 0,
        }
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
            if dream_note is not None and dream_note.startswith(
                "Dreaming ran, but"
            ):
                # The model answered; nothing it made was usable.
                dream_outcome = {
                    "ran": True,
                    "kept": 0,
                    "reason": dream_note,
                    "requested": want,
                }
                emit(
                    {
                        "type": "dream",
                        "requested": want,
                        "kept": 0,
                        "note": dream_note,
                    }
                )
            elif dream_note is not None:
                dream_outcome = {
                    "ran": False,
                    "kept": 0,
                    "reason": dream_note,
                    "requested": want,
                }
                emit({"type": "dream_skipped", "reason": dream_note})
            else:
                dream_outcome = {
                    "ran": True,
                    "kept": len(dreamed_rows),
                    "reason": None,
                    "requested": want,
                }
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
        # R8: unhealed cycles still occupy their number — the
        # orphan dir (and its adapter) must never be overwritten
        # by a fresh cycle reusing the number.
        known_numbers = [c.get("cycle", 0) for c in manifest["cycles"]]
        known_numbers += [
            u.get("cycle", 0)
            for u in manifest.get("unhealed_cycles", [])
        ]
        cycle_no = max(known_numbers, default=0) + 1
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
                # v0.36.0 (N27): the dream outcome rides with the
                # input, so a resumed cycle reports it too.
                "dream": dream_outcome,
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

    # v0.35.0 (N17): the real checkpoint list decides, not the
    # folder contents. A crashed save leaves a step-N.tmp folder
    # behind; the list ignores those, so a cycle whose only
    # checkpoint folder is a leftover tmp restarts its training
    # instead of resuming from nothing and refusing forever.
    from .train import list_checkpoints

    has_checkpoints = bool(
        list_checkpoints(
            store, profile, project,
            ckpt_dir=cycle_dir / "checkpoints",
        )
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
                "dream": dream_outcome,
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
            # v0.36.0 (N27): what dreaming did this cycle — ran,
            # skipped (with the reason), or ran and kept nothing
            # usable (with the reason) — in the saved report.
            "dream": dream_outcome,
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
    # R66: per-cycle sizes (live from disk, via list_sleep_cycles)
    # plus the total, so the CLI and the window can show what
    # sleep costs.
    cycles = list_sleep_cycles(store, profile, project)
    return {
        "profile": profile,
        "project": project,
        "cycles": cycles,
        "unhealed_cycles": manifest.get("unhealed_cycles", []),
        "slept_rows": len(slept),
        "dreamed_rows": len(manifest["dreamed_hashes"]),
        "old_val_rows": len(manifest["old_val_rows"]),
        "total_rows": total,
        "unslept_rows": unslept,
        "total_size_bytes": sum(c.get("size_bytes") or 0 for c in cycles),
    }
