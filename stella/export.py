"""STELLA export / import — a fine-tune as a portable package.

An export is a folder:

    <project>-stella-export/
      manifest.json     # profile + project + metamorph block + versions
      config.json       # training settings (the knobs Item 3 will drive)
      README.md         # human summary: what this is, how to use it
      weights/          # the trained LoRA adapter, when training has
                        # run (Item 3). Ships a placeholder note until
                        # then — Stella never pretends weights exist.
      checkpoints/      # copied from the project, if any exist
      probe_results.json  # refusal-probe before/after, if run
      sleep/            # sleep cycles (adapters, manifest, replay
                        # reports), if any were run (Item 4)

Import reads a package back, verifies it (required keys, known
metamorph mode, sane names), and recreates the profile (if missing)
and project. The round-trip check (export -> import into a fresh
home -> compare manifests) is the v0.1 proof the package is real.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .model import (
    DEFAULT_SETTINGS,
    METAMORPH_MODES,
    PROJECT_STATUSES,
    STELLA_VERSION,
    StellaError,
    Store,
    metamorph_mode,
    validate_settings,
    validate_slug,
)

EXPORT_SUFFIX = "-stella-export"


def _metamorph_block(proj: dict) -> dict:
    """The project's metamorph block for a manifest, read through
    the shared defensive reader (T37/T38): null/missing/wrong-type
    yields the default mode instead of a crash."""
    block = proj.get("metamorph")
    notes = block.get("notes", "") if isinstance(block, dict) else ""
    return {"mode": metamorph_mode(proj), "notes": notes}


def export_project(store: Store, profile: str, project: str, dest: str | Path) -> Path:
    """Export a project to <dest>/<project>-stella-export/. Returns the dir.

    The package is built in a staging dir next to the target and
    moved into place only when every file is written (T38): a
    failure anywhere leaves no partial package behind, and a retry
    never trips over "export folder already exists".
    """
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    dest = Path(dest).expanduser()
    if dest.exists() and not dest.is_dir():
        raise StellaError(f"export destination is not a folder: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / (project + EXPORT_SUFFIX)
    if out.exists():
        raise StellaError(f"export folder already exists: {out}")
    staging = Path(
        tempfile.mkdtemp(prefix=out.name + ".staging-", dir=str(dest))
    )
    try:
        _build_package(store, profile, project, prof, proj, staging)
        staging.replace(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return out


def _build_package(store, profile, project, prof, proj, out: Path) -> None:
    """Write every package file into `out` (the staging dir)."""
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
            "metamorph": _metamorph_block(proj),
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
        f"# {proj.get('display_name', proj['name'])}: Stella export\n\n"
        f"Fine-tune of profile **{prof.get('display_name', prof['name'])}** "
        f"(role: {role}, base: {prof.get('ollama_tag') or prof.get('base_ref') or 'not set'}).\n\n"
        f"MetaMorphAi mode: **{manifest['project']['metamorph'].get('mode', 'morph')}**.\n"
        f"Dataset: {proj.get('dataset_ref') or 'not set'}.\n"
        f"Status: {proj.get('status', 'draft')}.\n\n"
        "## Contents\n\n"
        "- `manifest.json`: the full profile + project record.\n"
        "- `config.json`: training settings.\n"
        "- `weights/`: adapter / merged weights (Item 3).\n"
        "- `checkpoints/`: training checkpoints, if any were made.\n"
        "- `sleep/`: sleep cycles (adapters, manifest, replay "
        "reports), if any were run.\n\n"
        "Import back into Stella with: `stella import <this folder>`\n"
        "or the Import button in the Stella window.\n",
        encoding="utf-8",
    )
    weights = out / "weights"
    weights.mkdir()
    src_adapter = store.project_dir(profile, project) / "adapter"
    if (src_adapter / "adapter_config.json").is_file():
        # The trained LoRA adapter travels with the export.
        for item in sorted(src_adapter.iterdir()):
            if item.is_file():
                shutil.copy2(item, weights / item.name)
            elif item.is_dir():
                shutil.copytree(item, weights / item.name)
    else:
        (weights / "README.txt").write_text(
            "No trained adapter yet. Train first:\n"
            f"  stella train {profile} {project}\n"
            "then export again and the adapter ships in this folder.\n",
            encoding="utf-8",
        )
    probe_src = store.project_dir(profile, project) / "probe_results.json"
    if probe_src.is_file():
        shutil.copy2(probe_src, out / "probe_results.json")
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
    # Sleep cycles travel whole: manifest + every cycle's adapter,
    # rows, and replay report. (The weights-drop bug — export
    # carrying a payload import never brought back — is not repeated
    # here: import restores sleep/ below, and a round-trip test pins
    # it.)
    src_sleep = store.project_dir(profile, project) / "sleep"
    if src_sleep.is_dir():
        shutil.copytree(src_sleep, out / "sleep")


def _check_field(block: dict, key: str, kind: str, where: str) -> None:
    """Require a manifest field to be of the right type, when
    present. `kind` is "str", "dict", or "str-list". Absent is
    fine — defaults cover it. Every failure is a plain StellaError."""
    if key not in block or block[key] is None:
        return
    value = block[key]
    if kind == "str" and isinstance(value, str):
        return
    if kind == "dict" and isinstance(value, dict):
        return
    if (
        kind == "str-list"
        and isinstance(value, list)
        and all(isinstance(item, str) for item in value)
    ):
        return
    want = {"str": "text", "dict": "an object", "str-list": "a list of text"}[kind]
    raise StellaError(
        f"export manifest: {where} {key!r} must be {want}, "
        f"not {type(value).__name__}"
    )


def verify_export(path: str | Path) -> dict:
    """Read and verify an export package. Returns its manifest.

    Import is the trust boundary — packages come from other
    machines, other people, and hand-edits — so the manifest schema
    is checked strictly here (T1): types for every field, the
    metamorph mode enum, and the project status enum. Nothing
    downstream ever sees a manifest field this has not validated.
    Settings VALUE ranges are the model layer's job (T6) and are
    checked by import before anything is created. The version range
    check is T40's, not this task's: no format versioning here.
    """
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
    for key in ("display_name", "role", "ollama_tag", "base_ref", "processor"):
        _check_field(prof, key, "str", "profile")
    _check_field(prof, "config", "dict", "profile")
    _check_field(prof, "dependencies", "str-list", "profile")
    for key in ("display_name", "dataset_ref"):
        _check_field(proj, key, "str", "project")
    _check_field(proj, "settings", "dict", "project")
    metamorph = proj.get("metamorph")
    if metamorph is not None:
        if not isinstance(metamorph, dict):
            raise StellaError(
                "export manifest: project 'metamorph' must be an "
                f"object, not {type(metamorph).__name__}"
            )
        _check_field(metamorph, "notes", "str", "project metamorph")
        mode = metamorph.get("mode", "morph")
        if mode not in METAMORPH_MODES:
            raise StellaError(f"export has unknown metamorph mode: {mode!r}")
    status = proj.get("status")
    if status is not None:
        if not isinstance(status, str) or status not in PROJECT_STATUSES:
            raise StellaError(
                f"export has unknown project status: {status!r} "
                f"(must be one of {', '.join(PROJECT_STATUSES)})"
            )
    if not (path / "config.json").is_file():
        raise StellaError("export is missing config.json")
    return manifest


def import_export(store: Store, path: str | Path) -> dict:
    """Import a verified export package into this home.

    Creates the profile if it does not exist yet (same slug, role and
    base from the manifest); the project must not already exist.
    Returns {"profile": ..., "project": ...}.

    Atomic (T1): names are normalized once at import start, so the
    returned names match the stored names; settings values are
    validated before anything is created; and if any step still
    fails, the profile/project just created are removed again — a
    failed import leaves the home exactly as it was.
    """
    path = Path(path).expanduser()
    manifest = verify_export(path)
    prof = manifest["profile"]
    proj = manifest["project"]
    # Normalize once, at import start: the store lowercases, so the
    # names used (and returned) must already be the stored form.
    slug = validate_slug(prof["name"], "profile name in export")
    project_slug = validate_slug(proj["name"], "project name in export")
    # Validate settings values BEFORE creating anything, so a bad
    # value cannot strand a half-created profile behind it.
    merged_settings = dict(DEFAULT_SETTINGS)
    merged_settings.update(proj.get("settings") or {})
    validate_settings(merged_settings)
    try:
        store.get_profile(slug)
        profile_existed = True
    except StellaError:
        profile_existed = False
    created_profile = False
    created_project = False
    try:
        if not profile_existed:
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
            created_profile = True
        metamorph = proj.get("metamorph") or {}
        created = store.create_project(
            slug,
            project_slug,
            display_name=proj.get("display_name", project_slug),
            dataset_ref=proj.get("dataset_ref", ""),
            settings=proj.get("settings", {}),
            metamorph_mode=metamorph.get("mode", "morph"),
            metamorph_notes=metamorph.get("notes", ""),
        )
        created_project = True
        if proj.get("status"):
            store.update_project(slug, project_slug, status=proj["status"])
            created = store.get_project(slug, project_slug)
        # Bring checkpoints + notes along, if the package has them.
        src_ckpt = path / "checkpoints"
        if src_ckpt.is_dir():
            dst_ckpt = store.project_dir(slug, project_slug) / "checkpoints"
            for item in sorted(src_ckpt.iterdir()):
                if item.is_file():
                    shutil.copy2(item, dst_ckpt / item.name)
                elif item.is_dir():
                    shutil.copytree(item, dst_ckpt / item.name)
        notes_src = path / "notes.md"
        if notes_src.is_file():
            store.write_notes(
                slug, project_slug, notes_src.read_text(encoding="utf-8")
            )
        # Sleep cycles come back whole (manifest + adapters + reports).
        src_sleep = path / "sleep"
        if src_sleep.is_dir():
            dst_sleep = store.project_dir(slug, project_slug) / "sleep"
            shutil.copytree(src_sleep, dst_sleep)
    except BaseException:
        # Roll back what this import created, best effort: a failed
        # import leaves the home exactly as it was.
        if created_project:
            try:
                store.delete_project(slug, project_slug)
            except Exception:
                pass
        if created_profile:
            try:
                store.delete_profile(slug)
            except Exception:
                pass
        raise
    return {
        "profile": slug,
        "profile_existed": profile_existed,
        "project": created["name"],
    }
