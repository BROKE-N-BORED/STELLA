"""STELLA re-quantize — make an installed Ollama model smaller.

Every model Ollama runs is already a GGUF file, so there is nothing
to convert. What this does is re-quantize one to a smaller size:
the same weights, packed tighter. A Q8_0 model at 2.7 GB becomes a
Q4_K_M model around 1.8 GB, and it runs faster because there is less
to read from memory.

The original model is NEVER touched: the smaller copy is a new file
and a new Ollama tag, made with llama.cpp's llama-quantize, then
registered with `ollama create`. Re-quantizing an already-quantized
model loses a little quality (the weights are rounded twice), so the
result is a touch less sharp than the original. That is the trade
for the size and speed.

Needs llama.cpp (for llama-quantize) and Ollama (for `ollama create`).
Both are checked up front, with plain-words errors naming the fix.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

from .gguf import LLAMA_CPP_HINT, write_modelfile
from .model import StellaError, default_home
from .ollama import list_models

DEFAULT_QUANT = "Q4_K_M"

# Quant types llama-quantize accepts (llama.cpp). Anything else is
# rejected up front, never passed through to the tool.
KNOWN_QUANTS = (
    "F32", "F16", "BF16",
    "Q8_0", "Q8_K",
    "Q6_K",
    "Q5_0", "Q5_1", "Q5_K", "Q5_K_S", "Q5_K_M",
    "Q4_0", "Q4_1", "Q4_K", "Q4_K_S", "Q4_K_M",
    "Q3_K", "Q3_K_S", "Q3_K_M", "Q3_K_L",
    "Q2_K",
    "IQ4_NL", "IQ4_XS", "IQ3_S", "IQ3_XXS", "IQ2_S", "IQ2_XS",
    "IQ2_XXS", "IQ1_S", "IQ1_M",
    "I8", "I16", "I32",
    "TQ1_0", "TQ2_0",
)

# Bits per weight, roughly, for the disk estimate (includes the
# per-block scales). Used to guess how big the output will be.
_QUANT_BPW = {
    "F32": 32.0, "F16": 16.0, "BF16": 16.0,
    "Q8_0": 8.5, "Q8_K": 8.5, "Q6_K": 6.6,
    "Q5_0": 5.5, "Q5_1": 5.5, "Q5_K": 5.5, "Q5_K_S": 5.5, "Q5_K_M": 5.5,
    "Q4_0": 4.5, "Q4_1": 4.5, "Q4_K": 4.85, "Q4_K_S": 4.85, "Q4_K_M": 4.85,
    "Q3_K": 3.9, "Q3_K_S": 3.9, "Q3_K_M": 3.9, "Q3_K_L": 3.9,
    "Q2_K": 3.35,
    "IQ4_NL": 4.5, "IQ4_XS": 4.25, "IQ3_S": 3.44, "IQ3_XXS": 3.06,
    "IQ2_S": 2.5, "IQ2_XS": 2.31, "IQ2_XXS": 2.06,
    "IQ1_S": 1.56, "IQ1_M": 1.75,
    "I8": 8.0, "I16": 16.0, "I32": 32.0,
    "TQ1_0": 1.69, "TQ2_0": 2.06,
}

# GGUF tensor type ids (the type of each weight block in the file).
_TENSOR_TYPE_QUANT = {
    0: ("F32", 32.0), 1: ("F16", 16.0), 2: ("Q4_0", 4.5),
    3: ("Q4_1", 4.5), 6: ("Q5_0", 5.5), 7: ("Q5_1", 5.5),
    8: ("Q8_0", 8.5), 9: ("Q2_K", 3.35), 10: ("Q3_K", 3.9),
    11: ("Q4_K", 4.85), 12: ("Q5_K", 5.5), 13: ("Q6_K", 6.6),
    14: ("Q8_K", 8.5), 15: ("IQ2_XXS", 2.06), 16: ("IQ2_XS", 2.31),
    17: ("IQ3_XXS", 3.06), 18: ("IQ1_S", 1.56), 19: ("IQ4_NL", 4.5),
    20: ("IQ3_S", 3.44), 21: ("IQ2_S", 2.5), 22: ("IQ4_XS", 4.25),
    24: ("I8", 8.0), 25: ("I16", 16.0), 26: ("I32", 32.0),
    29: ("IQ1_M", 1.75), 30: ("BF16", 16.0),
    31: ("Q4_0", 4.5), 32: ("Q4_0", 4.5), 33: ("Q4_0", 4.5),
    34: ("TQ1_0", 1.69), 35: ("TQ2_0", 2.06),
}

# Ollama's own layout: manifests name the model, blobs hold the bytes.
MODEL_MEDIA_TYPE = "application/vnd.ollama.image.model"
DEFAULT_REGISTRY = "registry.ollama.ai"

# Slack on top of the estimated output size for the disk check.
DISK_SLACK_BYTES = 10 * 1024 * 1024


def validate_quant(quant: str) -> str:
    """Normalize a quant name, or reject it in plain words."""
    name = (quant or "").strip().upper()
    if name not in KNOWN_QUANTS:
        raise StellaError(
            f"{quant!r} is not a quant type Stella knows. "
            f"Pick one of: {', '.join(KNOWN_QUANTS)}. "
            "Q4_K_M is the usual pick: small and still sharp."
        )
    return name


def ollama_models_dir() -> Path:
    """Where Ollama keeps its models (OLLAMA_MODELS wins)."""
    env = os.environ.get("OLLAMA_MODELS")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".ollama" / "models"


def _split_tag(tag: str) -> tuple[str, str, str]:
    """Split an Ollama tag into (registry, name, version).

    "qwen3.5:4b" -> ("registry.ollama.ai", "library/qwen3.5", "4b").
    "maternion/minicpm5-heretic:2b" -> ("registry.ollama.ai",
    "maternion/minicpm5-heretic", "2b"). No version means "latest".
    """
    tag = tag.strip()
    if ":" in tag.rsplit("/", 1)[-1]:
        name, _, version = tag.rpartition(":")
    else:
        name, version = tag, "latest"
    parts = name.split("/")
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0]
                           or parts[0] == "localhost"):
        registry, rest = parts[0], "/".join(parts[1:])
    else:
        registry, rest = DEFAULT_REGISTRY, name
    if "/" not in rest:
        rest = "library/" + rest
    return registry, rest, version


def _manifest_blob(tag: str, models_dir: Path) -> Path | None:
    """Find the GGUF blob for a tag via its Ollama manifest."""
    registry, name, version = _split_tag(tag)
    manifest = models_dir / "manifests" / registry / name / version
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, list):
        return None
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        if layer.get("mediaType") != MODEL_MEDIA_TYPE:
            continue
        digest = layer.get("digest") or ""
        if not digest.startswith("sha256:"):
            continue
        blob = models_dir / "blobs" / digest.replace(":", "-", 1)
        if blob.is_file():
            return blob
    return None


def _modelfile_blob(tag: str) -> Path | None:
    """Fallback: `ollama show <tag> --modelfile` names the blob file."""
    ollama = shutil.which("ollama")
    if ollama is None:
        return None
    try:
        proc = subprocess.run(
            [ollama, "show", tag, "--modelfile"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.strip().upper().startswith("FROM "):
            candidate = Path(line.split(None, 1)[1].strip())
            if candidate.is_file():
                return candidate
    return None


def _read_gguf_source_quant(path: Path) -> tuple[str | None, float | None]:
    """Best-effort read of a GGUF file's own quant type.

    Parses just the header: magic, counts, metadata (skipped), then
    the tensor list. Returns (quant name, bits per weight) for the
    most common tensor type, or (None, None) when the header cannot
    be read. Never raises: a failed read just means the disk
    estimate falls back to a cautious guess.
    """
    _VALUE_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4,
                    7: 1, 10: 8, 11: 8, 12: 8}
    try:
        data = path.read_bytes()[:1 * 1024 * 1024]
    except OSError:
        return None, None
    if len(data) < 24 or data[:4] != b"GGUF":
        return None, None
    try:
        pos = 8  # magic + version
        tensor_count = struct.unpack_from("<Q", data, pos)[0]
        pos += 8
        kv_count = struct.unpack_from("<Q", data, pos)[0]
        pos += 8

        def read_string(buf, off):
            (length,) = struct.unpack_from("<Q", buf, off)
            off += 8
            return buf[off:off + length].decode("utf-8", "replace"), off + length

        def skip_value(buf, off, vtype):
            if vtype == 8:  # string
                _, off = read_string(buf, off)
                return off
            if vtype == 9:  # array: element type + count + elements
                etype = struct.unpack_from("<I", buf, off)[0]
                off += 4
                count = struct.unpack_from("<Q", buf, off)[0]
                off += 8
                for _ in range(count):
                    off = skip_value(buf, off, etype)
                return off
            return off + _VALUE_SIZES[vtype]

        for _ in range(kv_count):
            _, pos = read_string(data, pos)
            vtype = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            pos = skip_value(data, pos, vtype)

        counts: dict[int, int] = {}
        for _ in range(min(tensor_count, 10000)):
            _, pos = read_string(data, pos)
            n_dims = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + 8 * n_dims
            ttype = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + 8  # type + offset
            counts[ttype] = counts.get(ttype, 0) + 1
    except (struct.error, IndexError, KeyError, ValueError):
        return None, None
    if not counts:
        return None, None
    common = max(counts, key=counts.get)
    entry = _TENSOR_TYPE_QUANT.get(common)
    if entry is None:
        return None, None
    return entry


def resolve_model_blob(tag: str, models_dir: Path | None = None) -> Path:
    """Find the GGUF file for an installed Ollama tag.

    Manifest first, `ollama show --modelfile` as the fallback.
    Raises StellaError when the model is not installed or the file
    is not a GGUF file.
    """
    models_dir = Path(models_dir) if models_dir else ollama_models_dir()
    blob = _manifest_blob(tag, models_dir)
    if blob is None:
        blob = _modelfile_blob(tag)
    if blob is None:
        raise StellaError(
            f"Ollama does not have a model called {tag!r} installed "
            "on this PC. Check the tag, or pull the model first."
        )
    try:
        magic = blob.read_bytes()[:4]
    except OSError as exc:
        raise StellaError(
            f"Could not read the model file for {tag!r}: {exc}"
        ) from exc
    if magic != b"GGUF":
        raise StellaError(
            f"The file for {tag!r} is not a GGUF model file, so it "
            "cannot be re-quantized. It may be a different kind of "
            "model, or a broken download."
        )
    return blob


def find_llama_quantize() -> Path:
    """Locate the llama-quantize binary (llama.cpp or PATH).

    Same search as gguf.find_llama_cpp, but only the quantizer is
    needed here, so a missing converter is fine. The binary must be
    executable: a non-executable file is skipped, not reported as
    found.
    """
    candidates: list[Path] = []
    env_dir = os.environ.get("LLAMA_CPP_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.append(Path.home() / "llama.cpp")
    candidates.append(Path.cwd() / "llama.cpp")
    install_dir = Path(__file__).resolve().parent.parent
    candidates.append(install_dir / "llama.cpp")
    candidates.append(install_dir.parent / "llama.cpp")
    for d in candidates:
        for q in (d / "build" / "bin" / "llama-quantize", d / "llama-quantize"):
            if q.is_file() and os.access(q, os.X_OK):
                return q
    on_path = shutil.which("llama-quantize")
    if on_path:
        return Path(on_path)
    raise StellaError(
        "llama-quantize was not found, so Stella cannot shrink this "
        "model.\n" + LLAMA_CPP_HINT
    )


def default_new_tag(tag: str, quant: str) -> str:
    """Default name for the smaller copy: the old tag plus the quant.

    "matern/minicpm5-heretic:2b" + Q4_K_M ->
    "matern/minicpm5-heretic:2b-q4-k-m". A tag with no version gets
    one: "lfm3" + Q4_K_M -> "lfm3:q4-k-m".
    """
    suffix = "-" + quant.lower().replace("_", "-")
    tag = tag.strip()
    if ":" in tag.rsplit("/", 1)[-1]:
        return tag + suffix
    return tag + ":" + suffix.lstrip("-")


def validate_new_tag(tag: str) -> str:
    """Check a new Ollama tag: lowercase, no spaces, one version."""
    value = (tag or "").strip()
    if not value:
        raise StellaError("the new model name must not be empty")
    if value != value.lower() or " " in value or value.count(":") > 1:
        raise StellaError(
            f"{tag!r} is not a valid model name. Use lowercase "
            "letters, numbers, dashes, dots and slashes, with one "
            "optional :version at the end (like model:q4-k-m)."
        )
    return value


def _run(cmd: list[str], *, what: str, _runner=None,
         should_stop=None) -> None:
    """Run a command, or hand it to the injected fake (tests).

    `should_stop` (a no-arg callable, T74) cancels a long command:
    the process is polled and killed when the flag flips, so the
    job card's Cancel button stops the quantizer instead of
    waiting for it. A Ctrl+C kills the child too before re-raising.
    """
    if _runner is not None:
        _runner(cmd)
        return
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        tail = ((err or out) or "").strip().splitlines()[-5:]
        raise StellaError(
            f"{what} failed ({proc.returncode}).\n" + "\n".join(tail)
        )


def _format_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    return f"{n:,} bytes"


def requant_model(
    tag: str,
    *,
    quant: str = DEFAULT_QUANT,
    new_tag: str | None = None,
    work_dir: str | Path | None = None,
    on_event=None,
    should_stop=None,
    _runner=None,
    _models_dir: Path | None = None,
) -> dict:
    """Re-quantize an installed Ollama model and register the copy.

    Steps: resolve the installed GGUF blob, check llama-quantize
    and Ollama exist, check free disk, quantize into Stella's work
    folder, write a Modelfile, `ollama create` the new tag, clean
    up the work files (Ollama has its own copy by then). The
    original model is never written to. `should_stop` (a no-arg
    callable, T74) cancels between phases and kills a running
    quantizer subprocess.

    Returns a report: source tag + size + quant, new tag, quant,
    output size, and the `ollama run` command for the new model.
    """
    quant = validate_quant(quant)
    source = resolve_model_blob(tag, _models_dir)
    source_bytes = source.stat().st_size
    source_quant, source_bpw = _read_gguf_source_quant(source)

    new_tag = validate_new_tag(
        new_tag if new_tag else default_new_tag(tag, quant)
    )
    if new_tag == tag.strip():
        raise StellaError(
            f"The new name {new_tag!r} is the same as the original. "
            "Pick a different name with --as, so the original stays "
            "untouched."
        )
    try:
        installed = list_models()
    except Exception:  # list_models never raises; belt and braces
        installed = []
    if new_tag in installed:
        raise StellaError(
            f"Ollama already has a model called {new_tag!r}. Pick a "
            "different name with --as, so nothing gets overwritten."
        )

    quantize = find_llama_quantize()
    if shutil.which("ollama") is None:
        raise StellaError(
            "The ollama command was not found. Ollama must be "
            "installed to register the smaller model. Start Ollama "
            "and make sure the ollama command is on the PATH."
        )

    work = Path(work_dir) if work_dir else default_home() / "requant"
    work.mkdir(parents=True, exist_ok=True)
    safe = tag.strip().lower().replace("/", "-").replace(":", "-")
    out_path = work / f"{safe}-{quant.lower().replace('_', '-')}.gguf"
    if out_path.exists():
        out_path.unlink()

    # Disk check before writing: the output is roughly the source
    # size scaled by the bits per weight. Unknown source quant
    # assumes a cautious 3 bits per weight, so the estimate is an
    # upper bound.
    target_bpw = _QUANT_BPW[quant]
    ratio = target_bpw / (source_bpw or 3.0)
    estimate = max(int(source_bytes * ratio), source_bytes // 20)
    needed = estimate + DISK_SLACK_BYTES
    free = shutil.disk_usage(work).free
    if free < needed:
        raise StellaError(
            f"Not enough free disk to shrink {tag!r}. The smaller "
            f"model needs about {_format_size(needed)} free, and "
            f"this disk has {_format_size(free)} free. Free some "
            "space and try again."
        )

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    emit({
        "type": "found",
        "source_tag": tag,
        "source_bytes": source_bytes,
        "source_quant": source_quant,
        "quant": quant,
        "new_tag": new_tag,
    })
    if should_stop is not None and should_stop():
        raise StellaError("Cancelled.")
    _run(
        [str(quantize), str(source), str(out_path), quant],
        what=f"Shrinking {tag!r} to {quant}",
        _runner=_runner,
        should_stop=should_stop,
    )
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise StellaError(
            f"The quantizer finished but wrote no file for {tag!r}. "
            "Try again, and check the disk is not full."
        )
    out_bytes = out_path.stat().st_size
    emit({
        "type": "quantized",
        "source_bytes": source_bytes,
        "output_bytes": out_bytes,
        "quant": quant,
    })

    modelfile, _command = write_modelfile(
        out_path, work / "Modelfile", name=new_tag
    )
    if should_stop is not None and should_stop():
        raise StellaError("Cancelled.")
    try:
        _run(
            ["ollama", "create", new_tag, "-f", str(modelfile)],
            what=f"Registering the new model {new_tag!r} with Ollama",
            _runner=_runner,
            should_stop=should_stop,
        )
    except StellaError as exc:
        raise StellaError(
            f"{exc}\nThe smaller file is still at {out_path}. "
            "Is Ollama running? Start it and try again."
        ) from exc
    emit({"type": "created", "new_tag": new_tag})

    # Ollama copied the file into its own store, so the work files
    # can go. The original blob was never touched.
    try:
        out_path.unlink()
        modelfile.unlink()
    except OSError:
        pass
    return {
        "source_tag": tag,
        "source_bytes": source_bytes,
        "source_quant": source_quant,
        "new_tag": new_tag,
        "quant": quant,
        "output_bytes": out_bytes,
        "ollama_run": f"ollama run {new_tag}",
    }
