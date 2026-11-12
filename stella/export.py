"""STELLA export / import — a fine-tune as a portable package.

An export is a folder:

    <project>-stella-export/
      manifest.json     # profile + project + metamorph block + versions
      config.json       # training settings (the knobs Item 3 will drive)
      README.md         # human summary: what this is, how to use it
      weights/          # adapter / merged weights land here (Item 3).
                        # v0.1 ships a placeholder note — no weights exist
                        # yet, and Stella never pretends otherwise.
      checkpoints/      # copied from the project, if any exist

Import reads a package back, verifies it (required keys, known
metamorph mode, sane names), and recreates the profile (if missing)
and project. The round-trip check (export -> import into a fresh
home -> compare manifests) is the v0.1 proof the package is real.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .model import METAMORPH_MODES, STELLA_VERSION, StellaError, Store, validate_slug

EXPORT_SUFFIX = "-stella-export"


def export_project(store: Store, profile: str, project: str, dest: str | Path) -> Path:
    """Export a project to <dest>/<project>-stella-export/. Returns the dir."""
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    dest = Path(dest).expanduser()
    out = dest / (project + EXPORT_SUFFIX)
    if out.exists():
        raise StellaError(f"export folder already exists: {out}")
    out.mkdir(parents=True)

    manifest = {
        "stella_version": STELLA_VERSION,
        "kind": "stella-export",
        "profile": {
            "name": prof["name"],
            "display_name": prof.get("display_name", prof["name"]),
            "role": prof.get("role", ""),
            "ollama_tag": prof.get("ollama_tag", ""),
            "base_ref": prof.get("base_ref", ""),
            "processor": prof.get("processor", ""),
            "config": prof.get("config", {}),
            "dependencies": prof.get("dependencies", []),
        },
        "project": {
            "name": proj["name"],
            "display_name": proj.get("display_name", proj["name"]),
            "dataset_ref": proj.get("dataset_ref", ""),
            "settings": proj.get("settings", {}),
            "metamorph": proj.get("metamorph", {"mode": "morph", "notes": ""}),
            "status": proj.get("status", "draft"),
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "config.json").write_text(
        json.dumps(proj.get("settings", {}), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    role = prof.get("role") or "no role set"
    (out / "README.md").write_text(
        f"# {proj.get('display_name', proj['name'])} — Stella export\n\n"
        f"Fine-tune of profile **{prof.get('display_name', prof['name'])}** "
        f"(role: {role}, base: {prof.get('ollama_tag') or prof.get('base_ref') or 'not set'}).\n\n"
        f"MetaMorphAi mode: **{manifest['project']['metamorph'].get('mode', 'morph')}**.\n"
        f"Dataset: {proj.get('dataset_ref') or 'not set'}.\n"
        f"Status: {proj.get('status', 'draft')}.\n\n"
        "## Contents\n\n"
        "- `manifest.json` — the full profile + project record.\n"
        "- `config.json` — training settings.\n"
        "- `weights/` — adapter / merged weights (Item 3).\n"
        "- `checkpoints/` — training checkpoints, if any were made.\n\n"
        "Import back into Stella with: `stella import <this folder>`\n"
        "or the Import button in the Stella window.\n",
        encoding="utf-8",
    )
    weights = out / "weights"
    weights.mkdir()
    (weights / "README.txt").write_text(
        "Weights for this fine-tune land here when training runs (Item 3).\n"
        "v0.1 exports the manifest, config and checkpoints only — no weights\n"
        "exist yet, so this folder ships empty on purpose.\n",
        encoding="utf-8",
    )
    src_ckpt = store.project_dir(profile, project) / "checkpoints"
    dst_ckpt = out / "checkpoints"
    dst_ckpt.mkdir()
    if src_ckpt.is_dir():
        for item in sorted(src_ckpt.iterdir()):
            if item.is_file():
                shutil.copy2(item, dst_ckpt / item.name)
            elif item.is_dir():
                shutil.copytree(item, dst_ckpt / item.name)
    notes_src = store.project_dir(profile, project) / "notes.md"
    if notes_src.is_file():
        shutil.copy2(notes_src, out / "notes.md")
    return out


def verify_export(path: str | Path) -> dict:
    """Read and verify an export package. Returns its manifest."""
    path = Path(path).expanduser()
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise StellaError(f"not a Stella export: no manifest.json in {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StellaError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != "stella-export":
        raise StellaError("not a Stella export: bad manifest kind")
    prof = manifest.get("profile")
    proj = manifest.get("project")
    if not isinstance(prof, dict) or not isinstance(proj, dict):
        raise StellaError("export manifest is missing profile or project")
    validate_slug(prof.get("name", ""), "profile name in export")
    validate_slug(proj.get("name", ""), "project name in export")
    mode = (proj.get("metamorph") or {}).get("mode", "morph")
    if mode not in METAMORPH_MODES:
        raise StellaError(f"export has unknown metamorph mode: {mode!r}")
    if not (path / "config.json").is_file():
        raise StellaError("export is missing config.json")
    return manifest


def import_export(store: Store, path: str | Path) -> dict:
    """Import a verified export package into this home.

    Creates the profile if it does not exist yet (same slug, role and
    base from the manifest); the project must not already exist.
    Returns {"profile": ..., "project": ...}.
    """
    path = Path(path).expanduser()
    manifest = verify_export(path)
    prof = manifest["profile"]
    proj = manifest["project"]
    slug = prof["name"]
    try:
        store.get_profile(slug)
        profile_existed = True
    except StellaError:
        store.create_profile(
            slug,
            ollama_tag=prof.get("ollama_tag", ""),
            role=prof.get("role", ""),
            display_name=prof.get("display_name", slug),
            base_ref=prof.get("base_ref", ""),
            config=prof.get("config", {}),
            processor=prof.get("processor", ""),
            dependencies=prof.get("dependencies", []),
        )
        profile_existed = False
    metamorph = proj.get("metamorph") or {}
    created = store.create_project(
        slug,
        proj["name"],
        display_name=proj.get("display_name", proj["name"]),
        dataset_ref=proj.get("dataset_ref", ""),
        settings=proj.get("settings", {}),
        metamorph_mode=metamorph.get("mode", "morph"),
        metamorph_notes=metamorph.get("notes", ""),
    )
    if proj.get("status"):
        store.update_project(slug, proj["name"], status=proj["status"])
        created = store.get_project(slug, proj["name"])
    # Bring checkpoints + notes along, if the package has them.
    src_ckpt = path / "checkpoints"
    if src_ckpt.is_dir():
        dst_ckpt = store.project_dir(slug, proj["name"]) / "checkpoints"
        for item in sorted(src_ckpt.iterdir()):
            if item.is_file():
                shutil.copy2(item, dst_ckpt / item.name)
            elif item.is_dir():
                shutil.copytree(item, dst_ckpt / item.name)
    notes_src = path / "notes.md"
    if notes_src.is_file():
        store.write_notes(slug, proj["name"], notes_src.read_text(encoding="utf-8"))
    return {
        "profile": slug,
        "profile_existed": profile_existed,
        "project": created["name"],
    }
