"""Project templates (T112): JSON files in stella/templates/, so a
new template is a file, not a code change.

A template is a known-good starting point for a project: the
dataset shape (which dataset file it trains on), the metamorph
mode, the base it was made for, and the training settings it
starts from. The picker shows the template's name and its
plain-words description only — never the settings (T16: the user
never sees training settings).

Schema (every field except "settings" is required):

    {
      "name": "lfm3-tool-format",       # slug, also the file stem
      "title": "LFM3 tool calls",       # shown in the picker
      "description": "Teach LFM3 ...",  # plain words, shown in the picker
      "mode": "both",                   # a metamorph mode
      "dataset_ref": "sample-tool-calls.jsonl",
      "base_ref": "LiquidAI/LFM3-1.7B",
      "settings": {"rank": 8, ...}      # partial: merged over the defaults
    }

The first template is the LFM3 tool-format preset, carrying the
audit's recommended defaults as its starting point (the audit
called the defaults genuinely good: rank 8, lr 0.0002, epochs 3,
batch 1 — audit #2). Its mode is "both", the mode the tool-calls
fixture already uses. No approver was awake to confirm the values;
they are the audit defaults, noted as such in the template file.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import (
    DEFAULT_SETTINGS,
    METAMORPH_MODES,
    StellaError,
    validate_settings,
    validate_slug,
)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _validate_template(data: dict, source: str) -> dict:
    """Check a parsed template dict. Returns the normalized
    template: name, title, description, mode, dataset_ref,
    base_ref, settings (merged over the defaults, validated).
    Every rejection names the file and the field."""
    if not isinstance(data, dict):
        raise StellaError(f"template {source} is not a JSON object")
    for key in ("name", "title", "description", "mode", "dataset_ref", "base_ref"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise StellaError(
                f"template {source}: {key!r} must be non-empty text"
            )
    name = validate_slug(data["name"], f"template name in {source}")
    mode = data["mode"]
    if mode not in METAMORPH_MODES:
        raise StellaError(
            f"template {source}: mode must be one of "
            f"{', '.join(METAMORPH_MODES)}, not {mode!r}"
        )
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise StellaError(f"template {source}: 'settings' must be an object")
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    try:
        merged = validate_settings(merged)
    except StellaError as exc:
        raise StellaError(f"template {source}: {exc}") from exc
    return {
        "name": name,
        "title": data["title"].strip(),
        "description": data["description"].strip(),
        "mode": mode,
        "dataset_ref": data["dataset_ref"].strip(),
        "base_ref": data["base_ref"].strip(),
        "settings": merged,
    }


def list_templates() -> list[dict]:
    """Every valid template in the tree, sorted by name. A file
    that cannot be read or validated is skipped: a broken template
    must not break the New Project dialog. (load_template raises
    on a named broken template instead, so a bad name is never
    silently ignored.)"""
    out = []
    if not TEMPLATE_DIR.is_dir():
        return out
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(_validate_template(data, path.name))
        except (OSError, ValueError, StellaError):
            continue
    out.sort(key=lambda t: t["name"])
    return out


def load_template(name: str) -> dict:
    """Load one template by name (its slug). Raises StellaError
    when there is no template with that name, or it is broken."""
    slug = validate_slug(name, "template name")
    path = TEMPLATE_DIR / f"{slug}.json"
    if not path.is_file():
        known = [t["name"] for t in list_templates()]
        hint = f" Known templates: {', '.join(known)}." if known else ""
        raise StellaError(f"no template named {slug!r}.{hint}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StellaError(
            f"template {path.name} cannot be read: {exc}"
        ) from exc
    return _validate_template(data, path.name)


def template_project_kwargs(template: dict) -> dict:
    """The create_project keyword arguments a template carries:
    dataset, settings, and metamorph mode. The base_ref stays
    out — the base belongs to the profile, not the project, and
    the template never changes the profile it lands in."""
    return {
        "dataset_ref": template["dataset_ref"],
        "settings": dict(template["settings"]),
        "metamorph_mode": template["mode"],
    }
