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

Every package file (except the manifest itself) is listed in the
manifest with its sha256 and byte size (T104), and import verifies
them before creating anything — a truncated checkpoint refuses the
import, naming the file. The manifest also carries the original
`created` / `updated` timestamps plus an `exported_at` stamp
(T118), so an imported project keeps its history.

Import reads a package back, verifies it (required keys, known
metamorph mode, sane names), and recreates the profile (if missing)
and project. The round-trip check (export -> import into a fresh
home -> compare manifests) is the v0.1 proof the package is real.

When the profile already exists, import merges the profile block
instead of discarding it (T57): tag, role and base are compared
with the manifest — identical blocks import silently, differing
blocks ask the user to keep theirs or take the package's.

A profile can also be exported on its own (T86): a profile package
holds the profile manifest and, as an option, all its projects —
importable back with the same strict verification. Collisions are
choices (T117): export offers overwrite (GUI prompt, CLI --force),
import offers a copy under a new name or a replace with the old
project backed up to the trash. `stella verify` / the window's
Check package action (T105) runs the full verification — schema,
version, checksums — without importing anything.
"""

from __future__ import annotations

import hashlib
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
    utc_now,
    validate_settings,
    validate_slug,
)

EXPORT_SUFFIX = "-stella-export"
PROFILE_EXPORT_SUFFIX = "-stella-profile-export"

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
# become two formats. Project and profile packages are importable;
# the recipe kind is defined here so its shape is settled before
# anything writes one.
PACKAGE_KINDS = {
    "stella-export": "project package: one profile block + one project",
    "stella-profile-export": (
        "profile package: a profile with all its projects (T86)"
    ),
    "stella-recipe-export": "recipe package: a reusable training recipe (T170)",
}
PROJECT_PACKAGE_KIND = "stella-export"
PROFILE_PACKAGE_KIND = "stella-profile-export"

# The kinds this Stella can import (T86: the profile kind joined
# the project kind in v0.18).
IMPORTABLE_KINDS = (PROJECT_PACKAGE_KIND, PROFILE_PACKAGE_KIND)


# -- progress + cancel (T106) --------------------------------------
# Export and import copy files, and a checkpoint copy can take a
# while: the GUI runs them on a worker with a progress bar and a
# Cancel button. The engine side is two callables: on_progress
# (done_bytes, total_bytes) and should_stop (no-arg, True to stop).
# A stop raises StellaError("Cancelled.") — on export the staging
# dir is removed, on import the rollback runs — so a cancelled
# copy leaves no partial state either way.

COPY_CHUNK_BYTES = 1024 * 1024


class _CopyProgress:
    """Byte counter shared by one export/import: every counted
    copy reports through it, and every check point asks it
    whether the user cancelled."""

    def __init__(self, total: int, on_progress=None, should_stop=None):
        self.total = total
        self.done = 0
        self._on_progress = on_progress
        self._should_stop = should_stop

    def check(self) -> None:
        if self._should_stop is not None and self._should_stop():
            raise StellaError("Cancelled.")

    def report(self) -> None:
        if self._on_progress is not None:
            self._on_progress(self.done, self.total)

    def add(self, n: int) -> None:
        self.done += n
        self.report()


def _dir_bytes(path: Path) -> int:
    """The bytes under a dir (files only), 0 when it is not there."""
    if not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def _copy_file_counted(
    src: Path, dst: Path, progress: _CopyProgress | None
) -> None:
    """Copy one file in 1 MB chunks, reporting bytes and checking
    the stop flag between chunks. A stop mid-file leaves a partial
    destination file — the caller owns the cleanup (staging on
    export, rollback on import), which is what makes the cancel
    leave no partial state behind."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if progress is None:
        shutil.copy2(src, dst)
        return
    progress.check()
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            chunk = fin.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            fout.write(chunk)
            progress.add(len(chunk))
            progress.check()
    shutil.copystat(src, dst)


def _copy_tree_counted(
    src: Path, dst: Path, progress: _CopyProgress | None
) -> None:
    """Copy a whole dir, file by file, through the byte counter."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if progress is not None:
            progress.check()
        if item.is_file():
            _copy_file_counted(item, dst / item.name, progress)
        elif item.is_dir():
            _copy_tree_counted(item, dst / item.name, progress)


# -- checksums (T104) ------------------------------------------------
# The manifest lists every package file (except itself) with its
# sha256 and byte size. Import verifies them before creating
# anything: a truncated checkpoint, a half-copied package, a
# flipped bit — all fail loudly, naming the file. Legacy packages
# (before v0.18) carry no file list and verify as before, with no
# checksum step to fail.


def _hash_file(path: Path) -> tuple[str, int]:
    """(sha256 hex, byte size) of one file."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fin:
        while True:
            chunk = fin.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _package_file_hashes(root: Path) -> dict:
    """The files list for a manifest: every file under `root`
    except manifest.json itself (a manifest cannot hash itself),
    as {relative posix path: {"sha256": ..., "size": ...}}."""
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel == "manifest.json":
            continue
        sha, size = _hash_file(path)
        files[rel] = {"sha256": sha, "size": size}
    return files


def _verify_file_hashes(path: Path, manifest: dict) -> None:
    """Check the manifest's file list against the package on disk.
    No file list (a legacy package) means nothing to check. A
    missing file, a size mismatch, or a hash mismatch is a
    StellaError naming the file — the import is refused, loudly.
    A file in the package but NOT in the list is ignored: old
    packages carry files (config.json) the list never covered,
    and import only ever reads the files it knows."""
    files = manifest.get("files")
    if files is None:
        return
    if not isinstance(files, dict):
        raise StellaError(
            "export manifest: 'files' must be an object, "
            f"not {type(files).__name__}"
        )
    for rel, entry in sorted(files.items()):
        if not isinstance(entry, dict):
            raise StellaError(
                f"export manifest: file entry {rel!r} must be an "
                "object with a sha256 and a size"
            )
        want_sha = entry.get("sha256")
        want_size = entry.get("size")
        if not isinstance(want_sha, str) or not want_sha:
            raise StellaError(
                f"export manifest: file entry {rel!r} has no sha256"
            )
        if (
            isinstance(want_size, bool)
            or not isinstance(want_size, int)
            or want_size < 0
        ):
            raise StellaError(
                f"export manifest: file entry {rel!r} has no size"
            )
        # A listed path must stay inside the package: a hand-edited
        # manifest claiming "../x" is refused, never followed.
        target = path / rel
        try:
            target.resolve().relative_to(path.resolve())
        except ValueError:
            raise StellaError(
                f"export manifest: file entry {rel!r} escapes the package"
            ) from None
        if not target.is_file():
            raise StellaError(
                f"the package is incomplete: {rel} is listed in the "
                "manifest but is not in the package"
            )
        got_sha, got_size = _hash_file(target)
        if got_size != want_size or got_sha != want_sha:
            raise StellaError(
                f"the package is damaged: {rel} does not match its "
                "checksum (it may be truncated or half-copied). "
                "Export it again."
            )


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
    force: bool = False,
    on_progress=None,
    should_stop=None,
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

    With `force` (T117), an existing export folder is removed
    first instead of refusing — the caller's overwrite choice,
    made before the call. Without it, an existing folder refuses
    as before.

    `on_progress` / `should_stop` (T106) are the worker hooks:
    progress reports (bytes done, bytes total) and a stop cancels
    the copy — the staging dir is removed, so a cancelled export
    leaves no partial package.
    """
    prof = store.get_profile(profile)
    proj = store.get_project(profile, project)
    dest = Path(dest).expanduser()
    if dest.exists() and not dest.is_dir():
        raise StellaError(f"export destination is not a folder: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / (project + EXPORT_SUFFIX)
    if out.exists():
        if not force:
            raise StellaError(f"export folder already exists: {out}")
        if out.is_dir() and not out.is_symlink():
            shutil.rmtree(out)
        else:
            out.unlink()
    staging = Path(
        tempfile.mkdtemp(prefix=out.name + ".staging-", dir=str(dest))
    )
    progress = _CopyProgress(
        _export_total_bytes(store, profile, project, bundle_dataset),
        on_progress, should_stop,
    )
    try:
        _build_package(
            store, profile, project, prof, proj, staging,
            bundle_dataset=bundle_dataset,
            progress=progress,
        )
        staging.replace(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return out


def _export_total_bytes(
    store, profile, project, bundle_dataset: bool
) -> int:
    """The bytes an export will copy, for the progress bar: the
    adapter, checkpoints, notes, probe results, sleep cycles, and
    the bundled dataset when asked. A dataset that cannot be
    resolved counts 0 here — the export itself refuses on it."""
    pdir = store.project_dir(profile, project)
    total = _dir_bytes(pdir / "adapter")
    total += _dir_bytes(pdir / "checkpoints")
    total += _dir_bytes(pdir / "sleep")
    for name in ("notes.md", "probe_results.json"):
        item = pdir / name
        if item.is_file():
            total += item.stat().st_size
    if bundle_dataset:
        ref = store.get_project(profile, project).get("dataset_ref", "")
        if ref:
            from .train import resolve_dataset_ref

            try:
                total += resolve_dataset_ref(
                    store, profile, project, ref
                ).stat().st_size
            except (StellaError, OSError):
                pass
    return total


def _copy_project_payload(
    store, profile, project, out: Path,
    progress: _CopyProgress | None = None,
) -> None:
    """Copy a project's payload files into `out` (a package dir,
    or a profile package's projects/<slug>/ dir): the trained
    adapter (or the placeholder note when untrained), the probe
    results, the checkpoints, the notes, and the sleep cycles.
    Shared by the project and profile exports, so both packages
    carry the same payload."""
    weights = out / "weights"
    weights.mkdir(parents=True, exist_ok=True)
    src_adapter = store.project_dir(profile, project) / "adapter"
    if (src_adapter / "adapter_config.json").is_file():
        # The trained LoRA adapter travels with the export.
        for item in sorted(src_adapter.iterdir()):
            if progress is not None:
                progress.check()
            if item.is_file():
                _copy_file_counted(item, weights / item.name, progress)
            elif item.is_dir():
                _copy_tree_counted(item, weights / item.name, progress)
    else:
        (weights / "README.txt").write_text(
            "No trained adapter yet. Train first:\n"
            f"  stella train {profile} {project}\n"
            "then export again and the adapter ships in this folder.\n",
            encoding="utf-8",
        )
    probe_src = store.project_dir(profile, project) / "probe_results.json"
    if probe_src.is_file():
        _copy_file_counted(probe_src, out / "probe_results.json", progress)
    src_ckpt = store.project_dir(profile, project) / "checkpoints"
    dst_ckpt = out / "checkpoints"
    dst_ckpt.mkdir(parents=True, exist_ok=True)
    if src_ckpt.is_dir():
        for item in sorted(src_ckpt.iterdir()):
            if progress is not None:
                progress.check()
            if item.is_file():
                _copy_file_counted(item, dst_ckpt / item.name, progress)
            elif item.is_dir():
                _copy_tree_counted(item, dst_ckpt / item.name, progress)
    notes_src = store.project_dir(profile, project) / "notes.md"
    if notes_src.is_file():
        _copy_file_counted(notes_src, out / "notes.md", progress)
    # Sleep cycles travel whole: manifest + every cycle's adapter,
    # rows, and replay report. (The weights-drop bug — export
    # carrying a payload import never brought back — is not repeated
    # here: import restores sleep/ below, and a round-trip test pins
    # it.)
    src_sleep = store.project_dir(profile, project) / "sleep"
    if src_sleep.is_dir():
        _copy_tree_counted(src_sleep, out / "sleep", progress)


def _profile_manifest_block(prof: dict) -> dict:
    """The profile block for a manifest (T118: created/updated
    travel with it, so an import restores the profile's history
    instead of stamping it brand new)."""
    block = {
        "name": prof["name"],
        "display_name": prof.get("display_name", prof["name"]),
        "role": prof.get("role", ""),
        "ollama_tag": prof.get("ollama_tag", ""),
        "base_ref": prof.get("base_ref", ""),
        "processor": prof.get("processor", ""),
        "config": prof.get("config", {}),
        "dependencies": prof.get("dependencies", []),
    }
    if prof.get("created"):
        block["created"] = prof["created"]
    if prof.get("updated"):
        block["updated"] = prof["updated"]
    return block


def _project_manifest_block(proj: dict) -> dict:
    """The project block for a manifest (T118: created/updated
    travel with it)."""
    block = {
        "name": proj["name"],
        "display_name": proj.get("display_name", proj["name"]),
        "dataset_ref": proj.get("dataset_ref", ""),
        "settings": proj.get("settings", {}),
        "metamorph": _metamorph_block(proj),
        "status": proj.get("status", "draft"),
    }
    if proj.get("created"):
        block["created"] = proj["created"]
    if proj.get("updated"):
        block["updated"] = proj["updated"]
    return block


def _build_package(
    store, profile, project, prof, proj, out: Path,
    bundle_dataset: bool = False,
    progress: _CopyProgress | None = None,
) -> None:
    """Write every package file into `out` (the staging dir). The
    manifest is written LAST: the checksums (T104) cover every
    other file in the package, so they can only be computed once
    the payload is in place."""
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
            _copy_file_counted(
                dataset_path, dataset_dir / dataset_path.name, progress
            )
            dataset_bundled = dataset_path.name
    manifest = {
        "stella_version": STELLA_VERSION,
        "format": FORMAT_VERSION,
        "kind": PROJECT_PACKAGE_KIND,
        # T118: when this package was made, and the original
        # timestamps inside the profile/project blocks.
        "exported_at": utc_now(),
        "profile": _profile_manifest_block(prof),
        "project": _project_manifest_block(proj),
    }
    if dataset_bundled:
        manifest["project"]["dataset_bundled"] = dataset_bundled
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
    _copy_project_payload(store, profile, project, out, progress)
    # The checksums (T104) go in last: every file above is hashed
    # into the manifest, so import can tell a truncated package
    # from a whole one.
    if progress is not None:
        progress.check()
    manifest["files"] = _package_file_hashes(out)
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def export_profile(
    store: Store, profile: str, dest: str | Path,
    include_projects: bool = False,
    force: bool = False,
    on_progress=None,
    should_stop=None,
) -> Path:
    """Export a profile on its own (T86) to
    <dest>/<profile>-stella-profile-export/. Returns the dir.

    The package holds the profile manifest and, with
    `include_projects`, every project in the profile (each with
    its payload: weights, checkpoints, notes, probe results,
    sleep cycles — the same payload a project export carries).
    A profile with zero projects exports fine: the package is
    the profile alone, and importing it brings the profile back.

    The profile package kind comes from T40
    (`kind: "stella-profile-export"`); import verifies it with
    the same strictness as a project package (T1 schema, T40
    format, T104 checksums). Staging, force, and the progress /
    cancel hooks work exactly as in export_project. Datasets are
    referenced, never bundled: a profile export names each
    project's dataset ref, and import warns when one is not on
    the PC (like an unbundled project import).
    """
    prof = store.get_profile(profile)
    dest = Path(dest).expanduser()
    if dest.exists() and not dest.is_dir():
        raise StellaError(f"export destination is not a folder: {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / (profile + PROFILE_EXPORT_SUFFIX)
    if out.exists():
        if not force:
            raise StellaError(f"export folder already exists: {out}")
        if out.is_dir() and not out.is_symlink():
            shutil.rmtree(out)
        else:
            out.unlink()
    projects = (
        [
            p for p in store.list_projects(profile)
            if not p.get("_damaged")
        ]
        if include_projects
        else []
    )
    total = sum(
        _export_total_bytes(store, profile, p["name"], False)
        for p in projects
    )
    progress = _CopyProgress(total, on_progress, should_stop)
    staging = Path(
        tempfile.mkdtemp(prefix=out.name + ".staging-", dir=str(dest))
    )
    try:
        manifest = {
            "stella_version": STELLA_VERSION,
            "format": FORMAT_VERSION,
            "kind": PROFILE_PACKAGE_KIND,
            "exported_at": utc_now(),
            "profile": _profile_manifest_block(prof),
            "projects": [
                _project_manifest_block(
                    store.get_project(profile, p["name"])
                )
                for p in projects
            ],
        }
        role = prof.get("role") or "no role set"
        if projects:
            project_lines = "\n".join(
                f"- {p.get('display_name', p['name'])} ({p['name']})"
                for p in projects
            )
            contents = (
                f"Projects in this package:\n\n{project_lines}\n\n"
                "Each project folder under `projects/` holds its "
                "weights, checkpoints, notes, probe results, and "
                "sleep cycles.\n"
            )
        else:
            contents = (
                "No projects in this package: the profile alone.\n"
            )
        (staging / "README.md").write_text(
            f"# {prof.get('display_name', prof['name'])}: Stella profile export\n\n"
            f"Profile (role: {role}, base: "
            f"{prof.get('ollama_tag') or prof.get('base_ref') or 'not set'}).\n\n"
            f"{contents}\n"
            "Import back into Stella with: `stella import <this folder>`\n"
            "or the Import button in the Stella window.\n",
            encoding="utf-8",
        )
        for p in projects:
            _copy_project_payload(
                store, profile, p["name"],
                staging / "projects" / p["name"], progress,
            )
        if progress is not None:
            progress.check()
        manifest["files"] = _package_file_hashes(staging)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.replace(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return out


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


def _validate_project_block(proj: dict) -> None:
    """The schema check for one project block (T1), shared by the
    project package (one block) and the profile package (one per
    project). Types for every field, the metamorph mode enum, and
    the project status enum. A legacy status ("trained") is
    normalized to its current word in memory, so the import
    stores the current word; the package file is untouched."""
    for key in ("display_name", "dataset_ref", "dataset_bundled"):
        _check_field(proj, key, "str", "project")
    _check_field(proj, "settings", "dict", "project")
    _check_field(proj, "created", "str", "project")
    _check_field(proj, "updated", "str", "project")
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
        status = normalize_status(status)
        proj["status"] = status
        if not isinstance(status, str) or status not in PROJECT_STATUSES:
            raise StellaError(
                f"export has unknown project status: {status!r} "
                f"(must be one of {', '.join(PROJECT_STATUSES)})"
            )


def _validate_profile_block(prof: dict) -> None:
    """The schema check for the profile block (T1)."""
    for key in ("display_name", "role", "ollama_tag", "base_ref", "processor"):
        _check_field(prof, key, "str", "profile")
    _check_field(prof, "config", "dict", "profile")
    _check_field(prof, "dependencies", "str-list", "profile")
    _check_field(prof, "created", "str", "profile")
    _check_field(prof, "updated", "str", "profile")


def _validate_kind(manifest: dict) -> str:
    """The kind step: known, and one this Stella can import.
    Returns the kind. A known kind this Stella cannot import yet
    (the recipe kind) says what it is, not just "bad kind"."""
    kind = manifest.get("kind")
    if kind not in PACKAGE_KINDS:
        raise StellaError("not a Stella export: bad manifest kind")
    if kind not in IMPORTABLE_KINDS:
        raise StellaError(
            f"this package is a {PACKAGE_KINDS[kind]}. This Stella "
            "can only import project and profile packages yet."
        )
    return kind


def _validate_format(manifest: dict) -> int:
    """The format step (T40): a newer format is refused with
    "needs a newer Stella", and a package with no format field
    reads as the legacy format 1. Returns the format number."""
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
    return fmt


def _validate_schema(manifest: dict) -> None:
    """The schema step (T1): the profile block, and the project
    block(s) — one "project" for a project package, a "projects"
    list for a profile package. `exported_at` is text when
    present. Nothing downstream ever sees a manifest field this
    has not validated."""
    _check_field(manifest, "exported_at", "str", "manifest")
    prof = manifest.get("profile")
    if not isinstance(prof, dict):
        raise StellaError("export manifest is missing profile or project")
    validate_slug(prof.get("name", ""), "profile name in export")
    _validate_profile_block(prof)
    kind = manifest.get("kind")
    if kind == PROFILE_PACKAGE_KIND:
        projects = manifest.get("projects")
        if not isinstance(projects, list):
            raise StellaError(
                "export manifest: a profile package must carry a "
                "'projects' list"
            )
        seen = set()
        for proj in projects:
            if not isinstance(proj, dict):
                raise StellaError(
                    "export manifest: each project in a profile "
                    "package must be an object"
                )
            name = validate_slug(
                proj.get("name", ""), "project name in export"
            )
            if name in seen:
                raise StellaError(
                    f"export manifest: project {name!r} is listed twice"
                )
            seen.add(name)
            _validate_project_block(proj)
        return
    proj = manifest.get("project")
    if not isinstance(proj, dict):
        raise StellaError("export manifest is missing profile or project")
    validate_slug(proj.get("name", ""), "project name in export")
    _validate_project_block(proj)


def _load_manifest(path: Path) -> dict:
    """Read a package's manifest.json. Raises StellaError when
    there is no manifest, it is not JSON, or it is not an
    object."""
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise StellaError(f"not a Stella export: no manifest.json in {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StellaError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise StellaError("not a Stella export: bad manifest kind")
    return manifest


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
    field reads as the legacy format 1. The file checksums (T104)
    are checked here too: a listed file that is missing or does
    not match its hash refuses the package, naming the file.

    No config.json check (T60): the file was dropped in v0.13 —
    the manifest holds the settings, and old packages that carry
    config.json still import (the file is ignored).
    """
    path = Path(path).expanduser()
    manifest = _load_manifest(path)
    _validate_kind(manifest)
    _validate_format(manifest)
    _validate_schema(manifest)
    _verify_file_hashes(path, manifest)
    return manifest


def check_export(path: str | Path) -> dict:
    """Verify a package WITHOUT importing it (T105), one check at
    a time, for `stella verify` and the window's Check package
    action. Returns:

      {"ok": bool,
       "kind": the package kind ("" when it could not be read),
       "checks": [{"name": ..., "passed": bool, "detail": ...}, ...],
       "manifest": the manifest dict, or None when unreadable}

    The checks run in dependency order and stop at the first
    failure: a package with no manifest cannot have its kind
    checked. A legacy package with no file list passes the
    checksum step with a note — there is nothing to check, and
    the package still imports.
    """
    path = Path(path).expanduser()
    checks: list[dict] = []

    def record(name, passed, detail=""):
        checks.append(
            {"name": name, "passed": passed, "detail": detail}
        )

    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        record(
            "Manifest present", False,
            f"no manifest.json in {path}",
        )
        return {"ok": False, "kind": "", "checks": checks, "manifest": None}
    record("Manifest present", True)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        record("Manifest is valid JSON", False, str(exc))
        return {"ok": False, "kind": "", "checks": checks, "manifest": None}
    except OSError as exc:
        record("Manifest is valid JSON", False, str(exc))
        return {"ok": False, "kind": "", "checks": checks, "manifest": None}
    if not isinstance(manifest, dict):
        record(
            "Manifest is valid JSON", False,
            "the manifest is not a JSON object",
        )
        return {"ok": False, "kind": "", "checks": checks, "manifest": None}
    record("Manifest is valid JSON", True)
    try:
        kind = _validate_kind(manifest)
    except StellaError as exc:
        record("Package kind is known", False, str(exc))
        return {
            "ok": False, "kind": "", "checks": checks, "manifest": manifest,
        }
    record(
        "Package kind is known", True,
        PACKAGE_KINDS[kind].split(":")[0],
    )
    try:
        fmt = _validate_format(manifest)
    except StellaError as exc:
        record("Format is supported", False, str(exc))
        return {
            "ok": False, "kind": kind, "checks": checks, "manifest": manifest,
        }
    record(
        "Format is supported", True,
        f"format {fmt} (this Stella reads up to format "
        f"{FORMAT_VERSION})",
    )
    try:
        _validate_schema(manifest)
    except StellaError as exc:
        record("Manifest shape is valid", False, str(exc))
        return {
            "ok": False, "kind": kind, "checks": checks, "manifest": manifest,
        }
    record("Manifest shape is valid", True)
    files = manifest.get("files")
    if files is None:
        record(
            "Files match their checksums", True,
            "this package has no checksums to check (it was made "
            "before checksums)",
        )
        return {
            "ok": True, "kind": kind, "checks": checks, "manifest": manifest,
        }
    try:
        _verify_file_hashes(path, manifest)
    except StellaError as exc:
        record("Files match their checksums", False, str(exc))
        return {
            "ok": False, "kind": kind, "checks": checks, "manifest": manifest,
        }
    record(
        "Files match their checksums", True,
        f"{len(files)} file{'s' if len(files) != 1 else ''} checked",
    )
    return {
        "ok": True, "kind": kind, "checks": checks, "manifest": manifest,
    }


def format_check_report(report: dict) -> str:
    """The verify report in plain words (T105), one line per
    check — shared by the CLI and the window, so both show the
    same thing."""
    lines = []
    for check in report["checks"]:
        mark = "OK" if check["passed"] else "FAIL"
        line = f"{mark}: {check['name']}"
        if check.get("detail"):
            line += f" ({check['detail']})"
        lines.append(line)
    if report["ok"]:
        lines.append("All checks passed. Nothing was imported.")
    else:
        lines.append("A check failed. Nothing was imported.")
    return "\n".join(lines)


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

      kind: "stella-export" or "stella-profile-export"
      profile: the slug (normalized, as import stores)
      profile_display: the display name
      tag, role, base: the profile block from the manifest
      stella_version: the Stella that wrote the package
      exported_at: when the package was made ("" when unknown)
      profile_existed: the profile is already in this home
      profile_diff: the T57 diff shape, {} when the blocks agree
      base_installed: True/False when the caller passed an
        installed list and the tag is (not) on it; None when
        unknown (no list, or no tag to check)

    For a project package, also:

      project: the slug (normalized, as import stores)
      project_display: the display name
      status: the project status in the manifest
      weights: True when the package carries real weights
      checkpoints: how many checkpoint entries it carries
      probe, sleep: True when probe results / sleep cycles are in
      dataset_ref, dataset_bundled: the manifest's dataset fields
      dataset_status: "bundled" (the file travels with the
        package), "present" (the ref resolves on this PC),
        "missing" (the ref is set and not here), "none" (no ref)
      project_existed: the project is already in this home (T117:
        the import offers copy-under-a-new-name or replace)

    For a profile package, also:

      projects: the project slugs in the package
      project_count: how many projects it carries
      weights, checkpoints, probe, sleep: True / totals across
        all the projects in the package
      existing_projects: the slugs already in this home (a
        profile import refuses while any of these exist)
    """
    path = Path(path).expanduser()
    manifest = verify_export(path)
    kind = manifest.get("kind", PROJECT_PACKAGE_KIND)
    prof = manifest["profile"]
    slug = validate_slug(prof["name"], "profile name in export")
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
    # The base health (T61): an empty list means "unknown", like
    # import — no warning fires on a guess.
    tag = prof.get("ollama_tag", "")
    base_installed = None
    if tag and installed_models:
        base_installed = tag in installed_models
    summary = {
        "kind": kind,
        "profile": slug,
        "profile_display": prof.get("display_name", slug),
        "tag": tag,
        "role": prof.get("role", ""),
        "base": prof.get("base_ref", ""),
        "stella_version": manifest.get("stella_version", ""),
        "exported_at": manifest.get("exported_at", ""),
        "profile_existed": profile_existed,
        "profile_diff": profile_diff,
        "base_installed": base_installed,
    }
    if kind == PROFILE_PACKAGE_KIND:
        blocks = manifest.get("projects", [])
        names = [
            validate_slug(b.get("name", ""), "project name in export")
            for b in blocks
        ]
        weights = False
        checkpoints = 0
        probe = False
        sleep = False
        for name in names:
            payload = path / "projects" / name
            weights = weights or bool(_package_weights(payload))
            ckpt_dir = payload / "checkpoints"
            if ckpt_dir.is_dir():
                checkpoints += len(list(ckpt_dir.iterdir()))
            probe = probe or (payload / "probe_results.json").is_file()
            sleep = sleep or (payload / "sleep").is_dir()
        existing = []
        for name in names:
            if (
                store.project_dir(slug, name) / "project.json"
            ).is_file():
                existing.append(name)
        summary.update({
            "projects": names,
            "project_count": len(names),
            "weights": weights,
            "checkpoints": checkpoints,
            "probe": probe,
            "sleep": sleep,
            "existing_projects": existing,
        })
        return summary
    proj = manifest["project"]
    project_slug = validate_slug(proj["name"], "project name in export")
    ckpt_dir = path / "checkpoints"
    checkpoints = (
        len(list(ckpt_dir.iterdir())) if ckpt_dir.is_dir() else 0
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
    summary.update({
        "project": project_slug,
        "project_display": proj.get("display_name", project_slug),
        "status": proj.get("status", "draft"),
        "weights": bool(_package_weights(path)),
        "checkpoints": checkpoints,
        "probe": (path / "probe_results.json").is_file(),
        "sleep": (path / "sleep").is_dir(),
        "dataset_ref": dataset_ref,
        "dataset_bundled": dataset_bundled,
        "dataset_status": dataset_status,
        "project_existed": (
            store.project_dir(slug, project_slug) / "project.json"
        ).is_file(),
    })
    return summary


def format_preview(summary: dict) -> str:
    """The preview summary in plain words (T58), one line per
    fact — shared by the import dialog and the CLI, so both show
    the same thing."""
    if summary.get("kind") == PROFILE_PACKAGE_KIND:
        return _format_profile_preview(summary)
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
    if summary.get("project_existed"):
        lines.append(
            f"The project {summary['project']!r} is already here. "
            "Import it as a copy under a new name, or replace the "
            "old one (the old one goes to the trash)."
        )
    lines.extend(_format_profile_lines(summary))
    return "\n".join(lines)


def _format_profile_preview(summary: dict) -> str:
    """The preview summary for a profile package (T86): what the
    profile is, and which projects it carries."""
    lines = [f"Profile {summary['profile']}."]
    tag = summary.get("tag") or summary.get("base") or ""
    if tag:
        lines.append(f"Base model: {tag}.")
    version = summary.get("stella_version")
    if version:
        lines.append(f"Made with Stella {version}.")
    names = summary.get("projects", [])
    if names:
        lines.append(
            f"Projects in this package ({len(names)}): "
            + ", ".join(names)
            + "."
        )
        parts = []
        if summary["weights"]:
            parts.append("trained weights")
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
        lines.append("No projects in this package: the profile alone.")
    existing = summary.get("existing_projects", [])
    if existing:
        lines.append(
            "Already here, so this import cannot go ahead: "
            + ", ".join(existing)
            + ". Delete or rename them first, or import the "
            "profile on its own."
        )
    lines.extend(_format_profile_lines(summary))
    return "\n".join(lines)


def _format_profile_lines(summary: dict) -> list[str]:
    """The shared tail of both previews: what the profile block
    means here, and the base health (T57/T61)."""
    lines = []
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
    return lines


def suggest_copy_name(store: Store, profile: str, project: str) -> str:
    """The slug an import-as-a-copy lands under (T117):
    `<project>-copy`, then `-copy-2`, `-copy-3`, ... until one is
    free. The GUI shows this name before importing, and the engine
    derives the same one, so the two never disagree."""
    slug = validate_slug(project, "project name")
    candidate = f"{slug}-copy"
    n = 2
    while (
        store.project_dir(profile, candidate) / "project.json"
    ).is_file():
        candidate = f"{slug}-copy-{n}"
        n += 1
    return candidate


def _profile_merge_decision(
    store, slug, prof, profile_choice, on_profile_conflict, warnings
):
    """The T57 decision, before anything is created: does the
    profile exist, how does its block differ, and keep or take?
    Returns (profile_existed, profile_diff, choice, local_block).
    `choice` is None when there is no diff to decide. With a diff
    and no way to ask, the local values are kept and a warning
    says so."""
    try:
        local_block = store.get_profile(slug)
        profile_existed = True
    except StellaError:
        local_block = None
        profile_existed = False
    profile_diff = {}
    choice = None
    if profile_existed:
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
    return profile_existed, profile_diff, choice, local_block


def _create_profile_from_manifest(store, slug, prof) -> None:
    """Create a profile from a manifest block (T118: the original
    timestamps are restored, not re-stamped)."""
    store.create_profile(
        slug,
        ollama_tag=prof.get("ollama_tag", ""),
        role=prof.get("role", ""),
        display_name=prof.get("display_name", slug),
        base_ref=prof.get("base_ref", ""),
        config=prof.get("config", {}),
        processor=prof.get("processor", ""),
        dependencies=prof.get("dependencies", []),
        created=prof.get("created"),
        updated=prof.get("updated"),
    )


def _restore_project_record(
    store, slug, proj, package_root, payload_dir, warnings,
    progress: _CopyProgress | None = None,
) -> dict:
    """Create one project from a manifest block and restore its
    payload (weights, probe results, checkpoints, notes, sleep
    cycles, and a bundled dataset when the package carries one).
    Returns {"project": created record, "dataset_ref": ...,
    "dataset_missing": bool}.

    The caller validates the settings values and resolves the
    collision BEFORE this runs, so a bad value or a taken name
    cannot strand a half-created project behind it. The status
    rule (T41) applies here: a finished status with no weights
    behind it imports as a draft, with a warning.
    """
    project_slug = validate_slug(proj["name"], "project name in export")
    weight_items = _package_weights(payload_dir)
    status = proj.get("status") or "draft"
    if status in WEIGHT_STATUSES and not weight_items:
        warnings.append(
            f"the package says project {project_slug!r} is {status}, "
            "but it carries no trained weights, so it imports as a "
            "draft. Train it first, then export again."
        )
        status = "draft"
    metamorph = proj.get("metamorph") or {}
    created = store.create_project(
        slug,
        project_slug,
        display_name=proj.get("display_name", project_slug),
        dataset_ref=proj.get("dataset_ref", ""),
        settings=proj.get("settings", {}),
        metamorph_mode=metamorph.get("mode", "morph"),
        metamorph_notes=metamorph.get("notes", ""),
        created=proj.get("created"),
        updated=proj.get("updated"),
    )
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
        candidate = package_root / "dataset" / bundled
        if candidate.is_file():
            bundled_src = candidate
    if bundled_src is not None:
        _copy_file_counted(
            bundled_src,
            store.project_dir(slug, project_slug) / bundled,
            progress,
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
    _restore_project_payload(
        store, slug, project_slug, payload_dir, progress
    )
    return {
        "project": created,
        "dataset_ref": dataset_ref,
        "dataset_missing": dataset_missing,
    }


def _restore_project_payload(
    store, slug, project_slug, payload_dir,
    progress: _CopyProgress | None = None,
) -> None:
    """Copy one project's payload files from a package dir into
    the project dir: the trained adapter (minus the placeholder
    note), the probe results, the checkpoints, the notes, and the
    sleep cycles. Every copy goes through the byte counter, so a
    cancel between files (or mid-file) still rolls back cleanly."""
    if progress is not None:
        progress.check()
    weight_items = _package_weights(payload_dir)
    if weight_items:
        dst_adapter = (
            store.project_dir(slug, project_slug) / "adapter"
        )
        dst_adapter.mkdir(parents=True, exist_ok=True)
        for item in weight_items:
            if progress is not None:
                progress.check()
            if item.is_file():
                _copy_file_counted(item, dst_adapter / item.name, progress)
            elif item.is_dir():
                _copy_tree_counted(item, dst_adapter / item.name, progress)
    # The refusal evidence travels with the fine-tune.
    probe_src = payload_dir / "probe_results.json"
    if probe_src.is_file():
        _copy_file_counted(
            probe_src,
            store.project_dir(slug, project_slug) / "probe_results.json",
            progress,
        )
    # Bring checkpoints + notes along, if the package has them.
    src_ckpt = payload_dir / "checkpoints"
    if src_ckpt.is_dir():
        dst_ckpt = store.project_dir(slug, project_slug) / "checkpoints"
        for item in sorted(src_ckpt.iterdir()):
            if progress is not None:
                progress.check()
            if item.is_file():
                _copy_file_counted(item, dst_ckpt / item.name, progress)
            elif item.is_dir():
                _copy_tree_counted(item, dst_ckpt / item.name, progress)
    notes_src = payload_dir / "notes.md"
    if notes_src.is_file():
        text = notes_src.read_text(encoding="utf-8")
        store.write_notes(slug, project_slug, text)
        if progress is not None:
            progress.add(len(text.encode("utf-8")))
    # Sleep cycles come back whole (manifest + adapters + reports).
    src_sleep = payload_dir / "sleep"
    if src_sleep.is_dir():
        dst_sleep = store.project_dir(slug, project_slug) / "sleep"
        _copy_tree_counted(src_sleep, dst_sleep, progress)


def _import_total_bytes(package_root: Path, payload_dirs) -> int:
    """The bytes an import will copy, for the progress bar."""
    total = 0
    for payload in payload_dirs:
        total += _dir_bytes(payload / "weights")
        total += _dir_bytes(payload / "checkpoints")
        total += _dir_bytes(payload / "sleep")
        for name in ("notes.md", "probe_results.json"):
            item = payload / name
            if item.is_file():
                total += item.stat().st_size
    total += _dir_bytes(package_root / "dataset")
    return total


def import_export(
    store: Store,
    path: str | Path,
    profile_choice: str | None = None,
    on_profile_conflict=None,
    installed_models: list[str] | None = None,
    collision: str | None = None,
    on_project_conflict=None,
    on_progress=None,
    should_stop=None,
) -> dict:
    """Import a verified export package into this home.

    A project package creates the profile if it does not exist
    yet (same slug, role and base from the manifest); the project
    must not already exist, unless the collision is resolved (see
    below). A profile package is handed to import_profile_export
    (T86) and its result returned. Returns {"profile": ...,
    "project": ..., "profile_existed": ..., "profile_diff": ...,
    "profile_choice": ..., "warnings": [...]} for a project
    package (see import_profile_export for the profile shape).

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

    The timestamps (T118) are restored, not re-stamped: the
    imported profile and project keep the `created` / `updated`
    the manifest carries.

    Collisions are choices (T117), not dead ends. When the project
    already exists: `collision="copy"` imports it under a new slug
    (`<name>-copy`, then `-copy-2`, ...); `collision="replace"`
    moves the old project to the trash (T23) and imports over it —
    the result names the trash folder, and a failed import moves
    the old project back. `on_project_conflict(slug, project)`
    is asked instead when given, returning "copy", "replace", or
    "cancel". With neither, the import is refused, naming the
    collision. The profile merge is decided before the project
    collision: a refused import changes nothing.

    Atomic (T1): names are normalized once at import start, so the
    returned names match the stored names; settings values are
    validated before anything is created; and if any step still
    fails, the profile/project just created are removed again — a
    failed import leaves the home exactly as it was. A cancel
    (T106, via `should_stop`) rolls back the same way.

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
    if collision is not None and collision not in ("copy", "replace"):
        raise StellaError(
            f"collision must be 'copy' or 'replace', not {collision!r}"
        )
    path = Path(path).expanduser()
    manifest = verify_export(path)
    if manifest.get("kind") == PROFILE_PACKAGE_KIND:
        return import_profile_export(
            store, path,
            profile_choice=profile_choice,
            on_profile_conflict=on_profile_conflict,
            installed_models=installed_models,
            on_progress=on_progress,
            should_stop=should_stop,
        )
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
    warnings: list[str] = []
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
    # T57: compare the profile block before creating anything, so a
    # choice is asked (or a warning recorded) while the home is
    # still untouched. Identical blocks import silently.
    (
        profile_existed, profile_diff, choice, local_block,
    ) = _profile_merge_decision(
        store, slug, prof, profile_choice, on_profile_conflict, warnings
    )
    # T117: resolve the project collision before creating anything.
    # The profile decision above already ran, but it writes nothing,
    # so a refused import still changes nothing.
    collision_mode = None
    copy_slug = None
    project_exists = (
        store.project_dir(slug, project_slug) / "project.json"
    ).is_file()
    if project_exists:
        if collision is not None:
            collision_mode = collision
        elif on_project_conflict is not None:
            answer = on_project_conflict(slug, project_slug)
            if answer == "cancel":
                raise StellaError("Import cancelled.")
            collision_mode = (
                answer if answer in ("copy", "replace") else None
            )
        if collision_mode is None:
            raise StellaError(
                f"project {project_slug!r} already exists in profile "
                f"{slug!r}. Import it as a copy under a new name, or "
                "replace the old one (the old one goes to the trash)."
            )
        if collision_mode == "copy":
            copy_slug = suggest_copy_name(store, slug, project_slug)
    progress = _CopyProgress(
        _import_total_bytes(path, [path]), on_progress, should_stop,
    )
    created_profile = False
    merged_profile = False
    merged_before: dict | None = None
    replaced_trash: Path | None = None
    replaced_dir: Path | None = None
    # The slug the project lands under (the copy slug, when this
    # import is a copy): the rollback destroys it, whether the
    # restore finished or failed midway — _destroy_project is a
    # no-op when the project was never created, so destroying
    # unconditionally is safe.
    restore_slug = copy_slug or project_slug
    restore_block = proj
    if collision_mode == "copy":
        # The copy lands under its own slug, with its own display
        # name: a default display (equal to the slug) becomes the
        # new slug; a custom one gains "(copy)".
        restore_block = dict(proj)
        restore_block["name"] = copy_slug
        display = proj.get("display_name", project_slug)
        restore_block["display_name"] = (
            copy_slug if display == project_slug
            else f"{display} (copy)"
        )
    try:
        if not profile_existed:
            _create_profile_from_manifest(store, slug, prof)
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
        if collision_mode == "replace":
            # T117 replace: the old project goes to the trash
            # first, so the import can land — and a failed import
            # moves it back, so a replace that fails loses nothing.
            replaced_dir = store.project_dir(slug, project_slug)
            replaced_trash = store.delete_project(slug, project_slug)
        restored = _restore_project_record(
            store, slug, restore_block, path, path, warnings, progress,
        )
        created = restored["project"]
    except BaseException:
        # Roll back what this import created, best effort: a failed
        # import leaves the home exactly as it was. The destroy
        # path (not the trash): a rollback must not leave a trash
        # folder behind. A take-merge is unwound the same way, so
        # the profile keeps the values it had before the import. A
        # replaced project is moved back from the trash.
        try:
            store._destroy_project(slug, restore_slug)
        except Exception:
            pass
        if replaced_trash is not None and replaced_dir is not None:
            try:
                replaced_trash.rename(replaced_dir)
            except Exception:
                pass
        if merged_profile and merged_before is not None:
            try:
                store.update_profile(slug, **merged_before)
            except Exception:
                pass
        if created_profile:
            try:
                store._destroy_profile(slug)
            except Exception:
                pass
        raise
    result = {
        "profile": slug,
        "profile_existed": profile_existed,
        "profile_diff": profile_diff,
        "profile_choice": choice,
        "project": created["name"],
        "dataset_ref": restored["dataset_ref"],
        "dataset_missing": restored["dataset_missing"],
        "warnings": warnings,
    }
    if collision_mode is not None:
        result["collision"] = collision_mode
        if collision_mode == "copy":
            result["copy_of"] = project_slug
        if replaced_trash is not None:
            result["replaced_trash"] = str(replaced_trash)
    return result


def import_profile_export(
    store: Store,
    path: str | Path,
    profile_choice: str | None = None,
    on_profile_conflict=None,
    installed_models: list[str] | None = None,
    on_progress=None,
    should_stop=None,
) -> dict:
    """Import a profile package (T86) into this home: the profile
    (created, or merged per T57 when it already exists) and every
    project the package carries, each restored like a project
    import (weights, checkpoints, notes, probe results, sleep
    cycles, timestamps). Returns {"profile": ..., "profile_existed":
    ..., "profile_diff": ..., "profile_choice": ..., "projects":
    [slugs], "dataset_missing": bool, "datasets_missing": [slugs],
    "warnings": [...]}.

    Every project's settings are validated and every name is
    checked for a collision BEFORE anything is created: a profile
    import refuses while any of its projects already exists (the
    caller says which ones — import them one at a time as project
    packages for the copy/replace choice). Atomic like the project
    import: a failure anywhere removes every project and profile
    this import created, and a take-merge is unwound.
    """
    if profile_choice is not None and profile_choice not in ("keep", "take"):
        raise StellaError(
            f"profile_choice must be 'keep' or 'take', "
            f"not {profile_choice!r}"
        )
    path = Path(path).expanduser()
    manifest = verify_export(path)
    if manifest.get("kind") != PROFILE_PACKAGE_KIND:
        raise StellaError(
            "this is a project package, not a profile package. "
            "Import it as a project."
        )
    prof = manifest["profile"]
    blocks = manifest.get("projects", [])
    slug = validate_slug(prof["name"], "profile name in export")
    # Validate every project's settings and names BEFORE creating
    # anything, so a bad block cannot strand a half-created
    # profile behind it.
    names = []
    for proj in blocks:
        name = validate_slug(proj.get("name", ""), "project name in export")
        merged_settings = dict(DEFAULT_SETTINGS)
        merged_settings.update(proj.get("settings") or {})
        validate_settings(merged_settings)
        names.append(name)
    # And refuse while any project already exists (T117's
    # copy/replace choice is per-project, so it lives on the
    # project import, not here).
    existing = [
        name for name in names
        if (store.project_dir(slug, name) / "project.json").is_file()
    ]
    if existing:
        raise StellaError(
            f"these projects already exist in profile {slug!r}: "
            f"{', '.join(existing)}. Delete or rename them first, "
            "or import the profile on its own."
        )
    warnings: list[str] = []
    if installed_models:
        tag = prof.get("ollama_tag", "")
        if tag and tag not in installed_models:
            warnings.append(
                f"the base model {tag!r} is not installed on this "
                "PC. Pull it before training."
            )
    (
        profile_existed, profile_diff, choice, local_block,
    ) = _profile_merge_decision(
        store, slug, prof, profile_choice, on_profile_conflict, warnings
    )
    payload_dirs = [path / "projects" / name for name in names]
    progress = _CopyProgress(
        _import_total_bytes(path, payload_dirs), on_progress, should_stop,
    )
    created_profile = False
    created_projects: list[str] = []
    merged_profile = False
    merged_before: dict | None = None
    datasets_missing: list[str] = []
    try:
        if not profile_existed:
            _create_profile_from_manifest(store, slug, prof)
            created_profile = True
        elif choice == "take":
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
        for proj, name in zip(blocks, names):
            # The name is recorded BEFORE the restore: a restore
            # that fails midway still created the project, and the
            # rollback must remove it. _destroy_project is a no-op
            # when the create itself failed, so recording first is
            # safe.
            created_projects.append(name)
            restored = _restore_project_record(
                store, slug, proj, path, path / "projects" / name,
                warnings, progress,
            )
            if restored["dataset_missing"]:
                datasets_missing.append(restored["project"]["name"])
    except BaseException:
        for name in reversed(created_projects):
            try:
                store._destroy_project(slug, name)
            except Exception:
                pass
        if merged_profile and merged_before is not None:
            try:
                store.update_profile(slug, **merged_before)
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
        "projects": created_projects,
        "dataset_missing": bool(datasets_missing),
        "datasets_missing": datasets_missing,
        "warnings": warnings,
    }
