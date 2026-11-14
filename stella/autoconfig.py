"""STELLA auto-config — measure this PC, pick training settings for it.

The design brief says the user never sees training settings: the
backend measures the PC and sets every knob to the best value for
this machine. This module is that backend half. It is Qt-free and
stdlib-only, so the model layer and the CLI can both use it with no
heavy imports.

Two halves:

- ``measure_pc()`` — CPU count + model, RAM total/available, free
  disk on the Stella home filesystem, 1-minute load. Best effort
  throughout: a reading that cannot be taken is ``None``, never a
  crash, and the settings rules treat unknown RAM as plenty (the
  defaults are already the conservative CPU recipe).
- ``compute_settings(ram_available_gb, model_params_b=None)`` — the
  documented conservative rules:

  - batch size is always 1 on CPU (bigger batches do not fit 8 GB
    and buy nothing on a CPU-only run).
  - LoRA rank 8, learning rate 2e-4, 3 epochs, max sequence length
    1024 — the usual recipe.
  - When less than 4 GB of RAM is available, rank drops to 4 and
    max sequence length to 512, so the run still fits with room
    for the system.
  - ``model_params_b`` is accepted so callers can pass the base
    model size; the current rules key off available RAM only,
    because on a CPU-only 8 GB machine RAM is the binding
    constraint. A future rule may use the size for very large
    bases; today it changes nothing.

``create_project`` (no explicit settings) stores the computed
settings with ``settings_source="auto"``; ``train_project``
re-measures at run start for auto projects and stores the fresh
values. Anything a human set — the Project window, the chat, an
import — is ``"manual"`` and is never recomputed.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# Below this much free RAM, the recipe shrinks (rank 4, seq 512) so
# the run still fits with room for the system.
LOW_RAM_GB = 4.0

# The usual recipe, on a machine with enough RAM.
DEFAULT_RANK = 8
DEFAULT_LEARNING_RATE = 0.0002
DEFAULT_EPOCHS = 3
DEFAULT_BATCH_SIZE = 1
DEFAULT_MAX_SEQ_LEN = 1024

# The shrunken recipe, on a machine short of RAM.
LOW_RAM_RANK = 4
LOW_RAM_MAX_SEQ_LEN = 512


def _default_home() -> Path:
    """The Stella home dir (same rule as model.default_home, kept
    local so this module stays free of the model import)."""
    override = os.environ.get("STELLA_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".stella"


def _cpu_model() -> str:
    """Best-effort CPU model name, or "unknown"."""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                _, _, value = line.partition(":")
                value = value.strip()
                if value:
                    return value
    except OSError:
        pass
    try:
        import platform

        value = platform.processor().strip()
        if value:
            return value
    except Exception:
        pass
    return "unknown"


def _ram_gb() -> tuple[float | None, float | None]:
    """(total GB, available GB) from /proc/meminfo, or (None, None)."""
    try:
        total = available = None
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) / 1024**2
            elif line.startswith("MemAvailable:"):
                available = int(line.split()[1]) / 1024**2
            if total is not None and available is not None:
                break
        if total is None:
            return None, None
        return round(total, 2), (round(available, 2) if available is not None else None)
    except (OSError, ValueError, IndexError):
        return None, None


def _load1() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        return None


def _disk_free_gb(path: Path) -> float | None:
    """Free GB on the filesystem holding `path`. The home dir may
    not exist yet on a fresh install, so walk up to the nearest
    existing ancestor — the filesystem is the same either way."""
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return None
        probe = parent
    try:
        return round(shutil.disk_usage(probe).free / 1024**3, 2)
    except OSError:
        return None


def measure_pc(home: str | Path | None = None) -> dict:
    """Measure this PC. Returns cpu_count, cpu_model, ram_total_gb,
    ram_available_gb, disk_free_gb (of the Stella home filesystem),
    and load1 (1-minute load average, None where unavailable)."""
    home_path = Path(home) if home is not None else _default_home()
    total_gb, available_gb = _ram_gb()
    disk_free = _disk_free_gb(home_path)
    return {
        "cpu_count": os.cpu_count() or 1,
        "cpu_model": _cpu_model(),
        "ram_total_gb": total_gb,
        "ram_available_gb": available_gb,
        "disk_free_gb": disk_free,
        "load1": _load1(),
    }


def compute_settings(
    ram_available_gb: float | None, model_params_b: float | None = None
) -> dict:
    """Training settings for a PC with this much RAM available.

    ``model_params_b`` (billions of parameters in the base model)
    is accepted for future rules; the current rules key off
    available RAM only — see the module docstring.
    """
    low_ram = ram_available_gb is not None and ram_available_gb < LOW_RAM_GB
    return {
        "rank": LOW_RAM_RANK if low_ram else DEFAULT_RANK,
        "learning_rate": DEFAULT_LEARNING_RATE,
        "epochs": DEFAULT_EPOCHS,
        "batch_size": DEFAULT_BATCH_SIZE,
        "max_seq_len": LOW_RAM_MAX_SEQ_LEN if low_ram else DEFAULT_MAX_SEQ_LEN,
    }


def auto_settings(home: str | Path | None = None) -> tuple[dict, dict]:
    """Measure this PC and compute its settings. Returns
    (measurement, settings)."""
    measurement = measure_pc(home)
    settings = compute_settings(measurement["ram_available_gb"])
    return measurement, settings


def _gb(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2f} GB"


def format_report(measurement: dict, settings: dict) -> str:
    """The measurement + computed settings in plain words, for
    `stella pc-info`."""
    lines = [
        f"This PC has {measurement['cpu_count']} CPUs "
        f"({measurement['cpu_model']}).",
        f"RAM: {_gb(measurement['ram_total_gb'])} total, "
        f"{_gb(measurement['ram_available_gb'])} available.",
        f"Free disk where Stella lives: {_gb(measurement['disk_free_gb'])}.",
    ]
    load1 = measurement["load1"]
    lines.append(
        f"Current load: {load1}."
        if load1 is not None
        else "Current load: unknown."
    )
    lines.append("")
    lines.append(
        "Training settings for this PC: LoRA rank "
        f"{settings['rank']}, learning rate {settings['learning_rate']}, "
        f"{settings['epochs']} epochs, batch size {settings['batch_size']}, "
        f"max sequence length {settings['max_seq_len']}."
    )
    return "\n".join(lines)
