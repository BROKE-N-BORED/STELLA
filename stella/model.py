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
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

STELLA_VERSION = "0.6.0"

# Slug: lowercase letters, digits, dash, underscore. Must start alnum.
# No dots, no slashes — a slug can never climb out of its directory.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MAX_SLUG_LEN = 64

# MetaMorphAi modes (structure only in v0.1 — no codec yet).
METAMORPH_MODES = ("morph", "compress", "both")

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
    "notes": "",
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
            f"{kind} {name!r} is not valid — use lowercase letters, "
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
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StellaError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StellaError(f"{path.name} must hold a JSON object")
    return data


class Store:
    """All profile/project storage. One Store = one home dir."""

    def __init__(self, home: Path | str | None = None):
        self.home = Path(home) if home is not None else default_home()
        self.profiles_dir = self.home / "profiles"

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
                except StellaError:
                    continue  # skip a broken manifest, don't crash the list
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
    ) -> dict:
        slug = validate_slug(slug, "profile name")
        pdir = self.profile_dir(slug)
        if (pdir / "profile.json").exists():
            raise StellaError(f"profile {slug!r} already exists")
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
            "created": utc_now(),
        }
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
        }
        for key, value in fields.items():
            if key not in allowed:
                raise StellaError(f"cannot change {key!r} on a profile")
            data[key] = value
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
        # Rename the projects' stored profile pointer too.
        for proj in self.list_projects(slug):
            pdata = self.get_project(slug, proj["name"])
            pdata["profile"] = new_slug
            _write_json(
                src / "projects" / proj["name"] / "project.json", pdata
            )
        _write_json(src / "profile.json", data)
        src.rename(dst)
        return self.get_profile(new_slug)

    def delete_profile(self, slug: str) -> None:
        slug = validate_slug(slug, "profile name")
        pdir = self.profile_dir(slug)
        if not (pdir / "profile.json").exists():
            raise StellaError(f"no profile named {slug!r}")
        shutil.rmtree(pdir)

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
                    out.append(_read_json(manifest))
                except StellaError:
                    continue
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
        merged = dict(DEFAULT_SETTINGS)
        merged.update(settings or {})
        data = {
            "stella_version": STELLA_VERSION,
            "kind": "project",
            "name": slug,
            "display_name": display_name or slug,
            "profile": profile,
            "dataset_ref": dataset_ref or "",
            "settings": merged,
            "metamorph": {"mode": metamorph_mode, "notes": metamorph_notes or ""},
            "status": "draft",
            "created": utc_now(),
        }
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
            "metamorph",
            "status",
        }
        for key, value in fields.items():
            if key not in allowed:
                raise StellaError(f"cannot change {key!r} on a project")
            if key == "metamorph":
                if not isinstance(value, dict):
                    raise StellaError("metamorph must be an object")
                mode = value.get("mode", data["metamorph"]["mode"])
                if mode not in METAMORPH_MODES:
                    raise StellaError(
                        f"metamorph mode must be one of "
                        f"{', '.join(METAMORPH_MODES)}"
                    )
                data["metamorph"] = {
                    "mode": mode,
                    "notes": value.get("notes", data["metamorph"].get("notes", "")),
                }
                continue
            if key == "settings":
                if not isinstance(value, dict):
                    raise StellaError("settings must be an object")
                merged = dict(data.get("settings", {}))
                merged.update(value)
                data["settings"] = merged
                continue
            data[key] = value
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

    def delete_project(self, profile: str, project: str) -> None:
        pdir = self.project_dir(profile, project)
        if not (pdir / "project.json").exists():
            raise StellaError(f"no project named {project!r}")
        shutil.rmtree(pdir)

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
        (pdir / "notes.md").write_text(text, encoding="utf-8")
