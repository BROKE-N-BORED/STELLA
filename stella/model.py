"""STELLA data model — profiles and projects on disk.

Home layout (default ~/.stella, overridable with STELLA_HOME):

    <home>/
      profiles/
        <profile-slug>/
          profile.json        # manifest: role, Ollama tag, base ref, config
          projects/
            <project-slug>/
              project.json    # manifest: dataset, settings, metamorph block
              checkpoints/    # training checkpoints (step-N folders)
              notes.md        # free-form notes

Everything is plain JSON + Markdown so a user can read or fix it by hand.
The base model is NEVER touched: Stella only stores a reference to it
(an Ollama tag or a local path string). All writes stay inside the home
dir — names are slugs, paths are containment-checked.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .autoconfig import compute_settings, measure_pc

STELLA_VERSION = "0.19.0"

# Slug: lowercase letters, digits, dash, underscore. Must start alnum.
# No dots, no slashes — a slug can never climb out of its directory.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MAX_SLUG_LEN = 64

# MetaMorphAi modes (structure only in v0.1 — no codec yet).
METAMORPH_MODES = ("morph", "compress", "both")
DEFAULT_METAMORPH_MODE = "morph"

# Canonical roles / Forge seats (T116): the one seat vocabulary,
# shared with Forge — the role field offers this list everywhere
# it appears, and the rename plan lands on it. The list is the
# roster's seat vocabulary; it is UNCONFIRMED with Joshua (no
# approver was awake when it landed — see the CHANGELOG), so a
# role outside it is still allowed, just flagged as custom.
CANONICAL_ROLES = (
    "driver", "reviewer", "vision", "fast", "tester",
    "all-rounder", "utility",
)

# Forge's governing seats (T116, reusing v0.16.0's T90 set): the
# seats whose models must NOT regain refusals — driver, reviewer,
# tester, fast. probe.GOVERING_ROLES is this same tuple; the
# governing-seat marker on a profile may only name one of these.
GOVERNING_SEATS = ("driver", "reviewer", "tester", "fast")

# Tag/base markers that say a base is abliterated (T116): a
# heuristic, because "abliterated" has no stored flag — the tag
# or base ref carries it ("minicpm5-heretic", "uncensored",
# "abliterated"). Matched as substrings, lowercased, against the
# tag and the base ref.
ABLITERATED_MARKERS = ("heretic", "uncensored", "abliterat")


def is_custom_role(role) -> bool:
    """True when a role is set but is not one of the canonical
    seats (T116): still allowed, just flagged as custom. A blank
    role is not custom — it is unset."""
    if not isinstance(role, str):
        return False
    role = role.strip().lower()
    return bool(role) and role not in CANONICAL_ROLES


def looks_abliterated(profile: dict) -> bool:
    """True when the base looks abliterated (T116): one of the
    ABLITERATED_MARKERS appears in the tag or the base ref. A
    heuristic — there is no stored abliteration flag, so a base
    that is abliterated without saying so in its name reads as
    stock, and the warning fires. That direction is the safe one:
    a warning that needn't have fired is an annoyance, a warning
    that didn't fire when it should breaks the seat."""
    text = " ".join(
        str((profile or {}).get(key) or "")
        for key in ("ollama_tag", "base_ref")
    ).lower()
    return any(marker in text for marker in ABLITERATED_MARKERS)


def governing_seat_warning(profile: dict) -> str | None:
    """The pre-train warning for a governing-seat profile (T116),
    or None when no warning is due. Fires only when a governing
    seat is MARKED on the profile (the governing_seat field) and
    the base is not abliterated — a governing ROLE alone does not
    warn here (the probe gates governing roles at probe time, T90;
    the marker is the explicit binding). The text names the seat
    and the base."""
    seat = str((profile or {}).get("governing_seat") or "").strip().lower()
    if seat not in GOVERNING_SEATS:
        return None
    if looks_abliterated(profile):
        return None
    base = (
        (profile or {}).get("base_ref")
        or (profile or {}).get("ollama_tag")
        or "not set"
    )
    return (
        f"This profile is bound for the {seat} seat in Code Forge, "
        "which needs an abliterated base, but its base is "
        f"{base} (no abliteration marker in the tag or base ref). "
        "Training on a stock base for a governing seat teaches it "
        "to refuse ordinary work."
    )


# Training methods. "full" is listed so old projects still show it,
# but it does not run on this PC (train.py always trains LoRA).
SETTING_METHODS = ("lora", "full")

# Project lifecycle statuses (T53, reconciled). The task's enum
# (draft/ready/training/done/failed/exported) and the engine's
# (draft/training/paused/trained/exported) disagreed; this is the
# one vocabulary now:
#   draft    — just created, not started
#   ready    — the user marked it ready to train (draft -> ready is
#              the only user-driven transition)
#   training — a run is in progress
#   paused   — a run stopped cleanly (Pause / Ctrl+C) and can resume
#   done     — a run finished (the engine's old word was "trained")
#   failed   — a run errored (a crash is not a pause)
#   exported — the adapter was exported to GGUF
# Transitions are driven by actions, never free text: training
# sets training/paused/done/failed, GGUF export sets exported,
# the user sets ready. `paused` has no slot in the task's enum but
# pause/resume is a real state, so it stays.
PROJECT_STATUSES = (
    "draft", "ready", "training", "paused", "done", "failed", "exported",
)

# Old status words, normalized on read, never persisted (T53):
# v0.1-v0.12 stored "trained" for a finished run; it reads as
# "done" now.
LEGACY_STATUS_ALIASES = {"trained": "done"}


def normalize_status(status) -> str:
    """The canonical status for a stored value (T53): a legacy
    alias maps to its current word, anything else passes through
    unchanged (validation happens on write, not on read)."""
    if isinstance(status, str):
        return LEGACY_STATUS_ALIASES.get(status, status)
    return status


# Statuses that claim a trained adapter exists (T41): a package
# claiming one of these without weights imports as a draft — a
# project with no weights must not claim to be finished.
WEIGHT_STATUSES = ("done", "exported")

# Where a project's settings came from: "auto" (measured from this
# PC, re-resolved at each run start) or "manual" (set by a human —
# the Project window, the chat, an import — never recomputed).
# Projects written before v0.9 have no field and read as "manual",
# so old hand-tuned settings are never overwritten.
SETTINGS_SOURCES = ("auto", "manual")

# Settings the model validates, with their allowed ranges. These are
# the chat's ranges (chat_agent.SETTING_RULES imports this table) —
# one rule, everywhere: GUI, CLI, imports, and hand-edits all get
# the same answer. Each rule is (kind, low, high).
SETTING_RULES = {
    "rank": ("int", 1, 64),
    "learning_rate": ("float", 0.0, 1.0),
    "epochs": ("int", 1, 100),
    "batch_size": ("int", 1, 32),
    "grad_accum": ("int", 1, 64),
    "max_seq_len": ("int", 128, 32768),
    "checkpoint_steps": ("int", 0, 10000),
    "val_fraction": ("float", 0.0, 0.5),
    "warmup_steps": ("int", 0, 1000),
    "seed": ("int", -2**31, 2**31 - 1),
}

# Default training settings for a new project — the knobs the Item 3
# training engine drives (stella/train.py). Micro-LoRA defaults for a
# CPU-only 8 GB machine: rank 8, batch 1, grad accumulation 8, short
# sequences, frequent checkpoints.
DEFAULT_SETTINGS = {
    "method": "lora",
    "rank": 8,
    "learning_rate": 0.0002,
    "epochs": 3,
    "batch_size": 1,
    "grad_accum": 8,
    "max_seq_len": 1024,
    "checkpoint_steps": 50,
    "val_fraction": 0.1,
    "warmup_steps": 5,
    "seed": 42,
    # T114: the old "notes" key is gone — it lived in the
    # defaults but nothing read or wrote it (the metamorph
    # notes and notes.md are the real notes). validate_settings
    # drops it from old manifests on sight, never persisting it.
    # T34: hand-supplied LoRA target layers for architectures the
    # auto-detection does not recognize. Empty means "find them
    # yourself" — the normal case; a non-empty list is used as-is.
    "target_modules": [],
}


class StellaError(Exception):
    """User-facing Stella error (bad name, missing profile, bad manifest)."""


def default_home() -> Path:
    """The Stella home dir: STELLA_HOME wins, else ~/.stella."""
    import os

    override = os.environ.get("STELLA_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".stella"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_slug(name: str, kind: str = "name") -> str:
    """Check a profile/project slug. Returns the slug or raises."""
    if not isinstance(name, str):
        raise StellaError(f"{kind} must be text")
    slug = name.strip().lower()
    if not slug:
        raise StellaError(f"{kind} must not be empty")
    if len(slug) > MAX_SLUG_LEN:
        raise StellaError(f"{kind} is too long (max {MAX_SLUG_LEN})")
    if not SLUG_RE.match(slug):
        raise StellaError(
            f"{kind} {name!r} is not valid. Use lowercase letters, "
            "numbers, dashes and underscores, starting with a letter "
            "or number"
        )
    return slug


def slug_from_model(model: str) -> str:
    """Derive a profile slug from a model id (Ollama tag or HF repo).

    Takes the last path segment (drops the namespace), lowercases it,
    and turns every run of non-slug characters into one dash:
    ``LiquidAI/LFM3-1.7B`` -> ``lfm3-1-7b``,
    ``maternion/minicpm5-heretic:2b`` -> ``minicpm5-heretic-2b``,
    ``qwen3.5:4b`` -> ``qwen3-5-4b``. Always returns a valid slug.
    """
    value = model.strip().lower()
    if "/" in value:
        value = value.rsplit("/", 1)[1]
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value:
        value = "profile"
    value = value[:MAX_SLUG_LEN].rstrip("-")
    return value or "profile"


def metamorph_mode(data: dict) -> str:
    """The metamorph mode of a project dict, defensively (T37).

    The ONE reader for the block: the model, the CLI list, the GUI
    list + detail fill, export, and verify all go through here.
    Missing, null, wrong-type, or unknown-mode blocks all yield the
    default ("morph") instead of a crash. Use metamorph_problem()
    when the caller needs to know the block was broken.
    """
    if not isinstance(data, dict):
        return DEFAULT_METAMORPH_MODE
    block = data.get("metamorph")
    if not isinstance(block, dict):
        return DEFAULT_METAMORPH_MODE
    mode = block.get("mode", DEFAULT_METAMORPH_MODE)
    if mode not in METAMORPH_MODES:
        return DEFAULT_METAMORPH_MODE
    return mode


def metamorph_problem(data: dict) -> str | None:
    """Why a project's metamorph block is broken, in plain words —
    or None when it is fine (including absent, which just means the
    default). The GUI tree and the CLI list show this as a warning
    instead of dying on the row (T39)."""
    if not isinstance(data, dict):
        return "the project record is not set right"
    if "metamorph" not in data:
        return None
    block = data.get("metamorph")
    if not isinstance(block, dict):
        return "the metamorph setting is not set right"
    mode = block.get("mode", DEFAULT_METAMORPH_MODE)
    if mode not in METAMORPH_MODES:
        return (
            f"metamorph mode {mode!r} is not one of "
            f"{', '.join(METAMORPH_MODES)}"
        )
    return None


def validate_settings(settings: dict) -> dict:
    """Validate a full settings dict against SETTING_RULES (T6).

    Returns a cleaned copy (numbers coerced to their kind). Every
    rejection is a StellaError naming the key and what is accepted:
    unknown keys, a bad method, a wrong type, a non-finite number,
    or a value outside its range. The GUI, CLI, imports, and
    hand-edits all hit these same rules through create/update.
    """
    if not isinstance(settings, dict):
        raise StellaError("settings must be an object")
    cleaned: dict = {}
    for key, value in settings.items():
        if key == "method":
            if value not in SETTING_METHODS:
                raise StellaError(
                    f"method must be one of {', '.join(SETTING_METHODS)}, "
                    f"not {value!r}"
                )
            cleaned[key] = value
            continue
        if key == "notes":
            # T114: the dead settings key, dropped on sight — an
            # old manifest (or an old package) carrying it
            # migrates by being read, never persisted again.
            continue
        if key == "target_modules":
            # T34: a list of layer leaf names, or empty for
            # auto-detection. Each name is checked against the
            # model at train time; here only the shape is checked.
            if not isinstance(value, list):
                raise StellaError(
                    "target_modules must be a list of layer names, "
                    f"not {value!r}"
                )
            names = []
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise StellaError(
                        "target_modules must be a list of layer names, "
                        f"not {value!r}"
                    )
                names.append(item.strip())
            cleaned[key] = names
            continue
        rule = SETTING_RULES.get(key)
        if rule is None:
            raise StellaError(
                f"there is no setting called {key!r}. The settings are: "
                f"{', '.join(sorted(SETTING_RULES))}, method, "
                "target_modules"
            )
        kind, low, high = rule
        if isinstance(value, bool):
            raise StellaError(f"{key} must be a number, not {value!r}")
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError, OverflowError):
            raise StellaError(f"{key} must be a number, not {value!r}") from None
        if kind == "int" and float(value) != number:
            raise StellaError(
                f"{key} must be a whole number, not {value!r}"
            )
        if kind == "float" and not math.isfinite(number):
            raise StellaError(
                f"{key} must be a real number, not {value!r}"
            )
        if not low <= number <= high:
            raise StellaError(
                f"{key} must be between {low} and {high}, not {value!r}"
            )
        cleaned[key] = number
    return cleaned


def _check_inside(home: Path, path: Path) -> Path:
    """Resolve `path` and require it to sit inside `home`."""
    home_r = home.resolve()
    path_r = path.resolve() if path.exists() else (home_r / path.name).resolve()
    # For not-yet-existing paths, resolve the parent chain manually.
    if not path.exists():
        parent = path.parent
        while not parent.exists():
            parent = parent.parent
        path_r = (parent.resolve() / path.relative_to(parent)).resolve()
    if path_r != home_r and home_r not in path_r.parents:
        raise StellaError(f"path escapes the Stella home: {path}")
    return path_r


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = json.dumps(data, indent=2, sort_keys=True, allow_nan=False)
    except ValueError as exc:
        # A NaN/inf value must never reach disk as bare NaN (not
        # valid JSON, and the next read would misbehave).
        raise StellaError(
            "cannot save: a value is not a real number "
            "(NaN or infinity cannot be stored)"
        ) from exc
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StellaError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StellaError(f"{path.name} must hold a JSON object")
    return data


def _migrate_project_file(data: dict, manifest: Path) -> None:
    """T114 migration: drop the dead settings["notes"] key from an
    old manifest, in memory and on disk. Only writes when the key
    is actually there, so a migrated manifest is never rewritten.
    The write is best effort — a failure leaves the in-memory
    record clean (and the next update persists it), so a write
    problem never turns a healthy project into a damaged row."""
    settings = data.get("settings")
    if isinstance(settings, dict) and "notes" in settings:
        del settings["notes"]
        try:
            _write_json(manifest, data)
        except StellaError:
            pass


class Store:
    """All profile/project storage. One Store = one home dir."""

    def __init__(self, home: Path | str | None = None):
        self.home = Path(home) if home is not None else default_home()
        self.profiles_dir = self.home / "profiles"
        # Deleted profiles and projects go here (T23), dated, so a
        # misclick past Yes is recoverable: move the folder back.
        self.trash_dir = self.home / "trash"

    # -- trash ------------------------------------------------------
    def _trash_name(self, base: str) -> str:
        """A dated trash folder name: <base>-YYYYMMDD-HHMMSS, with
        a -2, -3 suffix when two deletes land in the same second."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        name = f"{base}-{stamp}"
        n = 2
        while (self.trash_dir / name).exists():
            name = f"{base}-{stamp}-{n}"
            n += 1
        return name

    def _move_to_trash(self, folder: Path, base: str) -> Path:
        """Move a profile/project folder into the trash. Returns
        the trash path."""
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        dest = self.trash_dir / self._trash_name(base)
        folder.rename(dest)
        return dest

    def list_trash(self) -> list[dict]:
        """Every trashed item: {"name", "kind", "profile",
        "project", "trashed", "path"}. The kind and names come
        from the manifest inside the folder, so a hand-moved
        folder still reads right; the date comes from the folder
        name."""
        out = []
        if not self.trash_dir.is_dir():
            return out
        for d in sorted(self.trash_dir.iterdir()):
            if not d.is_dir():
                continue
            entry = {
                "name": d.name,
                "kind": "unknown",
                "profile": "",
                "project": "",
                "trashed": "",
                "path": str(d),
            }
            match = re.match(
                r"^(.+)-(\d{8})-(\d{6})(?:-\d+)?$", d.name
            )
            if match:
                date, clock = match.group(2), match.group(3)
                entry["trashed"] = (
                    f"{date[:4]}-{date[4:6]}-{date[6:]} "
                    f"{clock[:2]}:{clock[2:4]}:{clock[4:]}"
                )
            prof_manifest = d / "profile.json"
            proj_manifest = d / "project.json"
            try:
                if prof_manifest.is_file():
                    data = _read_json(prof_manifest)
                    entry["kind"] = "profile"
                    entry["profile"] = data.get("name", d.name)
                elif proj_manifest.is_file():
                    data = _read_json(proj_manifest)
                    entry["kind"] = "project"
                    entry["profile"] = data.get("profile", "")
                    entry["project"] = data.get("name", d.name)
            except StellaError:
                pass
            out.append(entry)
        return out

    def purge_trash(self, name: str) -> None:
        """Delete one trashed item forever (T23). The name must be
        a plain trash entry name — never a path."""
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise StellaError(f"not a trash item: {name!r}")
        target = self.trash_dir / name
        if not target.is_dir():
            raise StellaError(f"nothing in the trash named {name!r}")
        shutil.rmtree(target)

    def empty_trash(self) -> int:
        """Delete everything in the trash forever. Returns how many
        items were removed."""
        if not self.trash_dir.is_dir():
            return 0
        count = 0
        for d in list(self.trash_dir.iterdir()):
            if d.is_dir():
                shutil.rmtree(d)
                count += 1
            elif d.is_file():
                d.unlink()
                count += 1
        return count

    def _destroy_profile(self, slug: str) -> None:
        """Remove a profile permanently, no trash (T23). Only the
        import rollback uses this: a failed import must leave the
        home exactly as it was, and trash would leave a folder
        behind. Everything else deletes through the trash."""
        slug = validate_slug(slug, "profile name")
        pdir = self.profile_dir(slug)
        if (pdir / "profile.json").exists():
            shutil.rmtree(pdir)

    def _destroy_project(self, profile: str, project: str) -> None:
        """Remove a project permanently, no trash (T23) — see
        _destroy_profile."""
        pdir = self.project_dir(profile, project)
        if (pdir / "project.json").exists():
            shutil.rmtree(pdir)

    # -- paths ------------------------------------------------------
    def profile_dir(self, slug: str) -> Path:
        slug = validate_slug(slug, "profile name")
        return _check_inside(self.home, self.profiles_dir / slug)

    def project_dir(self, profile: str, project: str) -> Path:
        pslug = validate_slug(project, "project name")
        return _check_inside(
            self.home, self.profile_dir(profile) / "projects" / pslug
        )

    # -- profiles ---------------------------------------------------
    def list_profiles(self) -> list[dict]:
        out = []
        if not self.profiles_dir.is_dir():
            return out
        for d in sorted(self.profiles_dir.iterdir()):
            manifest = d / "profile.json"
            if d.is_dir() and manifest.is_file():
                try:
                    out.append(_read_json(manifest))
                except StellaError as exc:
                    # A broken manifest is a damaged row, not a skip
                    # (T3): the folder is still on disk and the UI
                    # must say so, with the error and the slug.
                    out.append(
                        {
                            "name": d.name,
                            "_damaged": True,
                            "_error": str(exc),
                        }
                    )
        return out

    def get_profile(self, slug: str) -> dict:
        slug = validate_slug(slug, "profile name")
        manifest = self.profile_dir(slug) / "profile.json"
        if not manifest.is_file():
            raise StellaError(f"no profile named {slug!r}")
        data = _read_json(manifest)
        data.setdefault("name", slug)
        return data

    def create_profile(
        self,
        slug: str,
        *,
        ollama_tag: str = "",
        role: str = "",
        display_name: str = "",
        base_ref: str = "",
        config: dict | None = None,
        processor: str = "",
        dependencies: list | None = None,
        governing_seat: str = "",
        created: str | None = None,
        updated: str | None = None,
    ) -> dict:
        slug = validate_slug(slug, "profile name")
        pdir = self.profile_dir(slug)
        if (pdir / "profile.json").exists():
            raise StellaError(f"profile {slug!r} already exists")
        seat = (governing_seat or "").strip().lower()
        if seat and seat not in GOVERNING_SEATS:
            raise StellaError(
                f"governing seat must be one of "
                f"{', '.join(GOVERNING_SEATS)}, not {governing_seat!r}"
            )
        data = {
            "stella_version": STELLA_VERSION,
            "kind": "profile",
            "name": slug,
            "display_name": display_name or slug,
            "role": role or "",
            "ollama_tag": ollama_tag or "",
            "base_ref": base_ref or ollama_tag or "",
            "processor": processor or "",
            "config": dict(config or {}),
            "dependencies": list(dependencies or []),
            # T116: the governing seat this profile is bound for,
            # when set ("" means not bound). A bound profile warns
            # before training unless its base is abliterated, and
            # its probe runs as a gate (T90).
            "governing_seat": seat,
            # T118: an import restores the original timestamps
            # instead of stamping fresh ones, so an imported
            # profile keeps its history. Anything else creates
            # with "now" — a non-text stamp is ignored, never
            # stored, so a hand-edited manifest cannot plant a
            # bad timestamp.
            "created": (
                created if isinstance(created, str) and created
                else utc_now()
            ),
        }
        if isinstance(updated, str) and updated:
            data["updated"] = updated
        (pdir / "projects").mkdir(parents=True, exist_ok=True)
        _write_json(pdir / "profile.json", data)
        return data

    def update_profile(self, slug: str, **fields) -> dict:
        data = self.get_profile(slug)
        allowed = {
            "display_name",
            "role",
            "ollama_tag",
            "base_ref",
            "processor",
            "config",
            "dependencies",
            "governing_seat",
        }
        old_tag = data.get("ollama_tag", "")
        old_base = data.get("base_ref", "")
        for key, value in fields.items():
            if key not in allowed:
                raise StellaError(f"cannot change {key!r} on a profile")
            if key == "governing_seat":
                # T116: the marker names a governing seat, or ""
                # for not bound. Anything else is refused, not
                # stored — a typo'd seat would silently never warn.
                seat = (value or "").strip().lower() if isinstance(value, str) else ""
                if value not in ("", None) and seat not in GOVERNING_SEATS:
                    raise StellaError(
                        "governing seat must be one of "
                        f"{', '.join(GOVERNING_SEATS)}, not {value!r}"
                    )
                data[key] = seat
                continue
            data[key] = value
        # T54 sync rule (interim, until Joshua decides drop vs
        # define): changing the tag updates base_ref unless the
        # user deliberately split them. A stored base_ref that
        # equals the OLD tag (or is empty) means "not split" — it
        # follows the new tag. A stored base_ref that differs from
        # the old tag is a deliberate split and stays. An explicit
        # base_ref in the same call always wins.
        if (
            "ollama_tag" in fields
            and "base_ref" not in fields
            and fields["ollama_tag"] != old_tag
            and (not old_base or old_base == old_tag)
        ):
            data["base_ref"] = fields["ollama_tag"]
        data["updated"] = utc_now()
        _write_json(self.profile_dir(slug) / "profile.json", data)
        return data

    def rename_profile(self, slug: str, new_slug: str) -> dict:
        slug = validate_slug(slug, "profile name")
        new_slug = validate_slug(new_slug, "new profile name")
        src = self.profile_dir(slug)
        dst = self.profile_dir(new_slug)
        if not (src / "profile.json").exists():
            raise StellaError(f"no profile named {slug!r}")
        if (dst / "profile.json").exists():
            raise StellaError(f"profile {new_slug!r} already exists")
        data = self.get_profile(slug)
        data["name"] = new_slug
        if data.get("display_name") == slug:
            data["display_name"] = new_slug
        data["updated"] = utc_now()
        # Rename the projects' stored profile pointer too. A
        # damaged project (T3) cannot be read, so its pointer stays
        # until the manifest is fixed — it must not abort the rename.
        for proj in self.list_projects(slug):
            if proj.get("_damaged"):
                continue
            pdata = self.get_project(slug, proj["name"])
            pdata["profile"] = new_slug
            _write_json(
                src / "projects" / proj["name"] / "project.json", pdata
            )
        _write_json(src / "profile.json", data)
        src.rename(dst)
        return self.get_profile(new_slug)

    def delete_profile(self, slug: str) -> Path:
        """Delete a profile — to the trash (T23), not gone: the
        folder moves to trash/<slug>-<date>/ with its projects,
        notes, and checkpoints intact, so a misclick is
        recoverable. Returns the trash path. Purge (delete
        forever) is purge_trash."""
        slug = validate_slug(slug, "profile name")
        pdir = self.profile_dir(slug)
        if not (pdir / "profile.json").exists():
            raise StellaError(f"no profile named {slug!r}")
        return self._move_to_trash(pdir, slug)

    def purge_profile(self, slug: str) -> None:
        """Delete a profile forever, no trash (T87 `--purge`):
        the CLI's permanent removal. The profile must exist."""
        slug = validate_slug(slug, "profile name")
        pdir = self.profile_dir(slug)
        if not (pdir / "profile.json").exists():
            raise StellaError(f"no profile named {slug!r}")
        self._destroy_profile(slug)

    def clone_profile(
        self, slug: str, new_slug: str, *, copy_projects: bool = False
    ) -> dict:
        """Copy a profile under a new name (T121): the same tag,
        base, role, processor, config, and dependencies, under
        its own name, with zero projects by default. The
        processor value is copied VERBATIM — its meaning is
        undecided (T128, hard-gated), so the clone never
        interprets it. The governing-seat marker is NOT copied:
        a binding is per profile, and the new profile's seat is
        the user's call. With copy_projects, each project is
        cloned too (T112's clone: same dataset/settings/mode, no
        checkpoints, fresh notes). The original is untouched. A
        name that already exists is refused, like any other
        create."""
        slug = validate_slug(slug, "profile name")
        new_slug = validate_slug(new_slug, "new profile name")
        src = self.get_profile(slug)
        # A custom display name travels; a default one (equal to
        # the slug) becomes the new slug instead of lying about
        # which profile it is — the same rule as clone_project.
        display = src.get("display_name", slug)
        if display == slug:
            display = ""
        data = self.create_profile(
            new_slug,
            ollama_tag=src.get("ollama_tag", ""),
            role=src.get("role", ""),
            display_name=display,
            base_ref=src.get("base_ref", ""),
            config=dict(src.get("config") or {}),
            processor=src.get("processor", ""),
            dependencies=list(src.get("dependencies") or []),
        )
        if copy_projects:
            try:
                for proj in self.list_projects(slug):
                    if proj.get("_damaged"):
                        continue
                    self.clone_project(
                        slug, proj["name"], proj["name"],
                        target_profile=new_slug,
                    )
            except BaseException:
                # A failed project copy leaves nothing behind:
                # the half-cloned profile is destroyed, so a
                # clone either lands whole or not at all.
                self._destroy_profile(new_slug)
                raise
        return data

    # -- projects ---------------------------------------------------
    def list_projects(self, profile: str) -> list[dict]:
        slug = validate_slug(profile, "profile name")
        pdir = self.profile_dir(slug) / "projects"
        if not pdir.is_dir():
            return []
        out = []
        for d in sorted(pdir.iterdir()):
            manifest = d / "project.json"
            if d.is_dir() and manifest.is_file():
                try:
                    entry = _read_json(manifest)
                    # T114 migration: an old manifest's dead
                    # settings["notes"] key is dropped here, in
                    # memory and on disk. It runs BEFORE the
                    # status normalization below, so the
                    # migration write never persists the new
                    # status word early (T53 keeps that
                    # in-memory-only until the next real write).
                    _migrate_project_file(entry, manifest)
                    # Legacy statuses read as their current word
                    # (T53), in memory only.
                    if "status" in entry:
                        entry["status"] = normalize_status(
                            entry["status"]
                        )
                    out.append(entry)
                except StellaError as exc:
                    # A broken manifest is a damaged row, not a skip
                    # (T3) — see list_profiles.
                    out.append(
                        {
                            "name": d.name,
                            "_damaged": True,
                            "_error": str(exc),
                        }
                    )
        return out

    def get_project(self, profile: str, project: str) -> dict:
        project = validate_slug(project, "project name")
        manifest = self.project_dir(profile, project) / "project.json"
        if not manifest.is_file():
            raise StellaError(
                f"no project named {project!r} in profile {profile!r}"
            )
        data = _read_json(manifest)
        data.setdefault("name", project)
        data.setdefault("profile", validate_slug(profile, "profile name"))
        data.setdefault("status", "draft")
        # T114 migration: an old manifest's dead settings["notes"]
        # key is dropped here, in memory and on disk.
        _migrate_project_file(data, manifest)
        # A legacy status reads as its current word (T53): a
        # v0.1-v0.12 "trained" project is "done" now. The file on
        # disk is untouched — the next write persists the new word.
        data["status"] = normalize_status(data.get("status", "draft"))
        # Default the metamorph block in memory (T37): a missing,
        # null, or wrong-type block reads as the default instead of
        # crashing the next reader. The file on disk is untouched —
        # the lists still see the raw block and can warn about it.
        block = data.get("metamorph")
        if not isinstance(block, dict):
            data["metamorph"] = {"mode": DEFAULT_METAMORPH_MODE, "notes": ""}
        elif block.get("mode") not in METAMORPH_MODES:
            block["mode"] = DEFAULT_METAMORPH_MODE
        return data

    def create_project(
        self,
        profile: str,
        slug: str,
        *,
        display_name: str = "",
        dataset_ref: str = "",
        settings: dict | None = None,
        metamorph_mode: str = "morph",
        metamorph_notes: str = "",
        created: str | None = None,
        updated: str | None = None,
    ) -> dict:
        profile = validate_slug(profile, "profile name")
        slug = validate_slug(slug, "project name")
        # The profile must exist first.
        self.get_profile(profile)
        if metamorph_mode not in METAMORPH_MODES:
            raise StellaError(
                f"metamorph mode must be one of {', '.join(METAMORPH_MODES)}"
            )
        pdir = self.project_dir(profile, slug)
        if (pdir / "project.json").exists():
            raise StellaError(
                f"project {slug!r} already exists in profile {profile!r}"
            )
        # Settings: no explicit settings means this PC picks them
        # (auto-config, measured now); explicit settings are the
        # caller's and are validated but never recomputed.
        if settings is None:
            measurement = measure_pc(self.home)
            computed = compute_settings(measurement["ram_available_gb"])
            merged = dict(DEFAULT_SETTINGS)
            merged.update(computed)
            settings_source = "auto"
        else:
            merged = dict(DEFAULT_SETTINGS)
            merged.update(settings)
            settings_source = "manual"
        merged = validate_settings(merged)
        data = {
            "stella_version": STELLA_VERSION,
            "kind": "project",
            "name": slug,
            "display_name": display_name or slug,
            "profile": profile,
            "dataset_ref": dataset_ref or "",
            "settings": merged,
            "settings_source": settings_source,
            "metamorph": {"mode": metamorph_mode, "notes": metamorph_notes or ""},
            "status": "draft",
            # T118: an import restores the original timestamps —
            # see create_profile.
            "created": (
                created if isinstance(created, str) and created
                else utc_now()
            ),
        }
        if isinstance(updated, str) and updated:
            data["updated"] = updated
        (pdir / "checkpoints").mkdir(parents=True, exist_ok=True)
        _write_json(pdir / "project.json", data)
        (pdir / "notes.md").write_text(
            f"# {display_name or slug}\n\nNotes for this fine-tune.\n",
            encoding="utf-8",
        )
        return data

    def update_project(self, profile: str, project: str, **fields) -> dict:
        data = self.get_project(profile, project)
        allowed = {
            "display_name",
            "dataset_ref",
            "settings",
            "settings_source",
            "metamorph",
            "status",
        }
        settings_changed = False
        for key, value in fields.items():
            if key not in allowed:
                raise StellaError(f"cannot change {key!r} on a project")
            if key == "metamorph":
                if not isinstance(value, dict):
                    raise StellaError("metamorph must be an object")
                # Read the stored block through the shared reader
                # (T37): a missing/null/wrong-type block defaults
                # instead of raising KeyError/TypeError.
                mode = value.get("mode", metamorph_mode(data))
                if mode not in METAMORPH_MODES:
                    raise StellaError(
                        f"metamorph mode must be one of "
                        f"{', '.join(METAMORPH_MODES)}"
                    )
                old_block = data.get("metamorph")
                old_notes = (
                    old_block.get("notes", "")
                    if isinstance(old_block, dict)
                    else ""
                )
                data["metamorph"] = {
                    "mode": mode,
                    "notes": value.get("notes", old_notes),
                }
                continue
            if key == "settings":
                if not isinstance(value, dict):
                    raise StellaError("settings must be an object")
                old = data.get("settings")
                merged = dict(old) if isinstance(old, dict) else dict(DEFAULT_SETTINGS)
                merged.update(value)
                data["settings"] = validate_settings(merged)
                settings_changed = True
                continue
            if key == "settings_source":
                if value not in SETTINGS_SOURCES:
                    raise StellaError(
                        f"settings source must be one of "
                        f"{', '.join(SETTINGS_SOURCES)}"
                    )
                data[key] = value
                continue
            if key == "status":
                # T53: status is a validated enum — anything else
                # is rejected. A legacy alias ("trained") is
                # accepted and stored as its current word ("done"),
                # never persisted as the old word. Every real
                # transition stamps status_changed.
                value = normalize_status(value)
                if value not in PROJECT_STATUSES:
                    raise StellaError(
                        f"status must be one of "
                        f"{', '.join(PROJECT_STATUSES)}, not {value!r}"
                    )
                if normalize_status(data.get("status")) != value:
                    data["status_changed"] = utc_now()
                data["status"] = value
                continue
            data[key] = value
        # Explicit settings are a human choice: the project becomes
        # manual, unless the caller named the source itself (the
        # run-start re-resolve passes "auto" back in).
        if settings_changed and "settings_source" not in fields:
            data["settings_source"] = "manual"
        data["updated"] = utc_now()
        pdir = self.project_dir(profile, project)
        _write_json(pdir / "project.json", data)
        return data

    def rename_project(self, profile: str, project: str, new_slug: str) -> dict:
        profile = validate_slug(profile, "profile name")
        project = validate_slug(project, "project name")
        new_slug = validate_slug(new_slug, "new project name")
        src = self.project_dir(profile, project)
        dst = self.project_dir(profile, new_slug)
        if not (src / "project.json").exists():
            raise StellaError(f"no project named {project!r}")
        if (dst / "project.json").exists():
            raise StellaError(f"project {new_slug!r} already exists")
        data = self.get_project(profile, project)
        data["name"] = new_slug
        if data.get("display_name") == project:
            data["display_name"] = new_slug
        data["updated"] = utc_now()
        _write_json(src / "project.json", data)
        src.rename(dst)
        return self.get_project(profile, new_slug)

    def delete_project(self, profile: str, project: str) -> Path:
        """Delete a project — to the trash (T23), not gone: the
        folder moves to trash/<profile>-<project>-<date>/ with its
        checkpoints and notes intact. Returns the trash path."""
        pdir = self.project_dir(profile, project)
        if not (pdir / "project.json").exists():
            raise StellaError(f"no project named {project!r}")
        return self._move_to_trash(
            pdir,
            f"{validate_slug(profile, 'profile name')}-"
            f"{validate_slug(project, 'project name')}",
        )

    def purge_project(self, profile: str, project: str) -> None:
        """Delete a project forever, no trash (T87 `--purge`):
        the CLI's permanent removal. The project must exist."""
        pdir = self.project_dir(profile, project)
        if not (pdir / "project.json").exists():
            raise StellaError(f"no project named {project!r}")
        self._destroy_project(profile, project)

    def clone_project(
        self, profile: str, project: str, new_slug: str,
        target_profile: str | None = None,
    ) -> dict:
        """Copy a project under a new name (T112): the same
        dataset, settings, and metamorph mode (notes included —
        they say why the mode was picked), zero checkpoints, no
        adapter, and fresh notes with a "cloned from X" header
        line. The original is untouched. A name that already
        exists is refused, like any other create. When the
        dataset file lives inside the source project (a bundled
        import), the file is copied into the clone too, so the
        clone's dataset ref still resolves. `target_profile`
        (T121) clones into a different profile — a profile clone
        copying its projects — instead of the source profile."""
        profile = validate_slug(profile, "profile name")
        project = validate_slug(project, "project name")
        new_slug = validate_slug(new_slug, "new project name")
        dst_profile = validate_slug(
            target_profile if target_profile is not None else profile,
            "profile name",
        )
        src = self.get_project(profile, project)
        block = src.get("metamorph")
        metamorph_notes = (
            block.get("notes", "")
            if isinstance(block, dict)
            else ""
        )
        # A custom display name travels; a default one (equal to
        # the slug) becomes the new slug instead of lying about
        # which project it is.
        display = src.get("display_name", project)
        if display == project:
            display = ""
        data = self.create_project(
            dst_profile,
            new_slug,
            display_name=display,
            dataset_ref=src.get("dataset_ref", ""),
            settings=dict(src.get("settings", {})),
            metamorph_mode=metamorph_mode(src),
            metamorph_notes=metamorph_notes,
        )
        ref = src.get("dataset_ref", "")
        if ref and ref == Path(ref).name:
            src_file = self.project_dir(profile, project) / ref
            if src_file.is_file():
                shutil.copy2(
                    src_file,
                    self.project_dir(dst_profile, new_slug) / ref,
                )
        self.write_notes(
            dst_profile,
            new_slug,
            f"# {data.get('display_name', new_slug)}\n\n"
            f"Cloned from {project}.\n",
        )
        return data

    # -- notes ------------------------------------------------------
    def read_notes(self, profile: str, project: str) -> str:
        pdir = self.project_dir(profile, project)
        notes = pdir / "notes.md"
        if not notes.is_file():
            return ""
        return notes.read_text(encoding="utf-8")

    def write_notes(self, profile: str, project: str, text: str) -> None:
        pdir = self.project_dir(profile, project)
        if not (pdir / "project.json").exists():
            raise StellaError(f"no project named {project!r}")
        notes = pdir / "notes.md"
        # The rotating single backup (T119): the previous version
        # is kept as notes.md.1, so a mistaken save loses nothing.
        # Restore by moving notes.md.1 back over notes.md (the
        # README documents it). No backup on the first save —
        # there is nothing previous to keep.
        if notes.is_file():
            shutil.copy2(notes, pdir / "notes.md.1")
        notes.write_text(text, encoding="utf-8")
