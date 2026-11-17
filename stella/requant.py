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
import re
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

# Ollama's projector layer: a manifest carrying one means the
# model sees pictures — its vision parts live in a blob of their
# own, which the requant path never touches (R5).
PROJECTOR_MEDIA_TYPE = "application/vnd.ollama.image.projector"

# GGUF architectures that can see pictures (general.architecture
# in the file's metadata). A model with one of these is a vision
# model, not a text model.
_VISION_GGUF_ARCHS = frozenset({
    "llava", "qwen2vl", "qwen2.5vl", "qwen3vl", "moondream2",
    "minicpmv", "mllama", "pixtral", "internvl", "llama4",
})

# Tensor-name markers for vision weights inside a GGUF file (the
# projector and the vision tower). No text model names a tensor
# this way.
_VISION_TENSOR_MARKERS = (
    "mmproj", "vision_tower", "vision_model",
    "multi_modal_projector",
)
DEFAULT_REGISTRY = "registry.ollama.ai"

# Slack on top of the estimated output size for the disk check.
DISK_SLACK_BYTES = 10 * 1024 * 1024

# A hung quantizer fails instead of hanging forever (R34): the
# same 30-minute bound export gives its converter (gguf.py).
SUBPROCESS_TIMEOUT_SECONDS = 30 * 60


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


def bits_per_weight(quant: str) -> float:
    """Bits per weight for a quant (T153): the disk estimate's
    input — how many bits each weight costs in the output file,
    per-block scales included. Validates first."""
    return _QUANT_BPW[validate_quant(quant)]


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
    quant holding the most BYTES in the file (R29: a count vote is
    a near-tie on real models, while the bytes are not), or
    (None, None) when the header cannot be read. Never raises: a
    failed read just means the disk estimate falls back to a
    cautious guess.

    The header is read by streaming, in 1 MB chunks, instead of
    truncating the file at 1 MB: a real Ollama GGUF blob's
    metadata alone is 7.85 MB (the tokenizer vocab arrays), so a
    1 MB cap dies mid-metadata and every real model reads as
    "unknown". Only the header is ever buffered — the weights are
    never read — and the buffer stops at 64 MB, past which the
    header is treated as unreadable.
    """
    _VALUE_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4,
                    7: 1, 10: 8, 11: 8, 12: 8}
    _CHUNK = 1 * 1024 * 1024
    _MAX_HEADER = 64 * 1024 * 1024
    try:
        handle = open(path, "rb")
    except OSError:
        return None, None
    buf = bytearray()
    pos = 0
    try:
        def need(count: int) -> None:
            """Grow the buffer until `count` bytes past `pos`
            are available, or raise EOFError."""
            nonlocal buf
            while len(buf) < pos + count:
                if len(buf) >= _MAX_HEADER:
                    raise EOFError("header over 64 MB")
                chunk = handle.read(
                    max(_CHUNK, pos + count - len(buf))
                )
                if not chunk:
                    raise EOFError("short file")
                buf += chunk

        def read_string() -> str:
            nonlocal pos
            need(8)
            (length,) = struct.unpack_from("<Q", buf, pos)
            pos += 8
            need(length)
            text = bytes(buf[pos:pos + length]).decode(
                "utf-8", "replace"
            )
            pos += length
            return text

        def skip_value(vtype: int) -> None:
            nonlocal pos
            if vtype == 8:  # string
                read_string()
                return
            if vtype == 9:  # array: element type + count + elements
                need(4)
                etype = struct.unpack_from("<I", buf, pos)[0]
                pos += 4
                need(8)
                count = struct.unpack_from("<Q", buf, pos)[0]
                pos += 8
                for _ in range(count):
                    skip_value(etype)
                return
            pos += _VALUE_SIZES[vtype]

        need(24)
        if len(buf) < 24 or bytes(buf[:4]) != b"GGUF":
            return None, None
        pos = 8  # magic + version
        need(8)
        tensor_count = struct.unpack_from("<Q", buf, pos)[0]
        pos += 8
        need(8)
        kv_count = struct.unpack_from("<Q", buf, pos)[0]
        pos += 8

        for _ in range(kv_count):
            read_string()
            need(4)
            vtype = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
            skip_value(vtype)

        # R29: the vote is weighted by BYTES, not by tensor count.
        # The real lfm3 blob is 136 Q5_K tensors vs 133 F32 — a
        # near-tie by count, while the F32s are tiny norms and
        # biases. One more norm family would have flipped the call
        # to F32, suppressing the double-quant warning and
        # collapsing the disk estimate. Each tensor's bytes are
        # elements x bits-per-weight, from the dims already parsed.
        type_bytes: dict[int, float] = {}
        for _ in range(min(tensor_count, 10000)):
            read_string()
            need(4)
            n_dims = struct.unpack_from("<I", buf, pos)[0]
            if n_dims > 8:
                # A tensor with more than 8 dims is not a tensor
                # list any more — the header is corrupt.
                return None, None
            pos += 4
            need(8 * n_dims)
            elements = 1
            for dim in struct.unpack_from(f"<{n_dims}Q", buf, pos):
                elements *= dim
            pos += 8 * n_dims
            need(4)
            ttype = struct.unpack_from("<I", buf, pos)[0]
            pos += 4 + 8  # type + offset
            entry = _TENSOR_TYPE_QUANT.get(ttype)
            if entry is not None:
                type_bytes[ttype] = (
                    type_bytes.get(ttype, 0.0)
                    + elements * entry[1] / 8.0
                )
    except (struct.error, IndexError, KeyError, ValueError, EOFError,
            OSError):
        return None, None
    finally:
        handle.close()
    if not type_bytes:
        return None, None
    common = max(type_bytes, key=type_bytes.get)
    entry = _TENSOR_TYPE_QUANT.get(common)
    if entry is None:
        return None, None
    return entry


def gguf_has_vision(path: Path) -> bool:
    """True when a GGUF file carries vision weights: a vision
    architecture in its `general.architecture` metadata, or
    projector / vision-tower tensors in its tensor list.

    Streams the header like `_read_gguf_source_quant` (1 MB
    chunks, 64 MB cap) and stops at the first marker — the
    weights are never read. False when the header cannot be
    read: an unreadable header is a corrupt file, and for an
    Ollama model the manifest check is the primary signal
    anyway (the projector lives in a blob of its own).
    """
    _VALUE_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4,
                    7: 1, 10: 8, 11: 8, 12: 8}
    _CHUNK = 1 * 1024 * 1024
    _MAX_HEADER = 64 * 1024 * 1024
    try:
        handle = open(path, "rb")
    except OSError:
        return False
    buf = bytearray()
    pos = 0
    try:
        def need(count: int) -> None:
            """Grow the buffer until `count` bytes past `pos`
            are available, or raise EOFError."""
            nonlocal buf
            while len(buf) < pos + count:
                if len(buf) >= _MAX_HEADER:
                    raise EOFError("header over 64 MB")
                chunk = handle.read(
                    max(_CHUNK, pos + count - len(buf))
                )
                if not chunk:
                    raise EOFError("short file")
                buf += chunk

        def read_string() -> str:
            nonlocal pos
            need(8)
            (length,) = struct.unpack_from("<Q", buf, pos)
            pos += 8
            need(length)
            text = bytes(buf[pos:pos + length]).decode(
                "utf-8", "replace"
            )
            pos += length
            return text

        def skip_value(vtype: int) -> None:
            nonlocal pos
            if vtype == 8:  # string
                read_string()
                return
            if vtype == 9:  # array: element type + count + elements
                need(4)
                etype = struct.unpack_from("<I", buf, pos)[0]
                pos += 4
                need(8)
                count = struct.unpack_from("<Q", buf, pos)[0]
                pos += 8
                for _ in range(count):
                    skip_value(etype)
                return
            pos += _VALUE_SIZES[vtype]

        need(24)
        if len(buf) < 24 or bytes(buf[:4]) != b"GGUF":
            return False
        pos = 8  # magic + version
        need(8)
        tensor_count = struct.unpack_from("<Q", buf, pos)[0]
        pos += 8
        need(8)
        kv_count = struct.unpack_from("<Q", buf, pos)[0]
        pos += 8

        for _ in range(kv_count):
            key = read_string()
            need(4)
            vtype = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
            if key == "general.architecture" and vtype == 8:
                if read_string().strip().lower() in _VISION_GGUF_ARCHS:
                    return True
            else:
                skip_value(vtype)

        for _ in range(min(tensor_count, 10000)):
            name = read_string().lower()
            if any(m in name for m in _VISION_TENSOR_MARKERS):
                return True
            need(4)
            n_dims = struct.unpack_from("<I", buf, pos)[0]
            pos += 4 + 8 * n_dims
            need(4)
            pos += 4 + 8  # type + offset
    except (struct.error, IndexError, KeyError, ValueError, EOFError,
            OSError):
        return False
    finally:
        handle.close()
    return False


def _manifest_has_projector(tag: str, models_dir: Path) -> bool:
    """True when the tag's Ollama manifest carries a projector
    layer — the model's vision parts, in a blob of their own.
    False when the manifest is missing or unreadable."""
    registry, name, version = _split_tag(tag)
    manifest = models_dir / "manifests" / registry / name / version
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, list):
        return False
    return any(
        isinstance(layer, dict)
        and layer.get("mediaType") == PROJECTOR_MEDIA_TYPE
        for layer in layers
    )


def model_is_vision(
    tag: str, blob: Path, models_dir: Path | None = None
) -> bool:
    """True when an installed model can see pictures: its Ollama
    manifest carries a projector layer, or its GGUF file carries
    vision weights. Both checks are cheap (a small JSON read, a
    streamed header scan) and run before any work starts."""
    models_dir = Path(models_dir) if models_dir else ollama_models_dir()
    if _manifest_has_projector(tag, models_dir):
        return True
    return gguf_has_vision(blob)


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
    # R6: read 4 bytes, not the file. The old read_bytes() pulled
    # the whole multi-GB blob into RAM for a 4-byte magic check
    # (1.05 GB peak for a 1.1 GB blob) — on an 8 GB PC, at the
    # start of a job that then runs a quantizer.
    try:
        with open(blob, "rb") as handle:
            magic = handle.read(4)
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
         should_stop=None, on_progress=None,
         _still_working_seconds: float = 30.0,
         timeout: float | None = SUBPROCESS_TIMEOUT_SECONDS) -> None:
    """Run a command, or hand it to the injected fake (tests).

    `should_stop` (a no-arg callable, T74) cancels a long command:
    the process is polled and killed when the flag flips, so the
    job card's Cancel button stops the quantizer instead of
    waiting for it. A Ctrl+C kills the child too before re-raising.
    `timeout` (R34) bounds the wait at 30 minutes by default,
    like export's converter: a hung quantizer is killed and fails
    with a plain-words message naming the timeout, instead of
    running forever.

    The child's output streams (S21): a reader thread hands each
    line to the main loop as it arrives, and per-tensor lines
    ("[ 12/ 287] ...", the format llama-quantize really prints,
    on stderr) become {"type": "quantize_progress", "done", "total"}
    events via `on_progress`, so the CLI/GUI never go quiet for
    minutes. When no parseable count has appeared for
    `_still_working_seconds` (30 by default), a {"type":
    "still_working"} event is emitted instead, at most once per
    interval. A failure is translated to plain words (S22) with
    the raw tail kept as a detail line.
    """
    if _runner is not None:
        _runner(cmd)
        return
    import queue
    import threading
    import time

    # llama-quantize prints its progress to stderr, not stdout,
    # so the streams are merged: one reader sees every line.
    # errors="replace": the metadata dump can carry raw
    # non-UTF-8 bytes (tokenizer vocab), which must not kill the
    # reader thread mid-run.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1,
    )
    lines: list[str] = []
    pending: queue.Queue = queue.Queue()
    _MISSING = object()

    def reader() -> None:
        try:
            for line in proc.stdout:
                lines.append(line)
                pending.put(line)
        except Exception:
            pass
        finally:
            pending.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    started = time.monotonic()
    deadline = None if timeout is None else started + timeout
    last_still_working = started
    saw_count = False
    last_done = -1
    try:
        while True:
            try:
                line = pending.get(timeout=0.2)
            except queue.Empty:
                line = _MISSING
            if line is None:  # the reader hit end of output
                break
            if line is not _MISSING:
                parsed = _parse_quantize_progress(line)
                if parsed is not None:
                    done, total = parsed
                    saw_count = True
                    if done != last_done and on_progress is not None:
                        last_done = done
                        on_progress({
                            "type": "quantize_progress",
                            "done": done,
                            "total": total,
                        })
            if should_stop is not None and should_stop():
                proc.kill()
                proc.wait()
                raise StellaError("Cancelled.")
            # R34: a hung quantizer stops on the timeout, with a
            # plain-words message naming it — the same shape as
            # export's converter timeout (gguf._run).
            if deadline is not None and time.monotonic() >= deadline:
                proc.kill()
                proc.wait()
                if timeout >= 60:
                    span = f"{timeout / 60:.0f} minutes"
                else:
                    span = f"{timeout:g} seconds"
                raise StellaError(
                    f"the quantizer timed out after {span}. The "
                    "requant was stopped. Try again, or check the "
                    "llama.cpp install."
                )
            if (
                on_progress is not None
                and not saw_count
                and time.monotonic() - last_still_working
                >= _still_working_seconds
            ):
                last_still_working = time.monotonic()
                on_progress({
                    "type": "still_working",
                    "message": "Still working...",
                })
        proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        from .tool_errors import translate_tool_error

        raise StellaError(
            translate_tool_error(
                "".join(lines), what=what, code=proc.returncode
            )
        )


_QUANTIZE_PROGRESS_RES = (
    # The format llama-quantize really prints (on stderr):
    # "[  12/ 287] blk.0.attn_q.weight - [...], type = q4_K, ..."
    re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]"),
    re.compile(r"tensor\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)\s+of\s+(\d+)\s+tensors?", re.IGNORECASE),
    re.compile(r"(\d+)\s*/\s*(\d+)\s+tensors?", re.IGNORECASE),
)


def _parse_quantize_progress(line: str) -> tuple[int, int] | None:
    """A "tensor N of M" count from one quantizer output line,
    or None when the line carries no count. A count is only
    believed when it is sane (a positive total, done within it):
    a stray "[ 1/ 2 ]" in a tensor name must not fake progress."""
    for pattern in _QUANTIZE_PROGRESS_RES:
        match = pattern.search(line)
        if match is None:
            continue
        done, total = int(match.group(1)), int(match.group(2))
        if 0 < total and 0 <= done <= total:
            return done, total
    return None


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
    # R5: refuse vision models BEFORE anything is registered — a
    # requant keeps only the model layer, so the smaller copy
    # would lose its vision with no warning. The check sits next
    # to the quant validation, before llama-quantize or
    # `ollama create` ever run.
    if model_is_vision(tag, source, _models_dir):
        raise StellaError(
            f"{tag!r} can see pictures (it has vision parts). "
            "Stella cannot shrink vision models yet: requanting "
            "would keep only the text parts, and the smaller copy "
            "would no longer see. The original is untouched."
        )
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
    # upper bound. R32: the peak is TWICE the output — `ollama
    # create` copies the file into Ollama's blob store while the
    # work file is still on disk, and the work file is kept after
    # a successful create — so the old estimate (output + slack)
    # understated the job by about one whole output file.
    target_bpw = _QUANT_BPW[quant]
    ratio = target_bpw / (source_bpw or 3.0)
    estimate = max(int(source_bytes * ratio), source_bytes // 20)
    needed = 2 * estimate + DISK_SLACK_BYTES
    free = shutil.disk_usage(work).free
    if free < needed:
        raise StellaError(
            f"Not enough free disk to shrink {tag!r}. The smaller "
            f"model needs about {_format_size(needed)} free (the "
            "new file, plus Ollama's own copy of it), and this "
            f"disk has {_format_size(free)} free. Free some "
            "space and try again."
        )

    def emit(event: dict):
        if on_event is not None:
            on_event(event)

    # llama-quantize's own warning, in plain words: re-quantizing
    # an already-quantized model rounds the weights a second time,
    # which can cost noticeably more quality than quantizing from
    # the original 16-bit or 32-bit weights. Every Ollama model is
    # already quantized, so this warns unless the source is
    # positively known to be unquantized (F32/F16/BF16).
    requantize_warning = None
    if source_bpw is None or source_bpw < 16.0:
        requantize_warning = (
            "Heads up: this model is already quantized, so shrinking "
            "it rounds the weights a second time. It can lose "
            "noticeably more quality than quantizing from the "
            "original 16-bit or 32-bit weights."
        )
    emit({
        "type": "found",
        "source_tag": tag,
        "source_bytes": source_bytes,
        "source_quant": source_quant,
        "quant": quant,
        "new_tag": new_tag,
        "requantize_warning": requantize_warning,
    })
    if should_stop is not None and should_stop():
        raise StellaError("Cancelled.")
    # --allow-requantize: every Ollama model is already quantized,
    # and llama-quantize refuses to requantize already-quantized
    # tensors without it ("requantizing from type q4_K is
    # disabled"). Without the flag, requant fails on every real
    # Ollama model.
    try:
        _run(
            [str(quantize), "--allow-requantize", str(source),
             str(out_path), quant],
            what=f"Shrinking {tag!r} to {quant}",
            _runner=_runner,
            should_stop=should_stop,
            # S21: the quantizer's per-tensor lines stream through
            # as progress events, so the run never goes quiet.
            on_progress=emit,
        )
    except BaseException:
        # A failed, cancelled, or interrupted run leaves a partial
        # file behind; remove it so a half-written model never sits
        # in the work folder. R33: the old handler caught
        # StellaError only, so Ctrl+C (a BaseException) and a disk
        # error (OSError) left the partial file behind. The
        # interrupt is re-raised, never swallowed, and the cleanup
        # itself never raises.
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if not out_path.is_file() or out_path.stat().st_size == 0:
        # Empty output is no output: clear it before complaining.
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
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
            # R34 scopes the timeout to the quantizer run; the
            # create keeps no timeout (its own bound is a
            # separate P3 task).
            timeout=None,
        )
    except StellaError as exc:
        raise StellaError(
            f"{exc}\nThe smaller file is still at {out_path}. "
            "Is Ollama running? Start it and try again."
        ) from exc
    except BaseException:
        # R33: an interrupted create (Ctrl+C, a disk error) leaves
        # no work files behind either — the same cleanup as the
        # failed quantize above. A plain StellaError keeps the
        # file on purpose (the message above names it, so the user
        # can retry the create); an interrupt is not a retryable
        # failure, so the work files go.
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            modelfile.unlink(missing_ok=True)
        except OSError:
            pass
        raise
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
