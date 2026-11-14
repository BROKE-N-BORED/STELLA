"""STELLA export / import — a fine-tune as a portable package.

An export is a folder:

    <project>-stella-export/
      manifest.json     # profile + project + metamorph block + versions
      README.md         # human summary: what this is, how to use it
      weights/          # the trained LoRA adapter, when training has
                        # run (Item 3). Ships a placeholder note until
                        # then — Stella never pretends weights exist.
      checkpoints/      # copied from the project, if any exist
      probe_results.json  # refusal-probe before/after, if run
      sleep/            # sleep cycles (adapters, manifest, replay
                        # reports), if any were run (Item 4)
      dataset/          # the training data file, when the export
                        # bundled it in (T59) — otherwise the
                        # package only names the dataset ref

The manifest is the one source of truth for the settings (T60):
v0.1–v0.12 exports also carried a config.json copy of the settings,
but nothing ever read it — import always took the settings from the
manifest — so v0.13 stopped writing it. Old packages that carry it
still import; the file is ignored.

The package format is versioned separately from the app version
(T40): `format: 1` in the manifest, enforced on import. See
docs/FORMAT.md for the format, the kinds, and the legacy rule.

Import reads a package back, verifies it (required keys, known
metamorph mode, sane names), and recreates the profile (if missing)
and project. The round-trip check (export -> import into a fresh
home -> compare manifests) is the v0.1 proof the package is real.

When the profile already exists, import merges the profile block
instead of discarding it (T57): tag, role and base are compared
with the manifest — identical blocks import silently, differing
blocks ask the user to keep theirs or take the package's.
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
    WEIGHT_STATUSES,
    StellaError,
    Store,
    metamorph_mode,
    normalize_status,
    validate_settings,
    validate_slug,
)

EXPORT_SUFFIX = "-stella-export"

# Package format (T40): the format version is separate from the app
# version. 1 is the only version this Stella writes, and the newest
# it reads. A package claiming a newer format is refused on import
# with "this package needs a newer Stella". A package with no
# format field is a legacy v0.1-v0.12 package and reads as format 1
# (the shape is the same) — see docs/FORMAT.md.
FORMAT_VERSION = 1
MIN_SUPPORTED_FORMAT = 1

# Package kinds (T40): distinct `kind` values sharing one manifest
# shape, so profile export (T86) and recipe export (T170) never
# become two formats. Only the project package is importable yet;
# the other two are defined here so their shape is settled before
# anything writes one.
PACKAGE_KINDS = {
    "stella-export": "project package: one profile block + one project",
    "stella-profile-export": (
        "profile package: a profile with all its projects (T86)"
    ),
    "stella-recipe-export": "recipe package: a reusable training recipe (T170)",
}
PROJECT_PACKAGE_KIND = "stella-export"


def _metamorph_block(proj: dict) -> dict:
    """The project's metamorph block for a manifest, read through
    the shared defensive reader (T37/T38): null/missing/wrong-type
    yields the default mode instead of a crash."""
    block = proj.get("metamorph")
    notes = block.get("notes", "") if isinstance(block, dict) else ""
    return {"mode": metamorph_mode(proj), "notes": notes}


def export_project(
    store: Store, profile: str, project: str, dest: str | Path,
    bundle_dataset: bool = False,
) -> Path:
    """Export a project to <dest>/<project>-stella-export/. Returns the dir.

    The package is built in a staging dir next to the target and
    moved into place only when every file is written (T38): a
    failure anywhere leaves no partial package behind, and a retry
    never trips over "export folder already exists".

    With `bundle_dataset` (T59), the project's dataset file is
    copied into the package as `dataset/<filename>` and the
    manifest records it — the package trains anywhere, without
    the other PC needing its own copy. A dataset ref that does
    not resolve on this PC fails the export outright: a bundle
    that silently shipped reference-only would be a lie. With no
    dataset ref there is nothing to bundle, and the flag is a
    no-op.
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
        _build_package(
            store, profile, project, prof, proj, staging,
            bundle_dataset=bundle_dataset,
        )
        staging.replace(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return out


def _build_package(
    store, profile, project, prof, proj, out: Path,
    bundle_dataset: bool = False,
) -> None:
    """Write every package file into `out` (the staging dir)."""
    # The bundled dataset (T59): resolve the ref and copy the file
    # in before the manifest is written, so the manifest can
    # record the bundled filename.
    dataset_bundled = ""
    if bundle_dataset:
        ref = proj.get("dataset_ref", "")
        if ref:
            from .train import resolve_dataset_ref

            try:
                dataset_path = resolve_dataset_ref(
                    store, profile, project, ref
                )
            except StellaError as exc:
                raise StellaError(
                    f"cannot bundle the dataset: {exc}"
                ) from exc
            dataset_dir = out / "dataset"
            dataset_dir.mkdir()
            shutil.copy2(dataset_path, dataset_dir / dataset_path.name)
            dataset_bundled = dataset_path.name
    manifest = {
        "stella_version": STELLA_VERSION,
        "format": FORMAT_VERSION,
        "kind": PROJECT_PACKAGE_KIND,
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
    if dataset_bundled:
        manifest["project"]["dataset_bundled"] = dataset_bundled
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # No config.json (T60): the manifest already holds the settings,
    # and nothing ever read the copy. Never require a file you
    # never read.
    role = prof.get("role") or "no role set"
    dataset_line = f"Dataset: {proj.get('dataset_ref') or 'not set'}.\n"
    if dataset_bundled:
        dataset_line += (
            f"Dataset bundled: {dataset_bundled} (copied into this "
            "package, in the dataset folder).\n"
        )
    (out / "README.md").write_text(
        f"# {proj.get('display_name', proj['name'])}: Stella export\n\n"
        f"Fine-tune of profile **{prof.get('display_name', prof['name'])}** "
        f"(role: {role}, base: {prof.get('ollama_tag') or prof.get('base_ref') or 'not set'}).\n\n"
        f"MetaMorphAi mode: **{manifest['project']['metamorph'].get('mode', 'morph')}**.\n"
        f"{dataset_line}"
        f"Status: {proj.get('status', 'draft')}.\n\n"
        "## Contents\n\n"
        "- `manifest.json`: the full profile + project record, "
        "including the training settings.\n"
        "- `weights/`: adapter / merged weights (Item 3).\n"
        "- `checkpoints/`: training checkpoints, if any were made.\n"
        "- `probe_results.json`: the refusal-probe result, if the "
        "probe ran.\n"
        "- `sleep/`: sleep cycles (adapters, manifest, replay "
        "reports), if any were run.\n"
        + (
            "- `dataset/`: the training data, copied in with the "
            "package.\n"
            if dataset_bundled
            else ""
        )
        + "\n"
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
    checked by import before anything is created. The format
    version (T40) is checked here too: a newer format is refused
    with "needs a newer Stella", and a package with no format
    field reads as the legacy format 1.
    """
    path = Path(path).expanduser()
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise StellaError(f"not a Stella export: no manifest.json in {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StellaError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise StellaError("not a Stella export: bad manifest kind")
    kind = manifest.get("kind")
    if kind not in PACKAGE_KINDS:
        raise StellaError("not a Stella export: bad manifest kind")
    if kind != PROJECT_PACKAGE_KIND:
        # A known kind this Stella cannot import yet (T40): say
        # what it is, not just "bad kind" — profile and recipe
        # packages arrive in later versions.
        raise StellaError(
            f"this package is a {PACKAGE_KINDS[kind]}. This Stella "
            "can only import project packages yet."
        )
    # Format version (T40), separate from the app version: a
    # package from a newer Stella must never import silently and
    # lose what the newer format carries.
    fmt = manifest.get("format")
    if fmt is None:
        # Legacy rule: packages written before format versioning
        # (v0.1-v0.12) carry no format field and read as format 1.
        fmt = FORMAT_VERSION
    if isinstance(fmt, bool) or not isinstance(fmt, int):
        raise StellaError(
            "export manifest: 'format' must be a whole number, "
            f"not {fmt!r}"
        )
    if fmt > FORMAT_VERSION:
        raise StellaError(
            f"this package needs a newer Stella (package format "
            f"{fmt}, this Stella reads up to format "
            f"{FORMAT_VERSION}). Update Stella and try again."
        )
    if fmt < MIN_SUPPORTED_FORMAT:
        raise StellaError(f"export manifest: unknown package format {fmt}")
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
    for key in ("display_name", "dataset_ref", "dataset_bundled"):
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
        # A legacy status ("trained") reads as its current word
        # ("done", T53) — the manifest dict is normalized in
        # memory, so the import stores the current word. The
        # package file itself is untouched.
        status = normalize_status(status)
        proj["status"] = status
        if not isinstance(status, str) or status not in PROJECT_STATUSES:
            raise StellaError(
                f"export has unknown project status: {status!r} "
                f"(must be one of {', '.join(PROJECT_STATUSES)})"
            )
    # No config.json check (T60): the file was dropped in v0.13 —
    # the manifest holds the settings, and old packages that carry
    # config.json still import (the file is ignored).
    return manifest


def _is_placeholder_readme(path: Path) -> bool:
    """True when a weights/README.txt is the placeholder note
    export writes for an untrained project (T41) — never a weight,
    never copied as one."""
    if path.name != "README.txt" or not path.is_file():
        return False
    try:
        return path.read_text(encoding="utf-8").startswith(
            "No trained adapter yet."
        )
    except OSError:
        return False


def _package_weights(path: Path) -> list[Path]:
    """The real weight files in a package's weights/ dir (T41):
    everything except the placeholder note. Empty when the package
    carries no adapter."""
    weights = path / "weights"
    if not weights.is_dir():
        return []
    return [
        item
        for item in sorted(weights.iterdir())
        if not _is_placeholder_readme(item)
    ]


# The profile block fields import compares (T57): tag, role, base.
# display_name, config, processor and dependencies are the
# profile's own furniture and are never merged — only the three
# fields that say which model this profile trains.
PROFILE_BLOCK_FIELDS = ("ollama_tag", "role", "base_ref")

# Plain words for the three fields, for warnings and dialogs.
PROFILE_FIELD_WORDS = {
    "ollama_tag": "tag",
    "role": "role",
    "base_ref": "base",
}


def compare_profile_block(local: dict, package: dict) -> dict:
    """Compare a stored profile block with a manifest's profile block.

    Returns {field: {"local": ..., "package": ...}} for the fields
    that differ, and {} when the blocks agree. Only the three
    PROFILE_BLOCK_FIELDS are compared.

    This is the T58 extension point: the import preview dialog
    reuses this comparator (and this diff shape) to show the
    existing-profile warning before anything is imported.
    """
    diff = {}
    for field in PROFILE_BLOCK_FIELDS:
        local_value = local.get(field, "")
        package_value = package.get(field, "")
        if local_value != package_value:
            diff[field] = {"local": local_value, "package": package_value}
    return diff


def describe_profile_diff(diff: dict) -> str:
    """Plain-words list of the differing fields: "tag", "tag and
    role", "tag, role and base". Empty diff -> ""."""
    words = [
        PROFILE_FIELD_WORDS[field]
        for field in PROFILE_BLOCK_FIELDS
        if field in diff
    ]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    if len(words) == 2:
        return f"{words[0]} and {words[1]}"
    return f"{words[0]}, {words[1]} and {words[2]}"


def preview_export(
    store: Store, path: str | Path,
    installed_models: list[str] | None = None,
) -> dict:
    """Summarize an export package WITHOUT importing it (T58):
    what it is, what it carries, and what would change here.
    Raises StellaError on a bad package, like verify_export.
    Returns a dict:

      profile, project: the slugs (normalized, as import stores)
      profile_display, project_display: the display names
      tag, role, base: the profile block from the manifest
      stella_version: the Stella that wrote the package
      status: the project status in the manifest
      weights: True when the package carries real weights
      checkpoints: how many checkpoint entries it carries
      probe, sleep: True when probe results / sleep cycles are in
      dataset_ref, dataset_bundled: the manifest's dataset fields
      dataset_status: "bundled" (the file travels with the
        package), "present" (the ref resolves on this PC),
        "missing" (the ref is set and not here), "none" (no ref)
      profile_existed: the profile is already in this home
      profile_diff: the T57 diff shape, {} when the blocks agree
      base_installed: True/False when the caller passed an
        installed list and the tag is (not) on it; None when
        unknown (no list, or no tag to check)
    """
    path = Path(path).expanduser()
    manifest = verify_export(path)
    prof = manifest["profile"]
    proj = manifest["project"]
    slug = validate_slug(prof["name"], "profile name in export")
    project_slug = validate_slug(proj["name"], "project name in export")
    ckpt_dir = path / "checkpoints"
    checkpoints = (
        len(list(ckpt_dir.iterdir())) if ckpt_dir.is_dir() else 0
    )
    try:
        local_block = store.get_profile(slug)
        profile_existed = True
    except StellaError:
        local_block = None
        profile_existed = False
    profile_diff = (
        compare_profile_block(local_block, prof)
        if profile_existed
        else {}
    )
    # The dataset status (T59): bundled beats present beats
    # missing — a bundled file travels with the package, so the
    # ref never needs resolving.
    dataset_ref = proj.get("dataset_ref", "")
    dataset_bundled = proj.get("dataset_bundled", "")
    bundled_present = bool(
        dataset_bundled
        and dataset_bundled == Path(dataset_bundled).name
        and (path / "dataset" / dataset_bundled).is_file()
    )
    if bundled_present:
        dataset_status = "bundled"
    elif not dataset_ref:
        dataset_status = "none"
    else:
        from .train import resolve_dataset_ref

        try:
            resolve_dataset_ref(store, slug, project_slug, dataset_ref)
        except StellaError:
            dataset_status = "missing"
        else:
            dataset_status = "present"
    # The base health (T61): an empty list means "unknown", like
    # import — no warning fires on a guess.
    tag = prof.get("ollama_tag", "")
    base_installed = None
    if tag and installed_models:
        base_installed = tag in installed_models
    return {
        "profile": slug,
        "project": project_slug,
        "profile_display": prof.get("display_name", slug),
        "project_display": proj.get("display_name", project_slug),
        "tag": tag,
        "role": prof.get("role", ""),
        "base": prof.get("base_ref", ""),
        "stella_version": manifest.get("stella_version", ""),
        "status": proj.get("status", "draft"),
        "weights": bool(_package_weights(path)),
        "checkpoints": checkpoints,
        "probe": (path / "probe_results.json").is_file(),
        "sleep": (path / "sleep").is_dir(),
        "dataset_ref": dataset_ref,
        "dataset_bundled": dataset_bundled,
        "dataset_status": dataset_status,
        "profile_existed": profile_existed,
        "profile_diff": profile_diff,
        "base_installed": base_installed,
    }


def format_preview(summary: dict) -> str:
    """The preview summary in plain words (T58), one line per
    fact — shared by the import dialog and the CLI, so both show
    the same thing."""
    lines = [
        f"Profile {summary['profile']}, project {summary['project']}.",
    ]
    tag = summary.get("tag") or summary.get("base") or ""
    if tag:
        lines.append(f"Base model: {tag}.")
    version = summary.get("stella_version")
    if version:
        lines.append(f"Made with Stella {version}.")
    lines.append(f"Status: {summary.get('status', 'draft')}.")
    parts = []
    if summary["weights"]:
        parts.append("the trained weights")
    if summary["checkpoints"]:
        n = summary["checkpoints"]
        parts.append(f"{n} checkpoint{'s' if n != 1 else ''}")
    if summary["probe"]:
        parts.append("probe results")
    if summary["sleep"]:
        parts.append("sleep cycles")
    if parts:
        lines.append("Inside: " + ", ".join(parts) + ".")
    else:
        lines.append("Inside: the project record only.")
    status = summary.get("dataset_status", "none")
    if status == "bundled":
        lines.append(
            f"Dataset: {summary['dataset_bundled']} (copied in with "
            "the package)."
        )
    elif status == "present":
        lines.append(f"Dataset: {summary['dataset_ref']} (on this PC).")
    elif status == "missing":
        lines.append(
            f"Dataset: {summary['dataset_ref']} (not on this PC)."
        )
    if summary.get("profile_existed"):
        diff = summary.get("profile_diff") or {}
        if diff:
            lines.append(
                f"The profile {summary['profile']!r} is already here, "
                f"but the package's {describe_profile_diff(diff)} "
                f"{'differs' if len(diff) == 1 else 'differ'}:"
            )
            for field in PROFILE_BLOCK_FIELDS:
                if field not in diff:
                    continue
                word = PROFILE_FIELD_WORDS[field]
                local = diff[field]["local"] or "(blank)"
                package = diff[field]["package"] or "(blank)"
                lines.append(
                    f"  {word}: yours is {local!r}, the package has "
                    f"{package!r}."
                )
        else:
            lines.append(
                f"The profile {summary['profile']!r} is already here."
            )
    if summary.get("base_installed") is False:
        lines.append(
            f"The base model {summary.get('tag')!r} is not installed "
            "on this PC. Pull it before training."
        )
    return "\n".join(lines)


def import_export(
    store: Store,
    path: str | Path,
    profile_choice: str | None = None,
    on_profile_conflict=None,
    installed_models: list[str] | None = None,
) -> dict:
    """Import a verified export package into this home.

    Creates the profile if it does not exist yet (same slug, role and
    base from the manifest); the project must not already exist.
    Returns {"profile": ..., "project": ..., "profile_existed": ...,
    "profile_diff": ..., "profile_choice": ..., "warnings": [...]}.

    The weights round-trip (T41): the package's weights/ (minus the
    placeholder note) land in the project's adapter/ dir, and
    probe_results.json comes back too, so the refusal evidence
    travels with the fine-tune. A package whose manifest claims a
    finished status but carries no weights imports as a draft, with
    a warning in the result — a project with no weights must not
    claim to be finished.

    The profile block is merged, not discarded (T57). When the
    profile already exists, tag / role / base are compared with the
    manifest: identical blocks import silently; differing blocks
    need a choice. `profile_choice` ("keep" or "take") decides
    outright; `on_profile_conflict(slug, diff)` is asked instead
    when given (the GUI dialog, the CLI prompt); with neither, the
    local values are kept and a warning says so. "take" makes the
    stored profile block exactly the package's — all three fields
    are passed explicitly, so the T54 tag/base sync cannot move the
    base underneath the merge. A take that is later rolled back
    restores the local values.

    Atomic (T1): names are normalized once at import start, so the
    returned names match the stored names; settings values are
    validated before anything is created; and if any step still
    fails, the profile/project just created are removed again — a
    failed import leaves the home exactly as it was.

    The base health check (T61): when the caller passes the
    installed-model list (`installed_models`), a profile tag that
    is not on it warns, naming the tag — a package arriving from
    another machine is exactly when the base is most likely to be
    missing. The warning never blocks the import. An empty list
    (or none) means "unknown" — Ollama down, or no list given —
    so no warning fires on a guess.

    The dataset (T59): a bundled dataset is copied into the new
    project dir and the ref becomes its filename, so the imported
    project trains as-is. An unbundled ref that does not resolve
    on this PC warns and sets `dataset_missing` in the result, so
    the caller can offer to find the file. The result always
    carries `dataset_ref` (the ref as imported) and
    `dataset_missing` (False when the dataset is present or
    bundled, or when the project has no dataset).
    """
    if profile_choice is not None and profile_choice not in ("keep", "take"):
        raise StellaError(
            f"profile_choice must be 'keep' or 'take', "
            f"not {profile_choice!r}"
        )
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
    # Weights decide the imported status (T41): a finished status
    # with no weights behind it is corrected to draft, with a
    # warning the caller surfaces.
    warnings: list[str] = []
    weight_items = _package_weights(path)
    status = proj.get("status") or "draft"
    if status in WEIGHT_STATUSES and not weight_items:
        warnings.append(
            f"the package says this project is {status}, but it "
            "carries no trained weights, so it imports as a draft. "
            "Train it first, then export again."
        )
        status = "draft"
    # Base health (T61): the tag is checked against the installed
    # list the caller passed (the cached list in the window, a
    # direct list_models() on the CLI). A missing tag warns and
    # never blocks; an empty list means "unknown", so no warning
    # fires on a guess.
    if installed_models:
        tag = prof.get("ollama_tag", "")
        if tag and tag not in installed_models:
            warnings.append(
                f"the base model {tag!r} is not installed on this "
                "PC. Pull it before training."
            )
    try:
        store.get_profile(slug)
        profile_existed = True
    except StellaError:
        profile_existed = False
    # T57: compare the profile block before creating anything, so a
    # choice is asked (or a warning recorded) while the home is
    # still untouched. Identical blocks import silently.
    profile_diff: dict = {}
    choice = None
    local_block: dict | None = None
    if profile_existed:
        local_block = store.get_profile(slug)
        profile_diff = compare_profile_block(local_block, prof)
    if profile_diff:
        if profile_choice is not None:
            choice = profile_choice
        elif on_profile_conflict is not None:
            answer = on_profile_conflict(slug, profile_diff)
            choice = answer if answer in ("keep", "take") else "keep"
        else:
            # No way to ask: keep the local values and say so.
            choice = "keep"
            fields = describe_profile_diff(profile_diff)
            verb = "differs" if len(profile_diff) == 1 else "differ"
            warnings.append(
                f"the package's {fields} {verb} from this "
                f"profile's, so this profile's values were kept."
            )
    created_profile = False
    created_project = False
    merged_profile = False
    merged_before: dict | None = None
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
        elif choice == "take":
            # T57 take: the stored block becomes the package's,
            # exactly — all three fields passed explicitly, so the
            # T54 sync cannot move the base. The local values are
            # remembered so a failed import restores them.
            merged_before = {
                field: (local_block or {}).get(field, "")
                for field in PROFILE_BLOCK_FIELDS
            }
            store.update_profile(
                slug,
                ollama_tag=prof.get("ollama_tag", ""),
                role=prof.get("role", ""),
                base_ref=prof.get("base_ref", ""),
            )
            merged_profile = True
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
        if status != "draft":
            store.update_project(slug, project_slug, status=status)
            created = store.get_project(slug, project_slug)
        # The dataset (T59): a bundled dataset lands in the project
        # dir and the ref becomes its filename — it resolves via the
        # project dir, so the imported project trains as-is. The
        # bundled name is trusted only as a plain filename: a
        # hand-edited manifest claiming "../x" is ignored, never
        # copied outside the project dir. An unbundled ref that is
        # not on this PC warns and is reported, so the caller can
        # offer to find the file.
        dataset_ref = proj.get("dataset_ref", "")
        dataset_missing = False
        bundled = proj.get("dataset_bundled", "")
        bundled_src = None
        if (
            bundled
            and bundled == Path(bundled).name
            and bundled not in (".", "..")
        ):
            candidate = path / "dataset" / bundled
            if candidate.is_file():
                bundled_src = candidate
        if bundled_src is not None:
            shutil.copy2(
                bundled_src,
                store.project_dir(slug, project_slug) / bundled,
            )
            dataset_ref = bundled
            store.update_project(slug, project_slug, dataset_ref=bundled)
        elif dataset_ref:
            from .train import resolve_dataset_ref

            try:
                resolve_dataset_ref(store, slug, project_slug, dataset_ref)
            except StellaError:
                dataset_missing = True
                warnings.append(
                    f"the dataset {dataset_ref!r} is not on this PC. "
                    "Find the file before training."
                )
        # The trained adapter comes back (T41): the package's
        # weights/ land in the project's adapter/ dir, minus the
        # placeholder note — the payload the program exists to
        # produce, restored instead of dropped.
        if weight_items:
            dst_adapter = (
                store.project_dir(slug, project_slug) / "adapter"
            )
            dst_adapter.mkdir(parents=True, exist_ok=True)
            for item in weight_items:
                if item.is_file():
                    shutil.copy2(item, dst_adapter / item.name)
                elif item.is_dir():
                    shutil.copytree(item, dst_adapter / item.name)
        # The refusal evidence travels with the fine-tune.
        probe_src = path / "probe_results.json"
        if probe_src.is_file():
            shutil.copy2(
                probe_src,
                store.project_dir(slug, project_slug) / "probe_results.json",
            )
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
        # import leaves the home exactly as it was. The destroy
        # path (not the trash): a rollback must not leave a trash
        # folder behind. A take-merge is unwound the same way, so
        # the profile keeps the values it had before the import.
        if merged_profile and merged_before is not None:
            try:
                store.update_profile(slug, **merged_before)
            except Exception:
                pass
        if created_project:
            try:
                store._destroy_project(slug, project_slug)
            except Exception:
                pass
        if created_profile:
            try:
                store._destroy_profile(slug)
            except Exception:
                pass
        raise
    return {
        "profile": slug,
        "profile_existed": profile_existed,
        "profile_diff": profile_diff,
        "profile_choice": choice,
        "project": created["name"],
        "dataset_ref": dataset_ref,
        "dataset_missing": dataset_missing,
        "warnings": warnings,
    }
