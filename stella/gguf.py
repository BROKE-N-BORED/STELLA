"""STELLA GGUF round-trip — adapter to Ollama model.

The second half of the proof loop: merge the trained LoRA adapter back
into the base, convert the merged HF weights to GGUF with llama.cpp,
quantize to Q4_K_M, and write an Ollama Modelfile so the tuned model
runs in Forge like any other Ollama model.

    adapter/ + base HF weights
        -> merged HF weights (bf16)
        -> model-f16.gguf (convert_hf_to_gguf.py)
        -> model-q4_k_m.gguf (llama-quantize)
        -> Modelfile + `ollama create <name> -f Modelfile`

llama.cpp is NOT bundled — it is a build tool the user installs once
(see LLAMA_CPP_HINT). If it is missing, every function here fails with
a clear error naming the fix, never silently and never with a fake
file. Tests inject a fake converter runner instead of llama.cpp.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

from .job_lock import job_lock
from .model import StellaError, Store
from .train import RAM_LIMIT_BYTES

DEFAULT_QUANT = "Q4_K_M"

# A hung converter/quantizer fails instead of hanging forever
# (T103): generous, a real 1.7B convert takes minutes.
SUBPROCESS_TIMEOUT_SECONDS = 30 * 60

# Headroom for the OS + Stella itself while a merge or a converter
# runs (T31). The training estimator uses the same shape.
RAM_HEADROOM_BYTES = 1 * 1024**3

LLAMA_CPP_HINT = (
    "llama.cpp was not found. Stella needs its converter + quantizer "
    "to make GGUF files. Install once:\n"
    "  git clone https://github.com/ggerganov/llama.cpp\n"
    "  cd llama.cpp\n"
    "  cmake -B build\n"
    "  cmake --build build -j\n"
    "Then either put that folder at ~/llama.cpp, or set LLAMA_CPP_DIR "
    "to it before running Stella."
)


def find_llama_cpp() -> tuple[Path, Path]:
    """Locate (convert_hf_to_gguf.py, llama-quantize binary).

    Searches LLAMA_CPP_DIR, ~/llama.cpp, ./llama.cpp, and the Stella
    folder's neighbours, plus PATH for the quantize binary. Raises
    StellaError with the install hint when anything is missing.
    """
    import os

    candidates: list[Path] = []
    env_dir = os.environ.get("LLAMA_CPP_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.append(Path.home() / "llama.cpp")
    candidates.append(Path.cwd() / "llama.cpp")
    # Next to the Stella install folder, and inside it.
    install_dir = Path(__file__).resolve().parent.parent
    candidates.append(install_dir / "llama.cpp")
    candidates.append(install_dir.parent / "llama.cpp")

    convert = None
    quantize = None
    not_executable = None
    for d in candidates:
        if convert is None and (d / "convert_hf_to_gguf.py").is_file():
            convert = d / "convert_hf_to_gguf.py"
        for q in (d / "build" / "bin" / "llama-quantize", d / "llama-quantize"):
            if quantize is None and q.is_file():
                # The quantizer must be executable, not just present
                # (T102): a chmod-644 binary is "found" and then dies
                # as a raw PermissionError from subprocess. Record
                # the first non-executable one so the error can name it.
                if os.access(q, os.X_OK):
                    quantize = q
                elif not_executable is None:
                    not_executable = q
        if convert is not None and quantize is not None:
            break
    if quantize is None:
        on_path = shutil.which("llama-quantize")
        if on_path:
            quantize = Path(on_path)
    missing = []
    if convert is None:
        missing.append("convert_hf_to_gguf.py")
    if quantize is None:
        if not_executable is not None:
            raise StellaError(
                f"llama-quantize at {not_executable} is not executable. "
                "Fix it with:\n"
                f"  chmod +x {not_executable}\n"
                "or rebuild llama.cpp (cmake --build build -j)."
            )
        missing.append("llama-quantize")
    if missing:
        raise StellaError(
            f"llama.cpp is incomplete: missing {', '.join(missing)}.\n"
            + LLAMA_CPP_HINT
        )
    return convert, quantize


def converter_supported_archs(convert_path: str | Path) -> set[str] | None:
    """The architectures the installed converter supports (T97),
    read from the converter's own registrations: modern
    convert_hf_to_gguf.py registers each model class with
    @Model.register("LlamaForCausalLM"). None when the script
    carries no registrations (an old converter, or one whose
    format changed) — the check cannot be made, so it does not
    refuse on a guess."""
    import re

    try:
        text = Path(convert_path).read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return None
    found = set(
        re.findall(
            r"@Model\.register\(\s*[\"']([^\"']+)[\"']\s*\)", text
        )
    )
    return found or None


def check_converter_supports_arch(
    arch: str, convert_path: str | Path
) -> None:
    """Refuse (T97) when the installed converter does not support
    the base model's architecture — before the merge, not after
    it. The arch and the converter are both named. When the
    converter's list cannot be read, the check passes: the
    converter itself will fail loudly if the arch is unsupported."""
    supported = converter_supported_archs(convert_path)
    if supported is None:
        return
    if arch not in supported:
        raise StellaError(
            f"the converter at {convert_path} does not support the "
            f"{arch} architecture, so this base model cannot be "
            "exported to GGUF with it. Update llama.cpp to one that "
            "supports it, or export from a supported base model."
        )


def _gb(n: int) -> str:
    """Bytes as 'x.xx GB', matching the training guard's format."""
    return f"{n / 1024**3:.2f} GB"


def estimate_merge_bytes(base_bytes: int) -> int:
    """RAM for the merge (T31): the base weights + the merged copy
    + headroom for the OS and Stella itself. Conservative on
    purpose — the merge runs after hours of training, so the
    estimate errs towards refusing rather than OOMing."""
    return base_bytes * 2 + RAM_HEADROOM_BYTES


def check_merge_fit(
    base_bytes: int, limit_bytes: int = RAM_LIMIT_BYTES
) -> None:
    """Refuse the merge when base + merged copy + headroom does
    not fit the ceiling. The estimate is named in the message."""
    estimate = estimate_merge_bytes(base_bytes)
    if estimate > limit_bytes:
        raise StellaError(
            f"Merging needs about {_gb(estimate)} of RAM (the base "
            f"model at {_gb(base_bytes)}, plus the merged copy, plus "
            f"headroom), over the {_gb(limit_bytes)} ceiling on this "
            "PC.\n"
            "Export on a machine with more RAM, or use a smaller "
            "base model."
        )


def merge_warnings(
    base_bytes: int, limit_bytes: int = RAM_LIMIT_BYTES
) -> list[str]:
    """Warnings for an export that fits the merge guard but is
    tight (T31). The converter loads the merged model again as a
    separate process, while Stella's merge memory may still be
    resident — when merge + converter together pass the ceiling,
    the export proceeds but the user is told to close other apps
    first. Empty when the merge itself does not fit: the guard
    refuses then, and no warning is needed on top."""
    if estimate_merge_bytes(base_bytes) > limit_bytes:
        return []
    total = (
        estimate_merge_bytes(base_bytes)
        + base_bytes
        + RAM_HEADROOM_BYTES
    )
    if total <= limit_bytes:
        return []
    return [
        f"Close other apps before exporting: the merge needs about "
        f"{_gb(estimate_merge_bytes(base_bytes))} of RAM, and the "
        f"converter then loads the model again as a separate "
        f"process (about {_gb(base_bytes + RAM_HEADROOM_BYTES)}). "
        f"Together that is over the {_gb(limit_bytes)} on this PC, "
        "so the export is tight on RAM."
    ]


def merge_adapter(
    base_ref: str,
    adapter_dir: str | Path,
    out_dir: str | Path,
    *,
    _model_loader=None,
    _dtype: str = "bfloat16",
    _base_bytes: int | None = None,
    on_event=None,
) -> Path:
    """Merge a LoRA adapter into its base and save HF weights.

    `_model_loader` is a test hook: (base_ref, adapter_dir) -> model,
    so tests can merge a tiny model with no downloads. `_base_bytes`
    is a test hook for the merge guard: the base size in bytes,
    used instead of reading the model's metadata. `on_event`
    (T152) gets a loading event before the base loads, naming the
    model — the merge is minutes of silence otherwise.
    """
    from .train import load_base_model, require_training_deps

    adapter_dir = Path(adapter_dir)
    out_dir = Path(out_dir)
    if not (adapter_dir / "adapter_config.json").is_file():
        raise StellaError(f"no adapter in {adapter_dir}")
    # The merge guard (T31): base + merged copy + headroom, from
    # the model's metadata — before loading anything, and before
    # the training deps are even required, so a model that cannot
    # fit is refused on any machine. A test loader skips it (the
    # test controls its own fake world).
    if _model_loader is None:
        if _base_bytes is None:
            from .train import load_model_metadata

            _base_bytes = load_model_metadata(base_ref)["base_bytes"]
        check_merge_fit(_base_bytes)
    require_training_deps()
    if on_event is not None:
        on_event({
            "type": "loading",
            "model": base_ref,
            "message": (
                f"Loading {base_ref} to merge the adapter..."
            ),
        })
    if _model_loader is not None:
        model, tokenizer = _model_loader(base_ref, adapter_dir)
    else:
        from peft import PeftModel

        model, tokenizer = load_base_model(base_ref, dtype=_dtype)
        model = PeftModel.from_pretrained(model, str(adapter_dir))
    merged = model.merge_and_unload()
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(out_dir))
    tokenizer.save_pretrained(str(out_dir))
    return out_dir


# -- up-front export estimate (T153) -------------------------------
# The export button shows what the export will cost before the
# user commits — merged size, output size, rough time — from
# metadata only, the same no-load rule as the dry-run estimate
# (T85). The merged weights are a full copy of the base; the
# GGUF size is params x bits-per-weight for the quant.


def _export_time_note(merged_bytes: int) -> str:
    """A rough time band for an export, in plain words (T153).

    Orders of magnitude, not a promise: merge + convert +
    quantize on this PC runs minutes for a small base, tens of
    minutes for a 1.7B one, longer for anything bigger. The
    label says "roughly" so nobody reads it as a schedule."""
    if merged_bytes < 1 * 1024**3:
        return "roughly minutes"
    if merged_bytes < 4 * 1024**3:
        return "roughly tens of minutes"
    return "roughly an hour or more"


def estimate_export(
    store: Store,
    profile: str,
    project: str,
    *,
    quant: str = DEFAULT_QUANT,
) -> dict:
    """The export estimate (T153), from metadata only.

    Merged size, output GGUF size, the disk the export needs
    (both at once — the merged weights stay on disk after a
    successful export), and a rough time band. Raises StellaError
    when the answer cannot be found out (no trained adapter, no
    base ref, unreadable model metadata) — the caller reports it
    plainly instead of guessing.

    Returns: merged_bytes, gguf_bytes, disk_bytes, time_note,
    quant, params, base_bytes.
    """
    from .requant import bits_per_weight, validate_quant
    from .train import LFM3_HF_REPO, load_model_metadata

    quant = validate_quant(quant)
    prof = store.get_profile(profile)
    store.get_project(profile, project)
    project_dir = store.project_dir(profile, project)
    if not (project_dir / "adapter" / "adapter_config.json").is_file():
        raise StellaError(
            f"project {project!r} has no trained adapter yet. "
            "run training first, then export"
        )
    base_ref = prof.get("base_ref") or ""
    if not base_ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    meta = load_model_metadata(base_ref)
    merged_bytes = meta["base_bytes"]
    gguf_bytes = int(meta["params"] * bits_per_weight(quant) / 8)
    return {
        "merged_bytes": merged_bytes,
        "gguf_bytes": gguf_bytes,
        "disk_bytes": merged_bytes + gguf_bytes,
        "time_note": _export_time_note(merged_bytes),
        "quant": quant,
        "params": meta["params"],
        "base_bytes": meta["base_bytes"],
    }


def _fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    return f"{n:,} bytes"


def format_export_estimate(estimate: dict) -> str:
    """The one-line export estimate for the button label (T153):
    merged size, output size, rough time — no settings (T16)."""
    return (
        f"Export merges about {_fmt_size(estimate['merged_bytes'])}, "
        f"then writes about a {_fmt_size(estimate['gguf_bytes'])} "
        f"GGUF file ({estimate['quant']}). "
        f"{estimate['time_note'].capitalize()}."
    )


def _timeout_text(seconds: float) -> str:
    """A timeout as plain words ("30 minutes", "5 seconds")."""
    if seconds >= 60:
        return f"{seconds / 60:.0f} minutes"
    return f"{seconds:g} seconds"


def _run(
    cmd: list[str],
    *,
    _runner=None,
    should_stop=None,
    timeout: float | None = None,
    step: str = "converter",
) -> None:
    """Run a converter command, or hand it to the injected fake.

    `should_stop` (a no-arg callable, T74) cancels a long command:
    the process is polled and killed when the flag flips, so the
    job card's Cancel button stops the converter instead of
    waiting for it. A Ctrl+C kills the child too before re-raising.
    `timeout` (T103) bounds the wait: a hung converter is killed
    and fails with a StellaError naming the step, instead of
    hanging the export — and the GUI job, which has no cancel —
    forever.
    """
    if _runner is not None:
        _runner(cmd)
        return
    import time

    deadline = None if timeout is None else time.monotonic() + timeout
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace",  # converter output can
        # carry raw non-UTF-8 bytes (tokenizer vocab)
    )
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if should_stop is not None and should_stop():
                    proc.kill()
                    proc.wait()
                    raise StellaError("Cancelled.")
                if deadline is not None and time.monotonic() >= deadline:
                    proc.kill()
                    proc.wait()
                    raise StellaError(
                        f"the {step} timed out after "
                        f"{_timeout_text(timeout)}. The export was "
                        "stopped. Try again, or check the llama.cpp "
                        "install."
                    )
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        from .tool_errors import translate_tool_error

        raise StellaError(
            translate_tool_error(
                (err or out) or "",
                what=f"the {step}",
                code=proc.returncode,
            )
        )


def convert_to_gguf(
    hf_dir: str | Path,
    out_path: str | Path,
    *,
    quant: str = DEFAULT_QUANT,
    llama_cpp: tuple[Path, Path] | None = None,
    on_event=None,
    should_stop=None,
    _runner=None,
) -> dict:
    """Convert merged HF weights to a quantized GGUF file.

    Two steps, the classic reliable path: convert to F16 GGUF, then
    quantize. Returns {"gguf": path, "quant": quant, "bytes": size}.
    `on_event` (T74) gets a phase event before each step; `should_stop`
    (a no-arg callable) cancels between steps and kills a running
    converter subprocess.
    """
    import sys

    # Validate the quant up front (T27), reusing the requant
    # validator — a bogus quant fails here in a millisecond, not at
    # the end of the pipeline. (Imported here: requant imports this
    # module, so a top-level import would be circular.)
    from .requant import validate_quant

    quant = validate_quant(quant)
    hf_dir = Path(hf_dir)
    out_path = Path(out_path)
    if not (hf_dir / "config.json").is_file():
        raise StellaError(f"no HF model in {hf_dir} (missing config.json)")
    if llama_cpp is None:
        if _runner is None:
            llama_cpp = find_llama_cpp()
        else:
            llama_cpp = (Path("convert_hf_to_gguf.py"), Path("llama-quantize"))
    convert, quantize = llama_cpp
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_f16 = out_path.parent / (out_path.stem + "-f16.gguf")

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    def cancelled() -> bool:
        return should_stop is not None and should_stop()

    try:
        if cancelled():
            raise StellaError("Cancelled.")
        emit({
            "type": "phase", "phase": "convert",
            "message": "Converting the merged model to GGUF...",
        })
        _run(
            [
                sys.executable, str(convert), str(hf_dir),
                "--outfile", str(tmp_f16), "--outtype", "f16",
            ],
            _runner=_runner,
            should_stop=should_stop,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            step="GGUF converter",
        )
        if _runner is None and not tmp_f16.is_file():
            raise StellaError(
                f"converter finished but wrote no file: {tmp_f16}"
            )
        if cancelled():
            raise StellaError("Cancelled.")
        emit({
            "type": "phase", "phase": "quantize",
            "message": f"Quantizing to {quant}...",
        })
        _run(
            [str(quantize), str(tmp_f16), str(out_path), quant],
            _runner=_runner,
            should_stop=should_stop,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            step="quantizer",
        )
        if _runner is None and not out_path.is_file():
            raise StellaError(
                f"quantizer finished but wrote no file: {out_path}"
            )
    except StellaError as exc:
        # A failed quantize used to leave the F16 intermediate
        # behind — ~3.4 GB on a real model (T26). Remove it and say
        # so in the error.
        if tmp_f16.is_file():
            tmp_f16.unlink()
            raise StellaError(
                f"{exc} The half-finished F16 file was removed."
            ) from exc
        raise
    if tmp_f16.is_file() and _runner is None:
        tmp_f16.unlink()  # the F16 intermediate is 2x the size; drop it
    return {
        "gguf": str(out_path),
        "quant": quant,
        "bytes": out_path.stat().st_size if out_path.is_file() else 0,
    }


def create_in_ollama(
    name: str,
    modelfile: str | Path,
    *,
    should_stop=None,
    timeout: float | None = None,
    _runner=None,
) -> str:
    """Run `ollama create <name> -f <Modelfile>` (T89): the last
    step of the fine-tune loop, one click instead of a copy-paste
    into a terminal. Returns Ollama's output on success. A failed
    create raises StellaError with Ollama's own error, plainly —
    and a missing `ollama` binary says so instead of failing as a
    raw FileNotFoundError. `should_stop` cancels a long create
    (the process is killed); `timeout` bounds the wait like the
    converter timeout. `_runner` is the test hook: (cmd) -> output.
    """
    import time

    modelfile = Path(modelfile).expanduser()
    if not modelfile.is_file():
        raise StellaError(
            f"no Modelfile at {modelfile}. Export to GGUF again "
            "first."
        )
    cmd = ["ollama", "create", name, "-f", str(modelfile)]
    if _runner is not None:
        return _runner(cmd)
    if shutil.which("ollama") is None:
        raise StellaError(
            "Ollama is not installed, or not on PATH. Install it "
            "first, then create the model again."
        )
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace",
        )
    except OSError as exc:
        raise StellaError(f"could not run ollama: {exc}") from exc
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if should_stop is not None and should_stop():
                    proc.kill()
                    proc.wait()
                    raise StellaError("Cancelled.")
                if deadline is not None and time.monotonic() >= deadline:
                    proc.kill()
                    proc.wait()
                    raise StellaError(
                        "ollama create timed out after "
                        f"{_timeout_text(timeout)}. Try again."
                    )
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        from .tool_errors import translate_tool_error

        detail = ((err or out) or "").strip()
        raise StellaError(
            translate_tool_error(
                detail or "no error reported",
                what="ollama create",
                code=proc.returncode,
            )
        )
    return (out or "").strip()


def write_modelfile(
    gguf_path: str | Path,
    out_path: str | Path,
    *,
    name: str,
    system: str = "",
    template: str = "",
) -> tuple[Path, str]:
    """Write an Ollama Modelfile for a GGUF file.

    Returns (modelfile_path, ollama_create_command). The paths
    are shlex-quoted (T101): a spaced path used to split the
    printed command at the space, so the exact command Stella
    prints for copy-paste failed. shlex.quote leaves a plain
    path untouched, so unspaced exports read exactly as before.
    Whether Ollama's Modelfile parser accepts a quoted FROM is
    unprobed without Ollama — the shell-command fix is the
    certain half; the FROM line wants a real-Ollama check.
    """
    gguf_path = Path(gguf_path).expanduser().resolve()
    out_path = Path(out_path)
    lines = [f"FROM {shlex.quote(str(gguf_path))}"]
    if template:
        lines.append(f'TEMPLATE """{template}"""')
    if system:
        lines.append(f'SYSTEM """{system}"""')
    lines.append("PARAMETER temperature 0.7")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = f"ollama create {name} -f {shlex.quote(str(out_path))}"
    return out_path, command


def export_gguf(
    store: Store,
    profile: str,
    project: str,
    dest: str | Path,
    *,
    quant: str = DEFAULT_QUANT,
    from_checkpoint: int | None = None,
    llama_cpp: tuple[Path, Path] | None = None,
    on_warning=None,
    on_event=None,
    should_stop=None,
    force: bool = False,
    _runner=None,
    _model_loader=None,
    _dtype: str = "bfloat16",
    _base_arch: str | None = None,
) -> dict:
    """Full round-trip for one trained project.

    Merges the adapter (project adapter/, or checkpoints/step-N with
    --from-checkpoint), converts, quantizes, writes the Modelfile.
    Returns paths + the ollama create command. `on_warning` (a
    callable taking one string) is called up front, before the
    merge, with any converter warning (T31). `on_event` (T74) gets
    a phase event before each step; `should_stop` (a no-arg
    callable) cancels between phases and kills a running converter
    subprocess.

    Overwriting (T24 — the REFUSE pick): an existing GGUF at the
    output path refuses the export with a plain message naming
    --force, before the merge runs. The previous output cost a
    merge + convert + quantize to produce; it is never deleted
    silently. `force=True` overwrites deliberately.

    The conversion pre-flight (T97) runs before the merge too:
    the base's architecture (from its config, or `_base_arch`
    in tests) must be one the installed converter supports, or
    the export is refused naming the arch and the converter.
    """
    from .requant import validate_quant
    from .train import LFM3_HF_REPO

    # The quant is validated first (T27): a bogus value fails in a
    # millisecond, before the merge, the convert, or anything else.
    quant = validate_quant(quant)
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    project_dir = store.project_dir(profile, project)
    if from_checkpoint is not None:
        adapter_dir = project_dir / "checkpoints" / f"step-{from_checkpoint}"
        if not (adapter_dir / "adapter_config.json").is_file():
            raise StellaError(
                f"no checkpoint step-{from_checkpoint} for project "
                f"{project!r} (checkpoints hold the adapter)"
            )
    else:
        adapter_dir = project_dir / "adapter"
        if not (adapter_dir / "adapter_config.json").is_file():
            raise StellaError(
                f"project {project!r} has no trained adapter yet. "
                "run training first (stella train "
                f"{profile} {project})"
            )
    base_ref = prof.get("base_ref") or ""
    if not base_ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref. Set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    gguf_name = f"{project}-{quant.lower().replace('_', '-')}.gguf"
    gguf_path = dest / gguf_name
    # Refuse to overwrite (T24): the previous GGUF cost a merge +
    # convert + quantize to produce. Checked here, before the
    # merge — a refused export costs nothing and destroys nothing.
    if gguf_path.exists() and not force:
        raise StellaError(
            f"{gguf_path} already exists. Exporting again would "
            "overwrite it. Use --force to replace it deliberately, "
            "or export to a different folder."
        )
    merged_dir = dest / f"{project}-merged-hf"
    if merged_dir.exists():
        shutil.rmtree(merged_dir)
    # Check llama.cpp BEFORE the merge (T26): the check is cheap,
    # the merge is minutes. A missing install used to fail only
    # after the whole merge, leaving ~3.4 GB of merged weights
    # behind. (A test runner stands in for llama.cpp, so the check
    # is skipped when one is injected.)
    if llama_cpp is None and _runner is None:
        llama_cpp = find_llama_cpp()
    # The converter warning (T31), up front — before the merge:
    # the converter loads the model again as a separate process,
    # and on a tight export the user should close other apps
    # first. Skipped when the metadata cannot be read (a test fake
    # world): the merge guard raises its own error there. The same
    # metadata read feeds the architecture pre-flight (T97).
    meta = None
    if _model_loader is None:
        try:
            from .train import load_model_metadata

            meta = load_model_metadata(base_ref)
        except StellaError:
            meta = None
    warnings = merge_warnings(meta["base_bytes"]) if meta else []
    for warning in warnings:
        if on_warning is not None:
            on_warning(warning)
    # The conversion pre-flight (T97): confirm the base's
    # architecture is one the installed converter supports —
    # before the merge, not after it. The arch comes from the base
    # config (or the _base_arch test hook); when it cannot be
    # read, the check is skipped rather than guessed.
    base_arch = _base_arch
    if base_arch is None and meta is not None:
        archs = meta.get("architectures") or []
        base_arch = archs[0] if archs else None
    if base_arch is not None and llama_cpp is not None:
        check_converter_supports_arch(base_arch, llama_cpp[0])

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    def cancelled() -> bool:
        return should_stop is not None and should_stop()

    # One job at a time (T29): the merge loads the base and the
    # converter loads it again, so the whole export holds the
    # home's job lock. The cheap checks above ran without it.
    with job_lock(store.home, f"GGUF export {profile}/{project}"):
        try:
            if cancelled():
                raise StellaError("Cancelled.")
            emit({
                "type": "phase", "phase": "merge",
                "message": "Merging the adapter into the base model...",
            })
            merge_adapter(
                base_ref, adapter_dir, merged_dir,
                _model_loader=_model_loader, _dtype=_dtype,
                on_event=on_event,
            )
            if gguf_path.exists():
                # --force: the deliberate overwrite (T24).
                gguf_path.unlink()
            if cancelled():
                raise StellaError("Cancelled.")
            result = convert_to_gguf(
                merged_dir, gguf_path, quant=quant,
                llama_cpp=llama_cpp, _runner=_runner,
                on_event=on_event, should_stop=should_stop,
            )
        except StellaError as exc:
            # A failure after the merge leaves no orphaned merged
            # weights behind (T26): remove the merged dir and say so.
            if merged_dir.exists():
                shutil.rmtree(merged_dir)
                raise StellaError(
                    f"{exc} The half-finished merged weights were removed."
                ) from exc
            raise
        model_name = f"{profile}-{project}"
        _modelfile, command = write_modelfile(
            gguf_path, dest / "Modelfile", name=model_name
        )
        record = {
            "profile": profile,
            "project": project,
            "base_ref": base_ref,
            "adapter": str(adapter_dir),
            "merged_hf": str(merged_dir),
            "gguf": str(gguf_path),
            "quant": quant,
            "gguf_bytes": result["bytes"],
            "warnings": warnings,
            "ollama_name": model_name,
            "ollama_create": command,
            "modelfile": str(dest / "Modelfile"),
        }
        (dest / "gguf-export.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # The same record in the project dir (T89): the window's
        # "Create in Ollama" button reads it, so the last export's
        # Modelfile is one click away without re-picking a folder.
        (project_dir / "gguf-export.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        store.update_project(profile, project, status="exported")
        return {
            "merged_hf": str(merged_dir),
            "gguf": str(gguf_path),
            "quant": quant,
            "gguf_bytes": result["bytes"],
            "warnings": warnings,
            "modelfile": str(dest / "Modelfile"),
            "ollama_name": model_name,
            "ollama_create": command,
        }
