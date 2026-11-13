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
import shutil
import subprocess
from pathlib import Path

from .model import StellaError, Store

DEFAULT_QUANT = "Q4_K_M"

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
    for d in candidates:
        if convert is None and (d / "convert_hf_to_gguf.py").is_file():
            convert = d / "convert_hf_to_gguf.py"
        for q in (d / "build" / "bin" / "llama-quantize", d / "llama-quantize"):
            if quantize is None and q.is_file():
                quantize = q
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
        missing.append("llama-quantize")
    if missing:
        raise StellaError(
            f"llama.cpp is incomplete: missing {', '.join(missing)}.\n"
            + LLAMA_CPP_HINT
        )
    return convert, quantize


def merge_adapter(
    base_ref: str,
    adapter_dir: str | Path,
    out_dir: str | Path,
    *,
    _model_loader=None,
    _dtype: str = "bfloat16",
) -> Path:
    """Merge a LoRA adapter into its base and save HF weights.

    `_model_loader` is a test hook: (base_ref, adapter_dir) -> model,
    so tests can merge a tiny model with no downloads.
    """
    from .train import load_base_model, require_training_deps

    require_training_deps()
    adapter_dir = Path(adapter_dir)
    out_dir = Path(out_dir)
    if not (adapter_dir / "adapter_config.json").is_file():
        raise StellaError(f"no adapter in {adapter_dir}")
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


def _run(cmd: list[str], *, _runner=None) -> None:
    """Run a converter command, or hand it to the injected fake."""
    if _runner is not None:
        _runner(cmd)
        return
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
        raise StellaError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            + "\n".join(tail)
        )


def convert_to_gguf(
    hf_dir: str | Path,
    out_path: str | Path,
    *,
    quant: str = DEFAULT_QUANT,
    llama_cpp: tuple[Path, Path] | None = None,
    _runner=None,
) -> dict:
    """Convert merged HF weights to a quantized GGUF file.

    Two steps, the classic reliable path: convert to F16 GGUF, then
    quantize. Returns {"gguf": path, "quant": quant, "bytes": size}.
    """
    import sys

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
    _run(
        [
            sys.executable, str(convert), str(hf_dir),
            "--outfile", str(tmp_f16), "--outtype", "f16",
        ],
        _runner=_runner,
    )
    if _runner is None and not tmp_f16.is_file():
        raise StellaError(
            f"converter finished but wrote no file: {tmp_f16}"
        )
    _run(
        [str(quantize), str(tmp_f16), str(out_path), quant],
        _runner=_runner,
    )
    if _runner is None and not out_path.is_file():
        raise StellaError(
            f"quantizer finished but wrote no file: {out_path}"
        )
    if tmp_f16.is_file() and _runner is None:
        tmp_f16.unlink()  # the F16 intermediate is 2x the size; drop it
    return {
        "gguf": str(out_path),
        "quant": quant,
        "bytes": out_path.stat().st_size if out_path.is_file() else 0,
    }


def write_modelfile(
    gguf_path: str | Path,
    out_path: str | Path,
    *,
    name: str,
    system: str = "",
    template: str = "",
) -> tuple[Path, str]:
    """Write an Ollama Modelfile for a GGUF file.

    Returns (modelfile_path, ollama_create_command).
    """
    gguf_path = Path(gguf_path).expanduser().resolve()
    out_path = Path(out_path)
    lines = [f"FROM {gguf_path}"]
    if template:
        lines.append(f'TEMPLATE """{template}"""')
    if system:
        lines.append(f'SYSTEM """{system}"""')
    lines.append("PARAMETER temperature 0.7")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = f"ollama create {name} -f {out_path}"
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
    _runner=None,
    _model_loader=None,
    _dtype: str = "bfloat16",
) -> dict:
    """Full round-trip for one trained project.

    Merges the adapter (project adapter/, or checkpoints/step-N with
    --from-checkpoint), converts, quantizes, writes the Modelfile.
    Returns paths + the ollama create command.
    """
    from .train import LFM3_HF_REPO

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
                f"project {project!r} has no trained adapter yet — "
                "run training first (stella train "
                f"{profile} {project})"
            )
    base_ref = prof.get("base_ref") or ""
    if not base_ref:
        raise StellaError(
            f"profile {profile!r} has no base_ref — set it to the "
            f"Hugging Face repo of the base model (e.g. {LFM3_HF_REPO!r})"
        )
    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    merged_dir = dest / f"{project}-merged-hf"
    if merged_dir.exists():
        shutil.rmtree(merged_dir)
    merge_adapter(
        base_ref, adapter_dir, merged_dir,
        _model_loader=_model_loader, _dtype=_dtype,
    )
    gguf_name = f"{project}-{quant.lower().replace('_', '-')}.gguf"
    gguf_path = dest / gguf_name
    if gguf_path.exists():
        gguf_path.unlink()
    result = convert_to_gguf(
        merged_dir, gguf_path, quant=quant,
        llama_cpp=llama_cpp, _runner=_runner,
    )
    model_name = f"{profile}-{project}"
    _modelfile, command = write_modelfile(
        gguf_path, dest / "Modelfile", name=model_name
    )
    (dest / "gguf-export.json").write_text(
        json.dumps(
            {
                "profile": profile,
                "project": project,
                "base_ref": base_ref,
                "adapter": str(adapter_dir),
                "merged_hf": str(merged_dir),
                "gguf": str(gguf_path),
                "quant": quant,
                "gguf_bytes": result["bytes"],
                "ollama_name": model_name,
                "ollama_create": command,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    store.update_project(profile, project, status="exported")
    return {
        "merged_hf": str(merged_dir),
        "gguf": str(gguf_path),
        "quant": quant,
        "gguf_bytes": result["bytes"],
        "modelfile": str(dest / "Modelfile"),
        "ollama_name": model_name,
        "ollama_create": command,
    }
