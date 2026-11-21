"""STELLA command line.

    stella profiles                       list profiles (role + base tag)
    stella projects <profile>             list projects in a profile
    stella export <profile> <project> <dir>
                                          export a project package
    stella export-profile <profile> <dir>
                                          export a profile package
    stella export-recipe <profile> <project> <dir>
                                          export a recipe package
                                          (settings only, no weights)
    stella export-adapter <profile> <project> <dir>
                                          export a bare adapter package
    stella import <export-dir>            import a package back
                                          (a folder or a .stella file)
    stella import-adapter <export-dir> [--into-profile <p>
                                          --into-project <j>]
                                          import an adapter package,
                                          into a project with the same
                                          base or a new project
    stella pull-weights <repo>            download a base model's
                                          weights from Hugging Face
    stella verify <export-dir>            check a package without
                                          importing it
    stella create-profile <name> [--tag <ollama-tag>] [--role <role>]
                                          [--display <name>]
                                          [--base <hf-repo>]
                                          create a profile
    stella create-project <profile> <name> [--display <name>]
                                          [--dataset <file>]
                                          [--template <name>]
                                          create a project in a profile
    stella rename-profile <old> <new>     rename a profile
    stella delete-profile <name> [--purge]
                                          delete a profile (to the trash,
                                          or forever with --purge)
    stella update-profile <name> [--role ...] [--tag ...]
                                          [--display ...] [--base ...]
                                          [--config ...] [--dependencies ...]
                                          [--governing-seat ...]
                                          change a profile
    stella show-profile <name>            show a profile's record
    stella rename-project <profile> <old> <new>
                                          rename a project
    stella delete-project <profile> <name> [--purge]
                                          delete a project (to the trash,
                                          or forever with --purge)
    stella update-project <profile> <name> [--display ...]
                                          [--dataset ...] [--metamorph ...]
                                          [--rank ...] ...
                                          change a project
    stella show-project <profile> <name>  show a project's record and
                                          its checkpoints
    stella delete-checkpoint <profile> <name> <step>
                                          delete one checkpoint forever
    stella prune-checkpoints <profile> <name> [--keep N]
                                          delete all but the newest
                                          checkpoints (and clean up
                                          unfinished ones)
    stella clone-profile <name> <new-name> [--with-projects]
                                          copy a profile under a new
                                          name (with its projects too,
                                          when asked)
    stella clone-project <profile> <name> <new-name>
                                          copy a project under a new
                                          name
    stella train <profile> <project>      LoRA-tune a project (Item 3)
    stella export-gguf <profile> <project> <dir>
                                          merge + convert + quantize to GGUF
    stella probe <profile> <project>      refusal probe, before vs after
    stella sleep <profile> <project>      consolidate new rows into a new
                                          LoRA adapter, with a replay check
                                          (Item 4); --dream adds synthetic
                                          rows from the local Ollama model
    stella sleep-status <profile> <project>
                                          per-cycle sleep stats
    stella sleep-delete <profile> <project> <cycle>
                                          delete one sleep cycle for good
    stella sleep-prune <profile> <project> [--keep N]
                                          delete all but the newest N
                                          sleep cycles
    stella chat [--provider groq|gemini|custom|ollama] [--model <name>]
                                          talk to Stella: the chat sets
                                          up and runs training for you
                                          (/quit to exit). Cloud
                                          providers need a key saved in
                                          Settings under AI providers.
    stella save-key <provider>            save a cloud provider key
                                          (groq, gemini, or custom),
                                          typed without showing it
    stella list-keys                      which providers have a key
                                          saved (never the keys)
    stella remove-key <provider>          forget a saved provider key
    stella requant <tag>                  re-quantize an installed Ollama
                                          model to a smaller quant (default
                                          Q4_K_M) and register it as a new
                                          tag; the original is untouched
    stella bridge <tag>                   find the Hugging Face repo to
                                          train from for an Ollama tag
    stella distill <profile> <project> --teacher <tag> --prompts <file>
                                          [--timeout <seconds>]
                                          ask a teacher model each prompt
                                          and save the answers as the
                                          project's dataset
    stella pc-info                        what this PC can do, and the
                                          training settings Stella picks
                                          for it
    stella doctor [--check]               check the install and repair
                                          what a move broke (--check
                                          only reports, without fixing)
    stella mark-ready <profile> <project>
                                          mark a project ready to train
    stella notes <profile> <project> [--set <text>]
                                          read a project's notes, or
                                          write them with --set
    stella probe-results <profile> <project>
                                          show the saved refusal-probe
                                          results (does not re-run it)
    stella howto [topic]                  read a How to Use topic, or
                                          list the topics
    stella debug-report                   write a debug report file

Reads STELLA_HOME for the home dir (default ~/.stella).

Global flags (T172), available on every command: --json prints a
structured result for scripting (every command except the
long-running ones — train, sleep, distill, export-gguf, requant,
pull-weights, and chat — which print progress as they run and
refuse the flag instead, R52), --quiet silences the per-step
progress lines on a long run, --verbose prints the full traceback
behind the clean error line.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import export as export_mod
from .autoconfig import auto_settings, format_report
from .model import STELLA_VERSION, StellaError, Store, metamorph_problem


def _store() -> Store:
    return Store()


def _as_json(args) -> bool:
    """True when --json was passed (T172)."""
    return bool(getattr(args, "json", False))


def _is_quiet(args) -> bool:
    """True when --quiet was passed (T172)."""
    return bool(getattr(args, "quiet", False))


def _print_json(obj) -> None:
    """One JSON document on stdout (T172): indented, so a human
    reading it can follow it too."""
    print(json.dumps(obj, indent=2, default=str))


# R52: the commands that print a structured result with --json.
# Every other command REFUSES --json (see _refuse_json, called
# from main()): the gate is closed by default, so a future command
# cannot silently ignore the flag the way 24 of them used to.
# train is the one split case, handled in main(): --dry-run prints
# its estimate as JSON, a real run refuses (it prints progress
# lines as it goes).
JSON_COMMANDS = frozenset({
    "profiles", "projects", "show-profile", "show-project",
    "verify", "probe", "sleep-status",
    "pc-info", "doctor", "bridge",
    "export", "export-profile", "export-recipe", "export-adapter",
    "import", "import-adapter",
    "create-profile", "create-project",
    "rename-profile", "delete-profile", "update-profile",
    "rename-project", "delete-project", "update-project",
    "clone-profile", "clone-project",
    "save-key", "list-keys", "remove-key",
    # R112: the new read/write commands print a structured result
    # too. howto is not here: it prints guide text, so --json is
    # refused for it like the other text-only commands.
    "mark-ready", "notes", "probe-results", "debug-report",
})


def _refuse_json(command: str) -> int:
    """--json on a command that cannot print it (R52): a plain
    refusal on stderr, exit 1 — never plain text with exit 0."""
    if command == "train":
        print(
            "stella: --json is not available for train: it prints "
            "progress lines as it runs, so there is no single result "
            "to print as JSON. For a machine-readable estimate, use: "
            "stella train <profile> <project> --dry-run --json",
            file=sys.stderr,
        )
        return 1
    print(
        f"stella: --json is not available for {command}: it prints "
        "progress lines as it runs, so there is no single result to "
        "print as JSON. Run it without --json.",
        file=sys.stderr,
    )
    return 1


def _normalized_note(typed: str, stored: str) -> str:
    """The "(from 'UPPER-Case')" tail (T187): when a name was
    normalized, say so — the user asked for one name and got
    another, and the next command using the typed name would fail
    to match it. Empty when nothing changed."""
    if typed != stored:
        return f" (from {typed!r})"
    return ""


def cmd_profiles(args) -> int:
    store = _store()
    profiles = store.list_profiles()
    if _as_json(args):
        # T172: the structured form — one object per profile, so a
        # script can read names, roles, and bases without parsing
        # the human lines. An empty home prints [], not the hint.
        out = []
        for p in profiles:
            if p.get("_damaged"):
                out.append({
                    "name": p.get("name") or "",
                    "damaged": True,
                    "error": p.get("_error", "bad file"),
                })
                continue
            out.append({
                "name": p.get("name") or "",
                "display_name": p.get("display_name") or p.get("name") or "",
                "role": p.get("role") or "",
                "ollama_tag": p.get("ollama_tag") or "",
                "base_ref": p.get("base_ref") or "",
                "governing_seat": p.get("governing_seat") or "",
                "last_used": p.get("last_used") or "",
            })
        _print_json(out)
        return 0
    if not profiles:
        print("No profiles yet. Create one in the Stella window,")
        # The working form before install is bash stella-cli (T51):
        # `stella` only exists after install.
        print("or: bash stella-cli create-profile <name> --tag <ollama-tag> --role <role>")
        return 0
    for p in profiles:
        # A damaged manifest (T3) is a row with its error, not a
        # silent skip — the folder is still on disk.
        if p.get("_damaged"):
            print(
                f"{p.get('name') or '(unnamed profile)'}\t"
                f"(damaged: {p.get('_error', 'bad file')})"
            )
            continue
        # Defensive read (T5): one nameless manifest degrades to a
        # warning line instead of killing the whole list.
        # R56: the warning fires only when the row REALLY is
        # "(unnamed profile)" — a profile with a display name but
        # no name shows its display name, and warning that it is
        # "shown as (unnamed profile)" described a screen the user
        # was not looking at.
        name = p.get("name") or p.get("display_name") or "(unnamed profile)"
        if not p.get("name") and not p.get("display_name"):
            print(
                "warning: a profile has no name, shown as "
                "(unnamed profile).",
                file=sys.stderr,
            )
        role = p.get("role") or "-"
        tag = p.get("ollama_tag") or p.get("base_ref") or "-"
        print(f"{name}\trole: {role}\tbase: {tag}")
    return 0


def cmd_projects(args) -> int:
    store = _store()
    # T88: a typo'd profile name reads as "that profile doesn't
    # exist", not as "you haven't made any projects yet".
    store.get_profile(args.profile)
    projects = store.list_projects(args.profile)
    if _as_json(args):
        # T172: the structured form — one object per project.
        out = []
        for p in projects:
            if p.get("_damaged"):
                out.append({
                    "name": p.get("name") or "",
                    "damaged": True,
                    "error": p.get("_error", "bad file"),
                })
                continue
            entry = {
                "name": p.get("name") or "",
                "display_name": p.get("display_name") or p.get("name") or "",
                "status": p.get("status", "draft"),
                "dataset_ref": p.get("dataset_ref") or "",
            }
            problem = metamorph_problem(p)
            if problem is not None:
                entry["metamorph_warning"] = problem
            out.append(entry)
        _print_json(out)
        return 0
    if not projects:
        print(f"No projects in profile {args.profile!r}.")
        return 0
    for p in projects:
        name = p.get("name") or "(unnamed project)"
        # A damaged manifest (T3) is a row with its error, not a
        # silent skip.
        if p.get("_damaged"):
            print(f"{name}\t(damaged: {p.get('_error', 'bad file')})")
            continue
        print(f"{name}\tstatus: {p.get('status', 'draft')}")
        # A broken metamorph block degrades to a warning line (T39),
        # read through the shared reader — never a crash, never
        # silent normal.
        problem = metamorph_problem(p)
        if problem is not None:
            print(
                f"  warning: {name}: {problem}; "
                "using the usual mode instead."
            )
    return 0


def cmd_pc_info(args) -> int:
    store = _store()
    measurement, settings = auto_settings(store.home)
    if _as_json(args):
        # R52: the structured form — the measurement and the
        # settings it picked, as one JSON document.
        _print_json({"measurement": measurement, "settings": settings})
        return 0
    print(format_report(measurement, settings))
    return 0


def cmd_doctor(args) -> int:
    """Check the install and repair what a move broke (T66)."""
    from . import doctor as doctor_mod

    checks = doctor_mod.run_checks(
        doctor_mod.find_install_dir(), Path.home(), fix=not args.check
    )
    broken = any(c.status == doctor_mod.BROKEN for c in checks)
    if _as_json(args):
        # R52: the structured form — every check as an object, plus
        # the overall verdict. The exit code still carries it, as
        # in the human form below.
        _print_json({
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                }
                for c in checks
            ],
            "ok": not broken,
        })
        return 1 if broken else 0
    print(doctor_mod.format_report(checks))
    return 1 if broken else 0


def cmd_export(args) -> int:
    store = _store()
    # R53: the project must exist before the size line prints —
    # the estimator sums files that exist (none for a missing
    # project, so 0), and the old order printed the nonsense
    # "Package size: about 0 bytes." before the real error.
    store.get_project(args.profile, args.project)
    # T178: the size before (the estimate) and after (the real
    # package). The disk check inside export_project refuses
    # before copying when it will not fit.
    bundle = getattr(args, "bundle_dataset", False)
    if _as_json(args):
        # R52: the structured form — one JSON document, no size
        # lines before or after it.
        out = export_mod.export_project(
            store, args.profile, args.project, args.dir,
            bundle_dataset=bundle,
            force=getattr(args, "force", False),
            as_zip=getattr(args, "zip", False),
        )
        _print_json({
            "kind": "project",
            "exported": str(out),
            "size_bytes": export_mod.package_size(out),
        })
        return 0
    estimate = export_mod.estimate_export_size(
        store, args.profile, args.project, bundle_dataset=bundle,
    )
    print(f"Package size: about {export_mod.format_size(estimate)}.")
    out = export_mod.export_project(
        store, args.profile, args.project, args.dir,
        bundle_dataset=bundle,
        force=getattr(args, "force", False),
        as_zip=getattr(args, "zip", False),
    )
    print(f"Exported to {out}")
    print(
        f"Package size: {export_mod.format_size(export_mod.package_size(out))}."
    )
    return 0


def cmd_export_profile(args) -> int:
    """Export a profile on its own (T86)."""
    store = _store()
    # R53: the profile must exist before the size line prints —
    # see cmd_export.
    store.get_profile(args.profile)
    # T178: the size before (the estimate) and after (the real
    # package), as in cmd_export.
    include = getattr(args, "with_projects", False)
    if _as_json(args):
        # R52: the structured form — one JSON document.
        out = export_mod.export_profile(
            store, args.profile, args.dir,
            include_projects=include,
            force=getattr(args, "force", False),
            as_zip=getattr(args, "zip", False),
        )
        _print_json({
            "kind": "profile",
            "exported": str(out),
            "size_bytes": export_mod.package_size(out),
        })
        return 0
    estimate = export_mod.estimate_profile_export_size(
        store, args.profile, include_projects=include,
    )
    print(f"Package size: about {export_mod.format_size(estimate)}.")
    out = export_mod.export_profile(
        store, args.profile, args.dir,
        include_projects=include,
        force=getattr(args, "force", False),
        as_zip=getattr(args, "zip", False),
    )
    print(f"Exported to {out}")
    print(
        f"Package size: {export_mod.format_size(export_mod.package_size(out))}."
    )
    return 0


def cmd_export_recipe(args) -> int:
    """Export a recipe on its own (T170): the settings-only share
    — dataset reference, settings, metamorph mode + notes, and
    project notes. No weights, no checkpoints."""
    store = _store()
    # R53: the project must exist before the size line prints —
    # see cmd_export.
    store.get_project(args.profile, args.project)
    if _as_json(args):
        # R52: the structured form — one JSON document.
        out = export_mod.export_recipe(
            store, args.profile, args.project, args.dir,
            force=getattr(args, "force", False),
            as_zip=getattr(args, "zip", False),
        )
        _print_json({
            "kind": "recipe",
            "exported": str(out),
            "size_bytes": export_mod.package_size(out),
        })
        return 0
    estimate = export_mod.estimate_recipe_export_size(
        store, args.profile, args.project,
    )
    print(f"Package size: about {export_mod.format_size(estimate)}.")
    out = export_mod.export_recipe(
        store, args.profile, args.project, args.dir,
        force=getattr(args, "force", False),
        as_zip=getattr(args, "zip", False),
    )
    print(f"Exported recipe to {out}")
    print(
        f"Package size: {export_mod.format_size(export_mod.package_size(out))}."
    )
    return 0


def cmd_export_adapter(args) -> int:
    """Export a bare adapter on its own (T173): the adapter
    weights + a manifest (base, rank, dataset name, training
    summary). No project record, no checkpoints."""
    store = _store()
    # R53: the project must exist before the size line prints —
    # see cmd_export.
    store.get_project(args.profile, args.project)
    if _as_json(args):
        # R52: the structured form — one JSON document.
        out = export_mod.export_adapter(
            store, args.profile, args.project, args.dir,
            force=getattr(args, "force", False),
            as_zip=getattr(args, "zip", False),
        )
        _print_json({
            "kind": "adapter",
            "exported": str(out),
            "size_bytes": export_mod.package_size(out),
        })
        return 0
    estimate = export_mod.estimate_adapter_export_size(
        store, args.profile, args.project,
    )
    print(f"Package size: about {export_mod.format_size(estimate)}.")
    out = export_mod.export_adapter(
        store, args.profile, args.project, args.dir,
        force=getattr(args, "force", False),
        as_zip=getattr(args, "zip", False),
    )
    print(f"Exported adapter to {out}")
    print(
        f"Package size: {export_mod.format_size(export_mod.package_size(out))}."
    )
    return 0


def cmd_pull_weights(args) -> int:
    """Download a base model's weights (T184): the short command
    that replaces the nested-quote one-liner the training
    installer used to print. Nothing to hand-type with nested
    quotes: `stella pull-weights LiquidAI/LFM3-1.7B`."""
    from . import provision as provision_mod

    repo = args.repo
    if not provision_mod.is_hf_repo_id(repo):
        print(
            f"stella: {repo!r} is not a Hugging Face repo id "
            "(it should look like org/name).",
            file=sys.stderr,
        )
        return 1
    if not provision_mod.hub_available():
        print(
            "stella: the Hugging Face packages are not installed. "
            "Run this once in the Stella folder: "
            "bash install-training.sh",
            file=sys.stderr,
        )
        return 1
    quiet = _is_quiet(args)
    announced: list[bool] = []

    def _show(line, **kwargs):
        # run_download speaks in PROGRESS / DONE / ERROR lines
        # (the GUI parses them); the terminal gets plain words.
        # R111(d): the "Pulling weights..." line prints only when
        # a pull actually starts — on the first progress or done
        # signal — so a bad repo shows only its error, not a
        # progress line for a download that never began.
        if line.startswith(("PROGRESS ", "DONE ")) and not announced:
            announced.append(True)
            print(f"Pulling weights for {repo}...")
        if line.startswith("DONE "):
            print(f"Downloaded to {line[5:]}.")
        elif line.startswith("ERROR "):
            print(f"stella: {line[6:]}", file=sys.stderr)
        elif line.startswith("PROGRESS ") and not quiet:
            try:
                _tag, done, total = line.split()
                done = int(done)
                total = int(total)
            except ValueError:
                return
            if total > 0:
                print(
                    f"Downloaded {provision_mod.format_size(done)} "
                    f"of {provision_mod.format_size(total)}.",
                    flush=True,
                )

    return provision_mod.run_download(repo, _print=_show)


def cmd_verify(args) -> int:
    """Check a package without importing it (T105): one
    readable pass/fail per check, exit 0 when all pass."""
    report = export_mod.check_export(args.dir)
    if _as_json(args):
        # T172: the structured form — the whole report, including
        # the manifest, as one JSON document.
        _print_json(report)
        return 0 if report["ok"] else 1
    print(f"Checking {args.dir}...")
    print(export_mod.format_check_report(report))
    return 0 if report["ok"] else 1


def _prompt_profile_merge(slug, diff) -> str:
    """The on_profile_conflict callback for the CLI on a terminal:
    print the differing fields, ask keep or take, return "keep" or
    "take". An empty answer, an answer that is not "use", or a
    closed stdin keeps yours — the safe answer."""
    print(f"Profile {slug!r} already exists, but the package differs:")
    for field in export_mod.PROFILE_BLOCK_FIELDS:
        if field not in diff:
            continue
        word = export_mod.PROFILE_FIELD_WORDS[field]
        local = diff[field]["local"] or "(blank)"
        package = diff[field]["package"] or "(blank)"
        print(f"  {word}: yours is {local!r}, the package has {package!r}.")
    try:
        answer = input(
            "Keep yours, or use the package's? "
            "[K]eep mine / [U]se the package's (default: keep mine): "
        )
    except (EOFError, KeyboardInterrupt):
        return "keep"
    if answer.strip().lower() in ("u", "use", "take"):
        return "take"
    return "keep"


def cmd_import(args) -> int:
    store = _store()
    choice = getattr(args, "profile_merge", None)
    # With a flag, the flag decides. Without one, ask on a
    # terminal; anywhere else (a script, a pipe) the engine keeps
    # the local values and warns — import never hangs on input().
    on_conflict = None
    if choice is None and sys.stdin.isatty():
        on_conflict = _prompt_profile_merge
    # The base-health check (T61): a direct list_models() is fine
    # here — import is user-initiated, not a click — and an empty
    # list (Ollama down) means "unknown", so no warning fires.
    from .ollama import list_models

    models = list_models()
    # The preview (T58): the same summary the window shows,
    # printed before anything is imported. --preview prints it
    # and stops — nothing is imported.
    summary = export_mod.preview_export(
        store, args.dir, installed_models=models
    )
    if _as_json(args) and getattr(args, "preview", False):
        # R52: the structured form of the preview — the summary
        # itself, as one JSON document. Nothing is imported.
        _print_json(summary)
        return 0
    if not _as_json(args):
        print(export_mod.format_preview(summary))
    if getattr(args, "preview", False):
        return 0
    # T117: the collision choice, from the flags. Without one, a
    # collision is refused with the flags named (the engine's
    # error) — a scripted import never hangs on a prompt.
    collision = None
    if getattr(args, "as_copy", False):
        collision = "copy"
    elif getattr(args, "replace", False):
        collision = "replace"
    result = export_mod.import_export(
        store, args.dir,
        profile_choice=choice, on_profile_conflict=on_conflict,
        installed_models=models,
        collision=collision,
    )
    if _as_json(args):
        # R52: the structured form — the import result as one JSON
        # document, with the package kind named.
        doc = dict(result)
        doc.setdefault("kind", summary.get("kind"))
        _print_json(doc)
        return 0
    if summary.get("kind") == export_mod.PROFILE_PACKAGE_KIND:
        names = result.get("projects", [])
        if names:
            print(
                f"Imported profile {result['profile']!r} with "
                f"{len(names)} project{'s' if len(names) != 1 else ''}: "
                f"{', '.join(names)}."
            )
        else:
            print(f"Imported profile {result['profile']!r} (no projects).")
    elif summary.get("kind") == export_mod.ADAPTER_PACKAGE_KIND:
        # A generic import always creates a new project around
        # the adapter (import-adapter is the command that targets
        # an existing project).
        print(
            f"Imported adapter {result['adapter']!r} as new project "
            f"{result['project']!r} in profile {result['profile']!r}."
        )
        if result.get("copy_of"):
            print(
                f"(The name {result['copy_of']!r} was taken, so it "
                "landed under a copy name.)"
            )
    else:
        # A project package, or a recipe (T170) — same shape, and
        # the same collision choices. The noun says which.
        noun = (
            "recipe"
            if summary.get("kind") == export_mod.RECIPE_PACKAGE_KIND
            else "project"
        )
        if result.get("collision") == "copy":
            print(
                f"Imported {noun} {result['project']!r} into profile "
                f"{result['profile']!r} (a copy of "
                f"{result.get('copy_of', '')!r})."
            )
        elif result.get("collision") == "replace":
            print(
                f"Imported {noun} {result['project']!r} into profile "
                f"{result['profile']!r} (the old project went to the "
                "trash)."
            )
        else:
            print(
                f"Imported {noun} {result['project']!r} into profile "
                f"{result['profile']!r}"
            )
    if result.get("profile_existed"):
        print(f"Profile {result['profile']!r} already existed.")
    if result.get("profile_choice") == "take":
        fields = export_mod.describe_profile_diff(
            result.get("profile_diff") or {}
        )
        print(f"Profile updated from the package ({fields}).")
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")
    if (
        result.get("profile_choice") == "keep"
        and result.get("profile_diff")
        and choice is None
        and on_conflict is None
    ):
        print("Use --profile-merge take to use the package's values instead.")
    return 0


def cmd_import_adapter(args) -> int:
    """Import an adapter package (T173): into an existing project
    with the same base (--into-profile + --into-project), or into
    a new project created around it. The preview, the profile
    merge, and the base-health check work as in cmd_import."""
    store = _store()
    choice = getattr(args, "profile_merge", None)
    on_conflict = None
    if choice is None and sys.stdin.isatty():
        on_conflict = _prompt_profile_merge
    from .ollama import list_models

    models = list_models()
    summary = export_mod.preview_export(
        store, args.dir, installed_models=models
    )
    if summary.get("kind") != export_mod.ADAPTER_PACKAGE_KIND:
        print(
            "stella: this is not an adapter package. Import it with "
            "`stella import` instead.",
            file=sys.stderr,
        )
        return 1
    if _as_json(args) and getattr(args, "preview", False):
        # R52: the structured form of the preview — see cmd_import.
        _print_json(summary)
        return 0
    if not _as_json(args):
        print(export_mod.format_preview(summary))
    if getattr(args, "preview", False):
        return 0
    into_profile = getattr(args, "into_profile", None)
    into_project = getattr(args, "into_project", None)
    result = export_mod.import_adapter_export(
        store, args.dir,
        profile_choice=choice, on_profile_conflict=on_conflict,
        installed_models=models,
        into_profile=into_profile, into_project=into_project,
    )
    if _as_json(args):
        # R52: the structured form — see cmd_import.
        doc = dict(result)
        doc.setdefault("kind", summary.get("kind"))
        _print_json(doc)
        return 0
    if result.get("into_existing"):
        print(
            f"Imported adapter {result['adapter']!r} into project "
            f"{result['project']!r} in profile {result['profile']!r}."
        )
    else:
        print(
            f"Imported adapter {result['adapter']!r} as new project "
            f"{result['project']!r} in profile {result['profile']!r}."
        )
        if result.get("copy_of"):
            print(
                f"(The name {result['copy_of']!r} was taken, so it "
                "landed under a copy name.)"
            )
    if result.get("profile_existed") and not result.get("into_existing"):
        print(f"Profile {result['profile']!r} already existed.")
    if result.get("profile_choice") == "take":
        fields = export_mod.describe_profile_diff(
            result.get("profile_diff") or {}
        )
        print(f"Profile updated from the package ({fields}).")
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")
    if (
        result.get("profile_choice") == "keep"
        and result.get("profile_diff")
        and choice is None
        and on_conflict is None
    ):
        print("Use --profile-merge take to use the package's values instead.")
    return 0


def _print_base_ref_warnings(base_ref: str) -> None:
    """R87: the save-time base-ref warnings, printed (one line
    each, \"Warning: ...\"). Silent when there is nothing to say."""
    from .train import base_ref_warnings

    for warning in base_ref_warnings(base_ref):
        print(f"Warning: {warning}")


def cmd_create_profile(args) -> int:
    store = _store()
    data = store.create_profile(
        args.name,
        ollama_tag=args.tag or "",
        role=args.role or "",
        display_name=args.display or "",
        base_ref=args.base or "",
    )
    if _as_json(args):
        # R52: the structured form — the created record.
        _print_json(data)
        return 0
    print(
        f"Created profile {data['name']!r}"
        f"{_normalized_note(args.name, data['name'])} "
        f"(role: {data.get('role') or '-'})"
    )
    # R87: the base ref is checked against the actual weights at
    # save time — a tag, a GGUF file, or a folder with no model
    # warns here, in the same soft voice as the window. JSON mode
    # stays clean (the record above is the whole output).
    _print_base_ref_warnings(args.base or "")
    return 0


# -- T87: CLI parity — rename, delete, update, show ------------------
# One cli.py change adding both sets of commands, reusing the Store
# methods and error messages the GUI already uses. The --processor
# option on update-profile is NOT here: the processor field's
# meaning is undecided (T128, hard-gated on Joshua's decision), so
# the CLI does not invent it.


def cmd_rename_profile(args) -> int:
    store = _store()
    data = store.rename_profile(args.old, args.new)
    if _as_json(args):
        # R52: the structured form — the renamed record.
        _print_json(data)
        return 0
    print(
        f"Renamed profile {args.old!r} to {data['name']!r}"
        f"{_normalized_note(args.new, data['name'])}"
    )
    return 0


def cmd_delete_profile(args) -> int:
    store = _store()
    if getattr(args, "purge", False):
        # R90: purging is forever, so it asks first (default No),
        # like the window's purge confirm — unless --yes says the
        # script already decided.
        if not getattr(args, "yes", False):
            if not _confirm_destructive(
                f"Delete profile {args.name!r} forever? "
                "This cannot be undone."
            ):
                print(f"Kept profile {args.name!r}.", file=sys.stderr)
                return 1
        store.purge_profile(args.name)
        if _as_json(args):
            # R52: the structured form — what happened, no prose.
            _print_json({"name": args.name, "action": "purged"})
            return 0
        print(f"Deleted profile {args.name!r} forever.")
    else:
        trash = store.delete_profile(args.name)
        if _as_json(args):
            _print_json({
                "name": args.name,
                "action": "trashed",
                "trash": str(trash),
            })
            return 0
        print(
            f"Moved profile {args.name!r} to the trash ({trash}). "
            "Move it back to undo, or delete it forever from Trash "
            "in the File menu."
        )
    return 0


def cmd_update_profile(args) -> int:
    store = _store()
    fields = {}
    if args.role is not None:
        fields["role"] = args.role
    if args.tag is not None:
        fields["ollama_tag"] = args.tag
    if args.display is not None:
        fields["display_name"] = args.display
    if args.base is not None:
        fields["base_ref"] = args.base
    # T115: config and dependencies, reachable from the terminal.
    # Bad JSON is refused with the parse error and nothing is
    # written — the parse happens before the store call, so a
    # bad --config cannot half-update the profile.
    if getattr(args, "config", None) is not None:
        import json

        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as exc:
            print(f"stella: config is not valid JSON: {exc}", file=sys.stderr)
            return 1
        if not isinstance(config, dict):
            print(
                "stella: config must be a JSON object, not "
                f"{type(config).__name__}",
                file=sys.stderr,
            )
            return 1
        fields["config"] = config
    if getattr(args, "dependencies", None) is not None:
        fields["dependencies"] = [
            item.strip()
            for item in args.dependencies.split(",")
            if item.strip()
        ]
    # T116: the governing-seat marker. The store validates the
    # seat name; a bad one is refused with the plain error.
    if getattr(args, "governing_seat", None) is not None:
        fields["governing_seat"] = args.governing_seat
    if not fields:
        print(
            "Nothing to change: pass --role, --tag, --display, "
            "--base, --config, --dependencies, or --governing-seat."
        )
        return 0
    data = store.update_profile(args.name, **fields)
    if _as_json(args):
        # R52: the structured form — the updated record.
        _print_json(data)
        return 0
    print(f"Updated profile {data['name']!r}.")
    # R87: a changed base ref is checked against the actual
    # weights — see cmd_create_profile.
    if "base_ref" in fields:
        _print_base_ref_warnings(fields["base_ref"])
    return 0


def cmd_show_profile(args) -> int:
    store = _store()
    prof = store.get_profile(args.name)
    projects = store.list_projects(args.name)
    if _as_json(args):
        # T172: the structured form — the profile record, plus the
        # project names (the human form lists them the same way).
        healthy = [p for p in projects if not p.get("_damaged")]
        _print_json({
            **prof,
            "projects": [p["name"] for p in healthy],
        })
        return 0
    print(f"Profile {prof['name']} ({prof.get('display_name', prof['name'])})")
    print(f"  role: {prof.get('role') or '-'}")
    # T116: a custom role is flagged, and a governing-seat marker
    # is shown, so the record says what the window says.
    from .model import is_custom_role

    if is_custom_role(prof.get("role")):
        print("  role is custom (not one of the canonical seats)")
    if prof.get("governing_seat"):
        print(f"  governing seat: {prof['governing_seat']}")
    print(f"  tag: {prof.get('ollama_tag') or '-'}")
    print(f"  base: {prof.get('base_ref') or '-'}")
    config = prof.get("config") or {}
    print(f"  config: {config if config else '(none)'}")
    deps = prof.get("dependencies") or []
    print(f"  dependencies: {', '.join(deps) if deps else '(none)'}")
    if prof.get("created"):
        print(f"  created: {prof['created']}")
    if prof.get("updated"):
        print(f"  updated: {prof['updated']}")
    healthy = [p for p in projects if not p.get("_damaged")]
    if healthy:
        print(
            f"  projects ({len(healthy)}): "
            + ", ".join(p["name"] for p in healthy)
        )
    else:
        print("  projects: (none)")
    return 0


def cmd_rename_project(args) -> int:
    store = _store()
    data = store.rename_project(args.profile, args.old, args.new)
    if _as_json(args):
        # R52: the structured form — the renamed record.
        _print_json(data)
        return 0
    print(
        f"Renamed project {args.old!r} to {data['name']!r}"
        f"{_normalized_note(args.new, data['name'])}"
    )
    return 0


def cmd_delete_project(args) -> int:
    store = _store()
    if getattr(args, "purge", False):
        # R90: purging is forever, so it asks first (default No),
        # like the window's purge confirm — unless --yes says the
        # script already decided.
        if not getattr(args, "yes", False):
            if not _confirm_destructive(
                f"Delete project {args.name!r} from profile "
                f"{args.profile!r} forever? This cannot be undone."
            ):
                print(
                    f"Kept project {args.name!r}.", file=sys.stderr
                )
                return 1
        store.purge_project(args.profile, args.name)
        if _as_json(args):
            # R52: the structured form — what happened, no prose.
            _print_json({
                "profile": args.profile,
                "name": args.name,
                "action": "purged",
            })
            return 0
        print(
            f"Deleted project {args.name!r} from profile "
            f"{args.profile!r} forever."
        )
    else:
        trash = store.delete_project(args.profile, args.name)
        if _as_json(args):
            _print_json({
                "profile": args.profile,
                "name": args.name,
                "action": "trashed",
                "trash": str(trash),
            })
            return 0
        print(
            f"Moved project {args.name!r} to the trash ({trash}). "
            "Move it back to undo, or delete it forever from Trash "
            "in the File menu."
        )
    return 0


# The training-setting flags, shared by create-project and
# update-project (T87): (flag, setting key, argparse type). The
# same flags, the same ranges, on both commands.
SETTING_FLAGS = [
    ("--rank", "rank", int),
    ("--epochs", "epochs", int),
    ("--learning-rate", "learning_rate", float),
    ("--batch-size", "batch_size", int),
    ("--grad-accum", "grad_accum", int),
    ("--max-seq-len", "max_seq_len", int),
    ("--checkpoint-steps", "checkpoint_steps", int),
    ("--val-fraction", "val_fraction", float),
    ("--warmup-steps", "warmup_steps", int),
    ("--seed", "seed", int),
    # R28: --method is NOT here any more. It used to accept "full"
    # and store it, while the engine silently trained LoRA anyway
    # (train.py has no full path and never reads the setting). The
    # flag still exists — _add_setting_flags adds it below — but
    # _settings_from_args refuses "full" in plain words and only
    # "lora" passes through, which is what every run trains.
]


def _settings_from_args(args) -> dict:
    """The settings the flags name (only the flags that were
    passed — an absent flag leaves the setting alone)."""
    settings = {}
    for flag, key, _kind in SETTING_FLAGS:
        value = getattr(args, key, None)
        if value is not None:
            settings[key] = value
    # R28: --method full is refused, not stored — storing it
    # would promise a full fine-tune the engine cannot run.
    method = getattr(args, "method", None)
    if method is not None:
        if str(method).strip().lower() == "full":
            raise StellaError(
                "method full is not available: Stella always trains "
                "with LoRA on this PC, because a full fine-tune "
                "needs far more RAM than this PC has. Use --method "
                "lora, or leave the flag off."
            )
        if str(method).strip().lower() == "lora":
            settings["method"] = "lora"
        else:
            raise StellaError(
                f"method must be lora, not {method!r}. Stella "
                "always trains with LoRA on this PC."
            )
    return settings


# R107: what each training-setting flag does, in plain words, with
# the range the validators enforce (SETTING_RULES in model.py) and
# the default (DEFAULT_SETTINGS). The help says it first, so the
# user does not have to trip the error to learn it. The ranges are
# written as "low to high" so the test can pin them against the
# rules table; --seed's range is the whole 32-bit span, so its
# help says "any whole number" instead of the numbers.
SETTING_HELP = {
    "rank": (
        "LoRA rank: how big the adapter is (1 to 64, default 8). "
        "A bigger rank can learn more, but uses more RAM."
    ),
    "epochs": (
        "Epochs: how many times training reads the whole dataset "
        "(1 to 100, default 3). More epochs take longer."
    ),
    "learning_rate": (
        "Learning rate: how big each training step is "
        "(0 to 1, default 0.0002). Too big and training jumps "
        "around; too small and it barely learns."
    ),
    "batch_size": (
        "Batch size: how many examples each training step reads "
        "at once (1 to 32, default 1). Bigger batches use more RAM."
    ),
    "grad_accum": (
        "Gradient accumulation: how many steps pile up before the "
        "model updates (1 to 64, default 8). Acts like a bigger "
        "batch without the RAM."
    ),
    "max_seq_len": (
        "Max sequence length: the longest example training reads, "
        "in tokens (128 to 32768, default 1024). Longer examples "
        "are cut off."
    ),
    "checkpoint_steps": (
        "Checkpoint steps: save a checkpoint every N steps "
        "(0 to 10000, default 50). 0 means no checkpoints during "
        "the run."
    ),
    "val_fraction": (
        "Validation fraction: how much of the dataset is held back "
        "to check training (0 to 0.5, default 0.1). 0 means no "
        "checking."
    ),
    "warmup_steps": (
        "Warmup steps: gentle steps before full training starts "
        "(0 to 1000, default 5)."
    ),
    "seed": (
        "Seed: the random starting point, any whole number "
        "(default 42). The same seed gives the same shuffle."
    ),
}


def _add_setting_flags(parser) -> None:
    """Add the training-setting flags to a subcommand parser."""
    for flag, key, kind in SETTING_FLAGS:
        parser.add_argument(
            flag, dest=key, type=kind, default=None,
            help=SETTING_HELP[key],
        )
    # R28: --method stays a real flag so `--method full` gets the
    # plain-words refusal in _settings_from_args instead of
    # argparse's "unrecognized arguments" error. R107: the help
    # names the values — lora only.
    parser.add_argument(
        "--method", dest="method", type=str, default=None,
        help="Training method: lora only. Stella always trains "
        "with LoRA on this PC.",
    )


def cmd_update_project(args) -> int:
    store = _store()
    fields: dict = {}
    if args.display is not None:
        fields["display_name"] = args.display
    if args.dataset is not None:
        fields["dataset_ref"] = args.dataset
    settings = _settings_from_args(args)
    if settings:
        fields["settings"] = settings
    metamorph = {}
    if args.metamorph is not None:
        metamorph["mode"] = args.metamorph
    if getattr(args, "metamorph_notes", None) is not None:
        metamorph["notes"] = args.metamorph_notes
    if metamorph:
        fields["metamorph"] = metamorph
    if not fields:
        print(
            "Nothing to change: pass --display, --dataset, "
            "--metamorph, or a setting flag."
        )
        return 0
    data = store.update_project(args.profile, args.name, **fields)
    if _as_json(args):
        # R52: the structured form — the updated record.
        _print_json(data)
        return 0
    print(
        f"Updated project {data['name']!r} in profile {args.profile!r}."
    )
    return 0


def cmd_show_project(args) -> int:
    store = _store()
    from .model import metamorph_mode
    from .train import list_checkpoints

    proj = store.get_project(args.profile, args.name)
    checkpoints = list_checkpoints(store, args.profile, args.name)
    if _as_json(args):
        # T172: the structured form — the project record, plus the
        # checkpoints (the human form lists them the same way).
        _print_json({**proj, "checkpoints": checkpoints})
        return 0
    print(
        f"Project {proj['name']} "
        f"({proj.get('display_name', proj['name'])}) "
        f"in profile {args.profile}"
    )
    print(f"  dataset: {proj.get('dataset_ref') or '(not set)'}")
    print(f"  status: {proj.get('status', 'draft')}")
    print(f"  metamorph: {metamorph_mode(proj)}")
    notes = (proj.get("metamorph") or {}).get("notes", "")
    if isinstance(proj.get("metamorph"), dict) and notes:
        print(f"  metamorph notes: {notes}")
    settings = proj.get("settings") or {}
    print("  settings:")
    for key in sorted(settings):
        print(f"    {key}: {settings[key]}")
    # R28: a stored method of "full" (set before v0.26.0) warns
    # here, so the listing never implies a full run is coming.
    if settings.get("method") == "full":
        print(
            "  note: this project says method full, but Stella "
            "always trains with LoRA on this PC."
        )
    if proj.get("created"):
        print(f"  created: {proj['created']}")
    if proj.get("updated"):
        print(f"  updated: {proj['updated']}")
    # A5-G2: the checkpoints, so the user can see what
    # `train --resume` would use (listed above, at the top, so the
    # --json branch shares them).
    if checkpoints:
        print(f"  checkpoints ({len(checkpoints)}):")
        for ck in checkpoints:
            loss = (
                f"{ck['loss']:.4f}" if ck.get("loss") is not None
                else "n/a"
            )
            print(
                f"    step {ck['step']} (epoch {ck.get('epoch', '?')}, "
                f"loss {loss})"
            )
    else:
        print("  checkpoints: (none)")
    return 0


def _confirm_destructive(question: str) -> bool:
    """A destructive confirmation on stdin (R90/R77): [y/N],
    default No. A non-interactive stdin (piped, closed, CI)
    reads EOF and counts as No, never a hang. The prompt goes to
    stderr so --json output on stdout stays clean."""
    print(f"{question} [y/N] ", file=sys.stderr, end="", flush=True)
    try:
        answer = sys.stdin.readline()
    except (OSError, EOFError):
        return False
    if not answer:
        return False
    return answer.strip().lower() in ("y", "yes")


def cmd_delete_checkpoint(args) -> int:
    """Delete one checkpoint, permanently (R77) — the CLI delete
    for checkpoints, including orphans (a crashed save's
    step dir, which the list never shows). The trash does not
    free disk, so there is no trash here; the prompt (or --yes)
    is the chance to back out."""
    from .train import (
        delete_checkpoint,
        list_checkpoints,
        list_orphan_checkpoints,
    )

    store = _store()
    target = None
    for ck in list_checkpoints(store, args.profile, args.name):
        if ck["step"] == args.step:
            target = ck
            break
    if target is None:
        for orphan in list_orphan_checkpoints(
            store, args.profile, args.name
        ):
            if orphan["name"] == f"step-{args.step}":
                target = orphan
                break
    if target is None:
        print(
            f"stella: no checkpoint step-{args.step} for project "
            f"{args.name!r}",
            file=sys.stderr,
        )
        return 1
    size = _fmt_size(target.get("size_bytes") or 0)
    if not getattr(args, "yes", False):
        if not _confirm_destructive(
            f"Delete checkpoint step-{args.step} of project "
            f"{args.name!r} forever ({size})? This cannot be undone."
        ):
            print(
                f"Kept checkpoint step-{args.step}.", file=sys.stderr
            )
            return 1
    result = delete_checkpoint(store, args.profile, args.name, args.step)
    if _as_json(args):
        _print_json({
            "profile": args.profile,
            "name": args.name,
            "action": "checkpoint-deleted",
            "step": result["step"],
            "freed_bytes": result["freed_bytes"],
        })
        return 0
    print(
        f"Deleted checkpoint step-{args.step} of project "
        f"{args.name!r} forever "
        f"({_fmt_size(result['freed_bytes'])} freed)."
    )
    return 0


def cmd_prune_checkpoints(args) -> int:
    """Delete all but the newest N checkpoints (R77) — the CLI
    prune, which R112 deliberately excludes because this task
    owns it. Old orphans (unfinished saves from a crash) are
    cleaned up with it and reported; orphans too young to tell
    from a live save are left alone."""
    from .train import (
        list_checkpoints,
        prune_checkpoints,
        reap_orphan_checkpoints,
    )

    store = _store()
    checkpoints = list_checkpoints(store, args.profile, args.name)
    keep = args.keep
    doomed = checkpoints[:-keep] if len(checkpoints) > keep else []
    if not doomed:
        if not _as_json(args):
            # R52: --json never mixes plain text into stdout —
            # the JSON summary below carries the same facts.
            print(
                f"Project {args.name!r} has {len(checkpoints)} "
                f"checkpoint{'s' if len(checkpoints) != 1 else ''}; "
                f"keeping {keep} deletes nothing."
            )
    elif not getattr(args, "yes", False):
        steps = ", ".join(f"step-{ck['step']}" for ck in doomed)
        freed = _fmt_size(sum(ck["size_bytes"] for ck in doomed))
        if not _confirm_destructive(
            f"Delete {len(doomed)} old checkpoint"
            f"{'s' if len(doomed) != 1 else ''} of project "
            f"{args.name!r} forever ({steps}, {freed} freed)? "
            "This cannot be undone."
        ):
            print("Kept every checkpoint.", file=sys.stderr)
            return 1
    result = prune_checkpoints(store, args.profile, args.name, keep=keep)
    reaped = reap_orphan_checkpoints(store, args.profile, args.name)
    if _as_json(args):
        _print_json({
            "profile": args.profile,
            "name": args.name,
            "action": "checkpoints-pruned",
            **result,
            "orphans_reaped": reaped["reaped"],
            "orphans_skipped": reaped["skipped"],
            "orphans_freed_bytes": reaped["freed_bytes"],
        })
        return 0
    if result["deleted"]:
        kept = len(result["kept"])
        print(
            f"Deleted {len(result['deleted'])} old checkpoint"
            f"{'s' if len(result['deleted']) != 1 else ''} "
            f"({_fmt_size(result['freed_bytes'])} freed); kept "
            f"the {kept} newest."
        )
    if reaped["reaped"]:
        print(
            f"Also cleaned up {len(reaped['reaped'])} unfinished "
            f"checkpoint folder"
            f"{'s' if len(reaped['reaped']) != 1 else ''} from "
            "interrupted saves "
            f"({_fmt_size(reaped['freed_bytes'])} freed)."
        )
    if reaped["skipped"]:
        print(
            f"Left {len(reaped['skipped'])} recent unfinished "
            "checkpoint folder"
            f"{'s' if len(reaped['skipped']) != 1 else ''} alone "
            "(too recent to tell from a save in progress)."
        )
    return 0


def cmd_clone_profile(args) -> int:
    """Copy a profile under a new name (R55): the engine's clone,
    the same one the Profile window's Clone button runs — same
    tag, base, role, config, and dependencies, no projects by
    default (or with them, when --with-projects is passed)."""
    store = _store()
    data = store.clone_profile(
        args.name, args.new_name,
        copy_projects=getattr(args, "with_projects", False),
    )
    if _as_json(args):
        # R52: the structured form — the cloned record (including
        # skipped_damaged_projects when a project could not be
        # copied).
        _print_json(data)
        return 0
    print(
        f"Cloned profile {args.name!r} as {data['name']!r}"
        f"{_normalized_note(args.new_name, data['name'])}."
    )
    # R40: a clone that skipped damaged projects says so — the
    # copy is incomplete, and "Cloned" alone would be a lie.
    skipped = data.get("skipped_damaged_projects") or []
    if skipped:
        names = ", ".join(s["name"] for s in skipped)
        print(
            f"Warning: {len(skipped)} project(s) could not be copied "
            f"because their records are damaged ({names}). "
            "The originals are untouched."
        )
    return 0


def cmd_clone_project(args) -> int:
    """Copy a project under a new name (R55): the engine's clone,
    the same one the Project window's Clone button runs — same
    dataset, settings, and metamorph mode, zero checkpoints, no
    adapter, and fresh notes with a "cloned from" line."""
    store = _store()
    data = store.clone_project(args.profile, args.name, args.new_name)
    if _as_json(args):
        # R52: the structured form — the cloned record.
        _print_json(data)
        return 0
    print(
        f"Cloned project {args.name!r} as {data['name']!r}"
        f"{_normalized_note(args.new_name, data['name'])} "
        f"in profile {args.profile!r}."
    )
    return 0


def cmd_train(args) -> int:
    import signal

    from .train import TrainController, train_project

    store = _store()
    # Pre-train dataset check (T83): the CLI pre-flight, the same
    # check the Train panel runs — a malformed or missing dataset
    # is refused here with the bad lines named, before the run
    # starts; a healthy one reports its row count and format; a
    # tiny one warns (the GUI asks; the CLI warns and proceeds,
    # so scripted runs never block on a prompt).
    from .train import check_dataset

    dataset_ref = args.dataset
    if dataset_ref is None:
        dataset_ref = (
            store.get_project(args.profile, args.project).get("dataset_ref")
            or ""
        )
    health = check_dataset(store, args.profile, args.project, dataset_ref)
    if health["status"] in ("missing", "invalid"):
        print(f"stella: {health['error']}", file=sys.stderr)
        return 1
    # R52: under --json the dry-run branch below prints one JSON
    # document, so the dataset lines stay silent here — a prose
    # line ahead of the document would break a script's parse.
    if health["status"] == "ok" and not _as_json(args):
        print(
            f"Dataset: {health['count']} examples "
            f"({health['format']} format, about "
            f"{health['est_tokens']:,} tokens)."
        )
        if health["tiny"]:
            print(
                f"Warning: only {health['count']} examples. A tiny "
                "dataset teaches the model very little: it will "
                "memorize these rows, not generalize from them."
            )
    # Dry run (T85): answer fit / steps / disk from metadata only
    # (no model load) and stop — nothing trains.
    if args.dry_run:
        from .train import estimate_run, format_estimate

        estimate = estimate_run(
            store, args.profile, args.project,
            dataset_path=args.dataset, base_ref=args.base,
            cli=True,
            # v0.36.0 (N28): a capped run's dry run quotes the
            # capped steps and disk, like the run itself.
            max_steps=args.steps,
        )
        if _as_json(args):
            # R52: the structured form — the estimate itself. A
            # real run refuses --json (see main()); the dry run is
            # a report, so it honours it.
            _print_json(estimate)
            return 0
        print(format_estimate(estimate))
        return 0
    # Governing-seat warning (T116): a profile bound for a
    # governing seat whose base is not abliterated warns here,
    # naming the seat and the base. The CLI warns and proceeds
    # (like the tiny-dataset warning above), so scripted runs
    # never block on a prompt; the window asks instead.
    from .model import governing_seat_warning

    try:
        warning = governing_seat_warning(store.get_profile(args.profile))
    except StellaError:
        warning = None
    if warning:
        print(f"Warning: {warning}")
    controller = TrainController()
    events = {"last": 0}
    quiet = _is_quiet(args)
    # S21: the ETA anchors on the first step event seen, not on the
    # run's start: a resumed run's steps continue from the
    # checkpoint, so only steps completed in THIS run measure the
    # rate. The anchor is (step, clock) at the first step event.
    clock: dict = {"step": None, "at": None}

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "loading":
            # T108: the base load (a first run downloads it) is
            # said before it starts, so the wait is not a mystery.
            print(event.get("message", "Loading the base model."),
                  flush=True)
        elif kind == "started":
            print(
                f"Training: {event['total_steps']} steps, "
                f"LoRA rank {event['rank']} (CPU, batch 1. This is slow, "
                "checkpoints save as it goes)"
            )
        elif kind == "step":
            events["last"] = event["step"]
            # T172 --quiet: the per-step lines go silent on a long
            # run; the started/done lines still print.
            if quiet:
                return
            if clock["step"] is None:
                clock["step"] = event["step"]
                clock["at"] = time.monotonic()
            eta = _eta_text(
                time.monotonic() - clock["at"],
                event["step"] - clock["step"],
                event["total_steps"] - event["step"],
            )
            line = (
                f"step {event['step']}/{event['total_steps']} "
                f"epoch {event['epoch']} loss {event['loss']:.4f} "
                f"lr {event['lr']:.2e}"
            )
            if eta:
                line += f", {eta}"
            print(line, flush=True)
        elif kind == "checkpoint":
            if quiet:
                return
            print(f"checkpoint saved: step {event['step']}", flush=True)
        elif kind == "val":
            print(f"epoch {event['epoch']} validation loss {event['loss']:.4f}")
        elif kind == "warning":
            print(f"Warning: {event.get('message', '')}")
        elif kind == "extending":
            # A resume on a project that already finished training
            # extends it past the original run (T25): say so, with
            # the new total, before the steps print.
            print(
                f"This project already finished training "
                f"({event['trained_steps']} steps). Resuming extends "
                f"it to {event['new_total']} total steps."
            )
        elif kind == "paused":
            print(f"Paused at step {event['step']}. Resume with --resume.")
        elif kind == "done":
            print(f"Done. Adapter saved to {event['adapter']}")

    # Ctrl+C pauses cleanly: the loop checkpoints after the current
    # step and the run resumes with --resume. A hard kill mid-step
    # loses at most the steps since the last checkpoint.
    # The handler sets the flag ONLY — printing inside a signal
    # handler races with buffered stdout and crashed the pause
    # (audit #5 W1). The "paused" event prints.
    # T108: the SECOND Ctrl+C exits immediately. Raising SystemExit
    # from the handler interrupts even a blocking base download:
    # a handler that raises aborts the syscall instead of retrying
    # it, so the wait ends at once. Exit code 130 is the
    # conventional "killed by Ctrl+C".
    stops = {"count": 0}

    def _sigint(signum, frame):
        stops["count"] += 1
        if stops["count"] >= 2:
            raise SystemExit(130)
        controller.request_stop()

    old_handler = signal.signal(signal.SIGINT, _sigint)
    # T34: --target-modules is a comma-separated list; an absent
    # flag is None (auto-detection), never an empty list.
    target_modules = None
    if args.target_modules:
        target_modules = [
            name.strip()
            for name in args.target_modules.split(",")
            if name.strip()
        ] or None
    try:
        summary = train_project(
            store,
            args.profile,
            args.project,
            max_steps=args.steps,
            resume=args.resume,
            from_checkpoint=args.from_checkpoint,
            dataset_path=args.dataset,
            base_ref=args.base,
            force=args.force,
            target_modules=target_modules,
            on_event=on_event,
            controller=controller,
            cli=True,
        )
    finally:
        signal.signal(signal.SIGINT, old_handler)
    final_loss = summary["final_loss"]
    loss_text = f"{final_loss:.4f}" if final_loss is not None else "n/a"
    # T96: the val loss is the number that says whether the tune
    # generalized — the closing line carries it next to the
    # training loss.
    val_loss = summary.get("final_val_loss")
    val_text = f"{val_loss:.4f}" if val_loss is not None else "n/a"
    # T109: a paused run's tail says Paused, not Trained — the old
    # line reused the completed-run wording, so a user scanning
    # the tail saw a run that looked finished.
    if summary.get("stopped"):
        print(
            f"Paused after {summary['steps']} steps, "
            f"final loss {loss_text}, val loss {val_text}, "
            f"{summary['trainable_params']:,} trainable params, "
            # T35: this is the pre-run estimate, not a measurement.
            f"about {summary['ram_estimate_gb']} GB RAM (estimated)."
        )
    else:
        print(
            f"Trained {summary['steps']} steps, "
            f"final loss {loss_text}, val loss {val_text}, "
            f"{summary['trainable_params']:,} trainable params, "
            # T35: this is the pre-run estimate, not a measurement.
            f"about {summary['ram_estimate_gb']} GB RAM (estimated)."
        )
    return 0


def cmd_export_gguf(args) -> int:
    from .gguf import export_gguf

    store = _store()

    def on_event(event: dict):
        # T109: a line per phase, so a multi-minute export is never
        # silent — the merge line first, then convert, then quantize.
        # T152: the merge's base load is said too, with the model name.
        if event.get("type") == "loading" and event.get("message"):
            print(event["message"], flush=True)
        elif event.get("type") == "phase" and event.get("message"):
            print(event["message"], flush=True)

    # R81: the estimate the GUI shows, printed before the export
    # starts — a CLI user exports with the same size/time picture.
    # An estimate that cannot be computed (no adapter yet, unknown
    # base) is left to the export itself, which refuses with its
    # own plain-words error.
    try:
        from .gguf import estimate_export, format_export_estimate

        print(
            format_export_estimate(
                estimate_export(
                    store, args.profile, args.project, quant=args.quant
                )
            ),
            flush=True,
        )
    except StellaError:
        pass

    result = export_gguf(
        store,
        args.profile,
        args.project,
        args.dir,
        quant=args.quant,
        from_checkpoint=args.from_checkpoint,
        from_sleep=args.from_sleep,
        force=args.force,
        on_warning=print,  # T31: the converter warning, before the merge
        on_event=on_event,
    )
    print(f"Merged HF weights: {result['merged_hf']}")
    print(
        f"GGUF ({result['quant']}): {result['gguf']} "
        f"({result['gguf_bytes']:,} bytes)"
    )
    print(f"Modelfile: {result['modelfile']}")
    print()
    print("Create the Ollama model with:")
    print(f"  {result['ollama_create']}")
    print(f"Then run it: ollama run {result['ollama_name']}")
    print("(Or let Stella do it: add --create to the export command.)")
    if getattr(args, "create", False):
        # T89: --create runs the command instead of leaving it to
        # a copy-paste. The manual commands above are still printed.
        from .gguf import SUBPROCESS_TIMEOUT_SECONDS, create_in_ollama
        from .ollama import list_models, name_taken

        # v0.34.0: a model with the same name already in Ollama
        # is replaced only after the user says so (default No,
        # --yes skips the question) — the window asks the same
        # way before its one-click put.
        if name_taken(
            result["ollama_name"], list_models()
        ) and not getattr(args, "yes", False):
            if not _confirm_destructive(
                f"A model named {result['ollama_name']} is already "
                "in Ollama. Replace it?"
            ):
                print(
                    f"Left the Ollama model {result['ollama_name']} "
                    "as it was."
                )
                return 0
        output = create_in_ollama(
            result["ollama_name"], result["modelfile"],
            # R82: a hung Ollama create stops on a timeout instead
            # of hanging the export forever — the same 30 minutes
            # the converter and quantizer runs use.
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        print()
        print(f"Created in Ollama as {result['ollama_name']}.")
        if output:
            print(output)
    return 0


def cmd_probe(args) -> int:
    # R68: the CLI auto-detects like the GUI (T90) — a governing
    # profile is gated, every other profile probes
    # informationally. --informational forces informational on a
    # governing profile; --gate forces the gate on a
    # non-governing one. A missing profile is left for
    # probe_project to report (it raises the same clean error).
    from .probe import is_governing_profile, probe_gate, probe_project

    store = _store()
    if args.informational:
        informational = True
    elif getattr(args, "gate", False):
        informational = False
    else:
        try:
            informational = not is_governing_profile(
                store.get_profile(args.profile)
            )
        except StellaError:
            informational = False

    def on_event(event: dict):
        # T109: a line when each pass starts, so a probe that loads
        # two models and runs 24 generations is never silent.
        # T152: each base load is said before it starts, with the
        # model name.
        if event.get("type") == "loading" and event.get("message"):
            print(event["message"], flush=True)
        elif event.get("type") == "phase":
            if event.get("phase") == "before":
                print("Probing before tuning...", flush=True)
            elif event.get("phase") == "after":
                print("Probing after tuning...", flush=True)

    result = probe_project(
        store, args.profile, args.project,
        informational=informational,
        on_event=on_event,
    )
    if _as_json(args):
        # T172: the structured form — the whole probe result
        # (before/after counts, delta, probe set, mode) as one
        # JSON document. The gate verdict still goes to stderr
        # and the exit code still carries it, as in the human
        # form below.
        _print_json(result)
        if informational:
            return 0
        passed, message = probe_gate(result)
        print(message, file=sys.stderr)
        return 0 if passed else 3
    before = result["before"]
    after = result["after"]

    def _line(label, side):
        # T30: a silent prompt is named, not hidden inside a clean 0.
        text = (
            f"{label} {side['refusals']}/{side['total']} refusals "
            f"({side['rate']:.0%})"
        )
        if side.get("empty"):
            text += f", {side['empty']} with no answer"
        return text

    print(_line("Before tuning:", before))
    print(_line("After tuning: ", after))
    # T174: the probe set that ran — the role's set, or the
    # default set when the role has none.
    print(
        f"Probe set: {result.get('probe_set', 'default')} "
        f"({before.get('total', 0)} prompts)."
    )
    if result.get("probe_set_note"):
        print(f"Note: {result['probe_set_note']}")
    if informational:
        # T90: informational mode reports the counts and the
        # change, no pass/fail verdict — and exits 0 regardless
        # of what the change was.
        print(
            f"Change: {result['delta']:+.0%}. Informational only: "
            "no gate verdict."
        )
        return 0
    passed, message = probe_gate(result)
    # T91: the verdict goes to stderr, separate from the numbers
    # on stdout, so a script can read each on its own. (T172 adds
    # a --json verdict later; this is the hook it builds on.)
    print(message, file=sys.stderr)
    # T91: a failed gate exits 3 — distinct from a crash (1) and
    # from argparse's usage error (2) — so a script can tell
    # "the probe ran and the gate failed" from "the probe crashed".
    return 0 if passed else 3


def cmd_create_project(args) -> int:
    store = _store()
    kwargs: dict = {}
    # T112: a template pre-fills the dataset, settings, and mode.
    # Explicit flags win over the template, one field at a time.
    if getattr(args, "template", None):
        from .templates import load_template, template_project_kwargs

        kwargs.update(
            template_project_kwargs(load_template(args.template))
        )
    if args.dataset:
        kwargs["dataset_ref"] = args.dataset
    settings = _settings_from_args(args)
    if settings:
        merged = dict(kwargs.get("settings") or {})
        merged.update(settings)
        kwargs["settings"] = merged
    if getattr(args, "metamorph", None):
        kwargs["metamorph_mode"] = args.metamorph
    if getattr(args, "metamorph_notes", None):
        kwargs["metamorph_notes"] = args.metamorph_notes
    data = store.create_project(
        args.profile,
        args.name,
        display_name=args.display or "",
        **kwargs,
    )
    if _as_json(args):
        # R52: the structured form — the created record.
        _print_json(data)
        return 0
    print(
        f"Created project {data['name']!r}"
        f"{_normalized_note(args.name, data['name'])} "
        f"in profile {args.profile!r}"
    )
    return 0


def _fmt_loss(value) -> str:
    return f"{value:.4f}" if value is not None else "n/a"


def cmd_sleep(args) -> int:
    import signal

    from .sleep import sleep_project
    from .train import TrainController

    store = _store()
    controller = TrainController()
    quiet = _is_quiet(args)

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "loading":
            # T108: the base load is said before it starts (sleep
            # forwards train events).
            print(event.get("message", "Loading the base model."),
                  flush=True)
        elif kind == "started":
            resumed = " (resuming)" if event.get("resumed") else ""
            print(
                f"Sleep cycle {event['cycle']}{resumed}: "
                f"{event['new_rows']} new rows"
                + (
                    f", {event['dreamed_rows']} dreamed rows"
                    if event.get("dreamed_rows")
                    else ""
                )
                + "."
            )
        elif kind == "dream":
            print(
                f"Dreamed {event['kept']} practice rows "
                f"(asked for {event['requested']})."
            )
        elif kind == "dream_skipped":
            print(f"Dreaming skipped: {event['reason']}")
        elif kind == "step":
            # T172 --quiet: the per-step lines go silent.
            if quiet:
                return
            print(
                f"step {event['step']}/{event['total_steps']} "
                f"epoch {event['epoch']} loss {event['loss']:.4f} "
                f"lr {event['lr']:.2e}",
                flush=True,
            )
        elif kind == "checkpoint":
            if quiet:
                return
            print(f"checkpoint saved: step {event['step']}", flush=True)
        elif kind == "val":
            print(f"epoch {event['epoch']} validation loss {event['loss']:.4f}")
        elif kind == "warning":
            print(f"Warning: {event.get('message', '')}")
        elif kind == "replay":
            print("Replay check: old rows vs new adapter...")
        elif kind == "replay_done":
            print(
                f"old loss {_fmt_loss(event['old_loss_before'])} -> "
                f"{_fmt_loss(event['old_loss_after'])}, "
                f"new loss {_fmt_loss(event['new_loss'])}, "
                f"{event['status']}"
            )
        elif kind == "paused":
            print(f"Paused at step {event['step']}. Run sleep again to resume.")
        elif kind == "done":
            print(f"Sleep cycle {event['cycle']} done: {event['status']}.")

    # Ctrl+C pauses cleanly: the consolidation loop checkpoints after
    # the current step and the cycle resumes on the next sleep run.
    # The handler sets the flag ONLY — printing inside a signal
    # handler races with buffered stdout and crashed the train
    # command's pause (audit #5 W1). The "paused" event prints.
    # T108: the second Ctrl+C exits immediately (see cmd_train).
    stops = {"count": 0}

    def _sigint(signum, frame):
        stops["count"] += 1
        if stops["count"] >= 2:
            raise SystemExit(130)
        controller.request_stop()

    old_handler = signal.signal(signal.SIGINT, _sigint)
    try:
        report = sleep_project(
            store,
            args.profile,
            args.project,
            dream=args.dream,
            dream_model=args.dream_model,
            rows_path=args.rows,
            threshold=args.threshold,
            on_event=on_event,
            controller=controller,
        )
    finally:
        signal.signal(signal.SIGINT, old_handler)
    if report.get("status") == "paused":
        return 0
    delta = report.get("old_delta_relative")
    delta_text = f"{delta:+.1%}" if delta is not None else "n/a (no old rows yet)"
    print()
    print(f"Sleep cycle {report['cycle']}: {report['status']}")
    print(
        f"  rows: {report['real_rows']} new"
        + (
            f", {report['dreamed_rows']} dreamed"
            if report.get("dreamed_rows")
            else ""
        )
        + f", {report['steps']} steps, rank {report['rank']}"
    )
    print(f"  old loss: {_fmt_loss(report['old_loss_before'])} -> "
          f"{_fmt_loss(report['old_loss_after'])} ({delta_text})")
    print(f"  new loss: {_fmt_loss(report['new_loss'])}")
    if report["status"] == "DEGRADED":
        print(
            "  The new adapter forgot old rows. The cycle is saved "
            "but flagged. Check the new rows before using this adapter."
        )
    return 0


def cmd_sleep_status(args) -> int:
    from .sleep import sleep_status

    store = _store()
    status = sleep_status(store, args.profile, args.project)
    if _as_json(args):
        # T172: the structured form — the whole sleep status.
        _print_json(status)
        return 0
    cycles = status["cycles"]
    if not cycles:
        print(f"No sleep cycles yet for {args.project!r}.")
    else:
        for c in cycles:
            delta = None
            before = c.get("old_loss_before")
            after = c.get("old_loss_after")
            if before is not None and after is not None and before > 0:
                delta = (after - before) / before
            delta_text = f"{delta:+.1%}" if delta is not None else "n/a"
            print(
                f"cycle {c['cycle']}: {c['status']}, "
                f"{c['real_rows']} new rows, {c['dreamed_rows']} dreamed, "
                f"{c['steps']} steps, old-loss delta {delta_text}, "
                f"{_fmt_size(c.get('size_bytes') or 0)}"
            )
        # R66: what all the cycles cost together.
        print(
            f"Sleep cycles use {_fmt_size(status.get('total_size_bytes') or 0)} "
            f"on disk ({len(cycles)} cycle{'s' if len(cycles) != 1 else ''})."
        )
    # R8: a cycle whose input file is gone cannot be recovered —
    # say so plainly, with what happens next (its rows sleep again
    # in a later cycle; its adapter stays on disk).
    for u in status.get("unhealed_cycles", []):
        print(
            f"cycle {u['cycle']} could not be recovered: "
            f"{u['reason']}. Those rows will sleep again in a "
            "later cycle."
        )
    total = status["total_rows"]
    unslept = status["unslept_rows"]
    if total is not None:
        print(
            f"{status['slept_rows']} rows slept on, {unslept} of {total} "
            "still awake."
        )
    else:
        print(
            f"{status['slept_rows']} rows slept on "
            "(no dataset set, so unslept rows are unknown)."
        )
    return 0


def cmd_sleep_delete(args) -> int:
    """Delete one sleep cycle for good (R66).

    v0.35.0 (N16): like delete-checkpoint, this asks first
    (default No) unless --yes was given - a typo must not delete
    a cycle's adapter the instant Enter is pressed."""
    from .sleep import delete_sleep_cycle, list_sleep_cycles

    store = _store()
    # Like delete-checkpoint: a cycle that does not exist is a
    # plain error, named before any question is asked.
    known = any(
        c.get("cycle") == args.cycle
        for c in list_sleep_cycles(store, args.profile, args.project)
    )
    cycle_dir = (
        store.project_dir(args.profile, args.project)
        / "sleep" / f"cycle-{args.cycle}"
    )
    if not known and not cycle_dir.is_dir():
        # Raises the plain "no sleep cycle" error.
        delete_sleep_cycle(store, args.profile, args.project, args.cycle)
    if not getattr(args, "yes", False):
        if not _confirm_destructive(
            f"Delete sleep cycle {args.cycle} of project "
            f"{args.project!r} forever? This cannot be undone."
        ):
            print(
                f"Kept sleep cycle {args.cycle}.", file=sys.stderr
            )
            return 1
    result = delete_sleep_cycle(
        store, args.profile, args.project, args.cycle
    )
    print(
        f"Deleted sleep cycle {result['cycle']}, freed "
        f"{_fmt_size(result['freed_bytes'])}."
    )
    return 0


def cmd_sleep_prune(args) -> int:
    """Delete all but the newest N sleep cycles (R66).

    v0.35.0 (N16): asks first (default No) unless --yes was
    given, like delete-checkpoint. When nothing would be
    pruned there is nothing to confirm."""
    from .sleep import list_sleep_cycles, prune_sleep_cycles

    store = _store()
    cycles = list_sleep_cycles(store, args.profile, args.project)
    doomed = cycles[:-args.keep] if len(cycles) > args.keep else []
    if doomed and not getattr(args, "yes", False):
        if not _confirm_destructive(
            f"Delete {len(doomed)} old sleep cycle"
            f"{'s' if len(doomed) != 1 else ''} of project "
            f"{args.project!r} forever, keeping the newest "
            f"{args.keep}? This cannot be undone."
        ):
            print("Kept every sleep cycle.", file=sys.stderr)
            return 1
    result = prune_sleep_cycles(
        store, args.profile, args.project, keep=args.keep
    )
    if not result["deleted"]:
        print(
            f"Nothing to prune: {len(result['kept'])} cycle"
            f"{'s' if len(result['kept']) != 1 else ''} kept, "
            f"keeping the newest {args.keep}."
        )
        return 0
    print(
        f"Pruned {len(result['deleted'])} sleep cycle"
        f"{'s' if len(result['deleted']) != 1 else ''}, freed "
        f"{_fmt_size(result['freed_bytes'])}. Sleep cycles now use "
        f"{_fmt_size(result['total_after'])}."
    )
    return 0


def cmd_chat(args) -> int:
    """Talk to Stella: the same agent core as the Chat window, as a
    small read-a-line loop. /quit (or Ctrl+C / Ctrl+D) exits."""
    from .chat_agent import ChatAgent
    from .ollama import list_models
    from .providers import (
        PROVIDERS,
        get_custom_config,
        has_key,
        missing_key_message,
    )

    store = _store()
    provider = (args.provider or "ollama").strip() or "ollama"
    model = (args.model or "").strip()
    if provider != "ollama":
        if not model:
            if provider == "custom":
                model = get_custom_config(store.home).get("model", "")
            elif PROVIDERS[provider]["models"]:
                model = PROVIDERS[provider]["models"][0]
        if not model:
            # R54: the pre-flight failures go to stderr, not
            # stdout — they are errors, and a script reading
            # stdout should not have to tell them from output.
            print(
                "Custom provider needs a model name. Pass --model "
                "<name>, or set one in Settings under AI providers.",
                file=sys.stderr,
            )
            return 1
        if not has_key(store.home, provider):
            print(missing_key_message(provider), file=sys.stderr)
            return 1
    if not model:
        models = list_models()
        if not models:
            print(
                "Ollama is not answering, so I cannot see which models "
                "are installed. Start Ollama and try again, or pass "
                "--model <tag>.",
                file=sys.stderr,
            )
            return 1
        print("Which model should I chat with?")
        for name in models:
            print(f"  {name}")
        try:
            picked = input("Model: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if picked not in models:
            print(f"No model called {picked!r}.", file=sys.stderr)
            return 1
        model = picked
    # R14: the CLI chat used to go silent for the whole run — the
    # agent's narration and progress callbacks were never wired,
    # so an hours-long training run showed nothing until it ended.
    # The GUI shows these as chat lines; here they print as they
    # come, flushed, ahead of the final "Stella:" reply.
    agent = ChatAgent(
        store, model, provider=provider,
        on_narration=lambda text: print(text, flush=True),
        on_progress=lambda text: print(text, flush=True),
    )
    print(
        "Hi. Tell me what you want to train, and I will set it up "
        "and run it for you. Type /quit to exit."
    )
    while True:
        try:
            line = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        text = line.strip()
        if not text:
            continue
        if text == "/quit":
            return 0
        print(f"Stella: {agent.reply(text)}")
        # R106: a cloud reply says what it used, in tokens. Local
        # Ollama reports no counts, so nothing shows for it.
        usage_fn = getattr(agent, "last_usage_text", None)
        if callable(usage_fn):
            usage_text = usage_fn() or ""
            if usage_text:
                print(usage_text)
        print()
    return 0


def _fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.0f} MB"
    return f"{n:,} bytes"


def cmd_requant(args) -> int:
    from .requant import requant_model

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "found":
            source_quant = event.get("source_quant") or "unknown quant"
            print(
                f"Found {event['source_tag']} "
                f"({_fmt_size(event['source_bytes'])}, {source_quant}). "
                f"Shrinking to {event['quant']} as {event['new_tag']}..."
            )
            if event.get("requantize_warning"):
                print(event["requantize_warning"])
        elif kind == "quantize_progress":
            print(
                f"shrinking... tensor {event['done']} of "
                f"{event['total']}",
                flush=True,
            )
        elif kind == "still_working":
            print("Still shrinking the model...", flush=True)
        elif kind == "quantized":
            print(
                f"Shrunk: {_fmt_size(event['source_bytes'])} -> "
                f"{_fmt_size(event['output_bytes'])}."
            )
        elif kind == "created":
            print(f"Registered with Ollama as {event['new_tag']}.")

    result = requant_model(
        args.tag,
        quant=args.quant,
        new_tag=args.as_tag,
        on_event=on_event,
    )
    print()
    print(
        f"Done. {result['new_tag']} is "
        f"{_fmt_size(result['output_bytes'])} "
        f"(was {_fmt_size(result['source_bytes'])}), {result['quant']}."
    )
    print(f"Run it: {result['ollama_run']}")
    print(f"The original {result['source_tag']} is untouched.")
    return 0


def cmd_bridge(args) -> int:
    from .ollama_bridge import (
        format_bridge_report,
        modelfile_blob_hint,
        suggest_hf_repos,
    )

    if _as_json(args):
        # R52: the structured form — the candidate repos, as one
        # JSON document.
        _print_json({
            "tag": args.tag,
            "suggestions": suggest_hf_repos(args.tag),
            "hint": modelfile_blob_hint(args.tag),
        })
        return 0
    print(format_bridge_report(args.tag))
    return 0


def _key_provider(raw: str) -> str:
    """The keyed provider a key command names (R54): groq, gemini,
    or custom. Ollama needs no key, and anything else is refused
    in plain words."""
    from .providers import KEYED_PROVIDERS

    provider = (raw or "").strip().lower()
    if provider == "ollama":
        raise StellaError("Ollama runs on this PC and needs no key.")
    if provider not in KEYED_PROVIDERS:
        raise StellaError(
            f"no keyed provider called {raw!r} "
            "(groq, gemini, or custom)"
        )
    return provider


def _read_key_secret(prompt: str) -> str:
    """Read a key without showing it (R54): getpass on a terminal,
    one line from stdin when piped (a script feeding a key). The
    key is never echoed and never printed back."""
    if sys.stdin.isatty():
        import getpass

        try:
            return getpass.getpass(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""
    try:
        return sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def cmd_save_key(args) -> int:
    """Save a cloud provider key from the CLI (R54): the same
    0600 providers.json the Settings window writes, so cloud chat
    works from the terminal too. For custom, --base-url and
    --model set the address and model name alongside the key."""
    from .providers import PROVIDERS, save_key

    store = _store()
    provider = _key_provider(args.provider)
    display = PROVIDERS[provider]["display"]
    key = _read_key_secret(f"Paste the {display} key: ")
    if not key:
        print("stella: paste a key first.", file=sys.stderr)
        return 1
    save_key(
        store.home, provider, key,
        base_url=getattr(args, "base_url", "") or "",
        model=getattr(args, "model", "") or "",
    )
    if _as_json(args):
        # R52: the structured form — the provider and the fact it
        # saved, never the key itself.
        _print_json({"provider": provider, "saved": True})
        return 0
    print(f"Saved the {display} key.")
    return 0


def cmd_list_keys(args) -> int:
    """Which providers have a key saved (R54): status words only,
    never the keys themselves."""
    from .providers import PROVIDERS, provider_presence

    store = _store()
    presence = provider_presence(store.home)
    if _as_json(args):
        # R52: the structured form — status words per provider.
        _print_json(presence)
        return 0
    for pid, status in presence.items():
        print(f"{PROVIDERS[pid]['display']}: {status}.")
    return 0


def cmd_remove_key(args) -> int:
    """Forget a saved provider key (R54). No error when none was
    saved — it just says so."""
    from .providers import PROVIDERS, has_key, remove_key

    store = _store()
    provider = _key_provider(args.provider)
    had = has_key(store.home, provider)
    remove_key(store.home, provider)
    display = PROVIDERS[provider]["display"]
    if _as_json(args):
        # R52: the structured form — whether a key was there to
        # remove.
        _print_json({"provider": provider, "removed": had})
        return 0
    if had:
        print(f"Removed the {display} key.")
    else:
        print(f"No {display} key was saved.")
    return 0


def cmd_mark_ready(args) -> int:
    """Mark a project ready to train (R112): the CLI twin of the
    Project window's Mark ready button. Status is informational
    only — training never gates on it — so this is a display
    change, not a workflow gate."""
    store = _store()
    data = store.update_project(args.profile, args.name, status="ready")
    if _as_json(args):
        _print_json(data)
        return 0
    print(
        f"Marked project {data['name']!r} in profile "
        f"{args.profile!r} ready."
    )
    return 0


def cmd_notes(args) -> int:
    """Read (or write) a project's notes (R112): the CLI twin of
    the Project window's notes area. Reads by default; --set
    writes through write_notes, so the rotating notes.md.1 backup
    still happens."""
    store = _store()
    if getattr(args, "set", None) is not None:
        store.write_notes(args.profile, args.name, args.set)
        if _as_json(args):
            _print_json({
                "profile": args.profile,
                "project": args.name,
                "notes": args.set,
            })
            return 0
        print(
            f"Saved notes for project {args.name!r} in profile "
            f"{args.profile!r}."
        )
        return 0
    # Read: the project must exist — read_notes returns "" for a
    # missing project too, so check first, or a typo reads as an
    # empty notebook.
    store.get_project(args.profile, args.name)
    notes = store.read_notes(args.profile, args.name)
    if _as_json(args):
        _print_json({
            "profile": args.profile,
            "project": args.name,
            "notes": notes,
        })
        return 0
    if notes:
        print(notes, end="" if notes.endswith("\n") else "\n")
    else:
        print(f"No notes for project {args.name!r} yet.")
    return 0


def cmd_probe_results(args) -> int:
    """Show the saved refusal-probe results (R112): reads
    probe_results.json and pretty-prints it — never re-runs the
    probe. Fails plainly when no results file exists yet."""
    from .probe import load_probe_results, probe_gate

    store = _store()
    store.get_project(args.profile, args.name)
    result = load_probe_results(store, args.profile, args.name)
    if result is None:
        raise StellaError(
            f"no probe results for project {args.name!r} in profile "
            f"{args.profile!r} yet. Run the probe first: stella "
            f"probe {args.profile} {args.name}"
        )
    if _as_json(args):
        _print_json(result)
        return 0
    before = result.get("before") or {}
    after = result.get("after") or {}
    print(
        f"Refusals: {before.get('refusals', 0)}/"
        f"{before.get('total', 0)} before, "
        f"{after.get('refusals', 0)}/{after.get('total', 0)} after "
        f"(change {result.get('delta', 0):+.0%})."
    )
    if result.get("probe_set"):
        print(
            f"Probe set: {result['probe_set']} "
            f"({before.get('total', 0)} prompts)."
        )
    if result.get("probe_set_note"):
        print(f"Note: {result['probe_set_note']}")
    if result.get("mode", "gate") == "informational":
        print(
            "Informational only: this probe does not pass or fail "
            "anything."
        )
    else:
        _passed, verdict = probe_gate(result)
        print(verdict)
    return 0


def cmd_howto(args) -> int:
    """Print a How to Use topic (R112): the guide, on the
    terminal. No topic lists the topics. A topic name matches
    case-insensitively, so `stella howto training` finds
    Training."""
    from .howto import topic_text, topic_titles

    topic = (args.topic or "").strip()
    if not topic:
        print("How to Use topics:")
        for title in topic_titles():
            print(f"  {title}")
        print("Read one with: stella howto <topic>")
        return 0
    body = topic_text(topic)
    if body is None:
        for title in topic_titles():
            if title.lower() == topic.lower():
                body = topic_text(title)
                break
    if body is None:
        raise StellaError(
            f"no How to Use topic called {topic!r}. Run stella "
            "howto to list the topics."
        )
    print(body)
    return 0


def cmd_debug_report(args) -> int:
    """Write the debug report (R112): the same report the
    Settings window writes — same logger, same settings, same
    services and dependencies — from the terminal."""
    from .debug_log import DebugLogger, check_ollama
    from .ollama import ollama_url
    from .providers import provider_presence

    store = _store()
    log = DebugLogger(
        "stella", STELLA_VERSION, log_dir=str(store.home / "logs")
    )
    log.set_setting("home", str(store.home))
    log.set_setting("chat_providers", provider_presence(store.home))
    log.register_service("ollama", lambda: check_ollama(ollama_url()))
    for dep in (
        "PySide6",
        "torch",
        "transformers",
        "peft",
        "huggingface_hub",
    ):
        log.register_dependency(dep)
    path = log.generate_report()
    if _as_json(args):
        _print_json({"report": str(path)})
        return 0
    print(f"Debug report written to:\n{path}")
    return 0


def cmd_distill(args) -> int:
    from .distill import distill_dataset

    store = _store()
    quiet = _is_quiet(args)
    # S21: the ETA anchors on the first prompt event. A prompt
    # event fires BEFORE its prompt is asked, so at prompt N,
    # N - 1 prompts are done and total - (N - 1) are still to go
    # (the one about to be asked included).
    clock: dict = {"at": None}

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "warning":
            # R30/R35: a failed or cut-off prompt says so as it
            # happens, even under --quiet — it is a result, not
            # progress chatter.
            print(event.get("message", ""), flush=True)
            return
        if kind == "prompt":
            # T172 --quiet: the per-prompt lines go silent.
            if quiet:
                return
            if clock["at"] is None:
                clock["at"] = time.monotonic()
            done = event["index"] - 1
            eta = _eta_text(
                time.monotonic() - clock["at"],
                done,
                event["total"] - done,
            )
            line = f"prompt {event['index']} of {event['total']}"
            if eta:
                line += f", {eta}"
            print(line, flush=True)

    report = distill_dataset(
        store,
        args.profile,
        args.project,
        args.teacher,
        args.prompts,
        timeout=args.timeout,
        on_event=on_event,
    )
    print()
    print(
        f"Asked the teacher {report['asked']} prompt(s), "
        f"kept {report['rows']} answer(s)."
    )
    if report["skipped_empty"]:
        print(
            f"  {report['skipped_empty']} empty answer(s) skipped."
        )
    if report["skipped_dup"]:
        print(
            f"  {report['skipped_dup']} duplicate answer(s) skipped."
        )
    if report["skipped_resumed"]:
        print(
            f"  {report['skipped_resumed']} prompt(s) already answered "
            "in an earlier run."
        )
    if report.get("failed"):
        print(
            f"  {report['failed']} prompt(s) got no answer from the "
            "teacher. The answers so far are saved; run it again "
            "to pick up where it stopped."
        )
    if report.get("skipped_truncated"):
        print(
            f"  {report['skipped_truncated']} answer(s) were cut off "
            "mid-sentence and were not saved."
        )
    print(f"Dataset saved: {report['dataset']}")
    print(
        "The project now points at it. Train it with:"
    )
    print(f"  stella train {args.profile} {args.project}")
    return 0


def _positive_int(value: str) -> int:
    """Argparse type for --steps (T56): a whole number, at least 1.
    0 or a negative number is refused by argparse with a plain
    message, before the command runs."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a whole number."
        ) from None
    if number <= 0:
        raise argparse.ArgumentTypeError("--steps must be at least 1.")
    return number


def _positive_timeout(value: str) -> float:
    """Argparse type for distill --timeout (S3): a number of
    seconds, more than 0. Anything else is refused by argparse
    with a plain message, before the command runs."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a number of seconds."
        ) from None
    if number <= 0:
        raise argparse.ArgumentTypeError(
            "--timeout must be more than 0 seconds."
        )
    return number


def _format_duration(seconds: float) -> str:
    """Seconds as plain words: 40 seconds, 3 minutes,
    1 hour 5 minutes. (The GUI's run-stats label formats the same
    way; this is the terminal's copy.)"""
    total = int(max(0, round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minutes"
    if minutes:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{secs} second{'s' if secs != 1 else ''}"


def _eta_text(
    elapsed: float, done: int, remaining: int, *, min_samples: int = 2
) -> str:
    """The time-left tail for a progress line (S21): "about 25
    minutes left", from the rate so far (done units in elapsed
    seconds) times the units still to go. Empty when the rate is
    not meaningful yet: fewer than min_samples completed units,
    nothing left, or no time measured. A single sample never
    produces an ETA, so no line ever shows a bogus one."""
    if done < min_samples or remaining <= 0 or elapsed <= 0:
        return ""
    seconds_left = remaining * (elapsed / done)
    return f"about {_format_duration(seconds_left)} left"


def _global_flags_parser() -> argparse.ArgumentParser:
    """The global flags (T172), as a parent parser every
    subcommand inherits: --json, --quiet, --verbose. The defaults
    are SUPPRESS on the subcommands, so a flag given BEFORE the
    subcommand (`stella --json profiles`) is not clobbered by the
    subcommand's own default — the top parser (below) carries the
    real False defaults."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS,
        help="print the result as JSON, for scripts (not on train, "
        "sleep, distill, export-gguf, requant, pull-weights, or "
        "chat, which print progress as they run).",
    )
    parent.add_argument(
        "--quiet", action="store_true", default=argparse.SUPPRESS,
        help="silence the per-step progress lines on a long run "
        "(train, sleep, distill, pull-weights).",
    )
    parent.add_argument(
        "--verbose", action="store_true", default=argparse.SUPPRESS,
        help="print the full traceback when a command fails, "
        "instead of just the clean error line.",
    )
    return parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stella", description="Stella: fine-tune models on your own PC."
    )
    parser.add_argument("--version", action="version", version=f"stella {STELLA_VERSION}")
    # T172: the global flags on the top parser too, so they work
    # before the subcommand (`stella --json profiles`) as well as
    # after it (`stella profiles --json`). The top parser carries
    # the False defaults; the subcommands SUPPRESS theirs.
    parser.add_argument(
        "--json", action="store_true", default=False,
        help="print the result as JSON, for scripts (not on train, "
        "sleep, distill, export-gguf, requant, pull-weights, or "
        "chat, which print progress as they run).",
    )
    parser.add_argument(
        "--quiet", action="store_true", default=False,
        help="silence the per-step progress lines on a long run "
        "(train, sleep, distill, pull-weights).",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False,
        help="print the full traceback when a command fails, "
        "instead of just the clean error line.",
    )
    # T187: the subcommand is NOT required — bare `stella` prints
    # the command list (main() shows the top --help) instead of
    # argparse's "arguments are required" error.
    sub = parser.add_subparsers(dest="command", required=False)
    _globals = _global_flags_parser()

    def _cmd(name, text, epilog):
        """A subcommand whose help keeps its example lines: the
        default formatter would collapse the epilog into one
        wrapped paragraph (T51). For a user who hand-types from a
        phone screen, --help is the manual — every command shows
        a worked example."""
        return sub.add_parser(
            name, help=text, description=text, epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            parents=[_globals],
        )

    p = _cmd("profiles", "list profiles",
             "examples:\n  stella profiles")
    p.set_defaults(func=cmd_profiles)

    p = _cmd("projects", "list projects in a profile",
             "examples:\n  stella projects lfm3-tool")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.set_defaults(func=cmd_projects)

    p = _cmd("export", "export a project package",
             "examples:\n  stella export lfm3-tool tool-calls ~/exports\n"
             "  stella export lfm3-tool tool-calls ~/exports "
             "--bundle-dataset")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("dir", help="folder to write the package into")
    p.add_argument(
        "--bundle-dataset", action="store_true",
        help="copy the project's dataset file into the package, so "
        "it trains on a PC that does not have the dataset.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="overwrite an existing export folder instead of "
        "refusing (T117).",
    )
    p.add_argument(
        "--zip", action="store_true",
        help="write a single .stella file instead of a folder "
        "(T171): the zip holds exactly the folder package, and "
        "import reads it back the same way.",
    )
    p.set_defaults(func=cmd_export)

    p = _cmd("export-profile", "export a profile package",
             "examples:\n"
             "  stella export-profile lfm3-tool ~/exports\n"
             "  stella export-profile lfm3-tool ~/exports --with-projects")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("dir", help="folder to write the package into")
    p.add_argument(
        "--with-projects", action="store_true",
        help="include every project in the profile, each with its "
        "weights, checkpoints, and notes. Without it, the package "
        "holds the profile alone.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="overwrite an existing export folder instead of "
        "refusing (T117).",
    )
    p.add_argument(
        "--zip", action="store_true",
        help="write a single .stella file instead of a folder "
        "(T171): the zip holds exactly the folder package, and "
        "import reads it back the same way.",
    )
    p.set_defaults(func=cmd_export_profile)

    p = _cmd("export-recipe", "export a recipe package (settings only)",
             "examples:\n"
             "  stella export-recipe lfm3-tool tool-calls ~/exports\n"
             "  stella export-recipe lfm3-tool tool-calls ~/exports --zip")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("dir", help="folder to write the package into")
    p.add_argument(
        "--force", action="store_true",
        help="overwrite an existing export folder instead of "
        "refusing (T117).",
    )
    p.add_argument(
        "--zip", action="store_true",
        help="write a single .stella file instead of a folder "
        "(T171): the zip holds exactly the folder package, and "
        "import reads it back the same way.",
    )
    p.set_defaults(func=cmd_export_recipe)

    p = _cmd("export-adapter", "export a bare adapter package",
             "examples:\n"
             "  stella export-adapter lfm3-tool tool-calls ~/exports\n"
             "  stella export-adapter lfm3-tool tool-calls ~/exports --zip")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("dir", help="folder to write the package into")
    p.add_argument(
        "--force", action="store_true",
        help="overwrite an existing export folder instead of "
        "refusing (T117).",
    )
    p.add_argument(
        "--zip", action="store_true",
        help="write a single .stella file instead of a folder "
        "(T171): the zip holds exactly the folder package, and "
        "import reads it back the same way.",
    )
    p.set_defaults(func=cmd_export_adapter)

    p = _cmd("import-adapter", "import an adapter package",
             "examples:\n"
             "  stella import-adapter "
             "~/exports/tool-calls-stella-adapter-export\n"
             "  stella import-adapter "
             "~/exports/tool-calls-stella-adapter-export "
             "--into-profile lfm3-tool --into-project tool-calls-2")
    p.add_argument(
        "dir",
        help="folder or .stella file holding the adapter package",
    )
    p.add_argument(
        "--into-profile", default=None,
        help="import the adapter into an existing project in this "
        "profile (with --into-project): the project's base must "
        "match the adapter's base. Without it, a new project is "
        "created around the adapter.",
    )
    p.add_argument(
        "--into-project", default=None,
        help="the existing project to import the adapter into "
        "(with --into-profile).",
    )
    p.add_argument(
        "--profile-merge", choices=["keep", "take"], default=None,
        help="when the profile already exists and the package's tag, "
        "role or base differ: keep uses this profile's values, take "
        "uses the package's. Without this flag Stella asks, or keeps "
        "yours when it cannot ask.",
    )
    p.add_argument(
        "--preview", action="store_true",
        help="show what the package is and what it carries, and "
        "import nothing.",
    )
    p.set_defaults(func=cmd_import_adapter)

    p = _cmd("pull-weights", "download a base model's weights",
             "examples:\n"
             "  stella pull-weights LiquidAI/LFM3-1.7B")
    p.add_argument(
        "repo",
        help="Hugging Face repo id, e.g. LiquidAI/LFM3-1.7B",
    )
    p.set_defaults(func=cmd_pull_weights)

    p = _cmd("verify", "check an export package without importing it",
             "examples:\n  stella verify ~/exports/tool-calls-stella-export")
    p.add_argument("dir", help="folder holding the package to check")
    p.set_defaults(func=cmd_verify)

    p = _cmd("import", "import an export package",
             "examples:\n  stella import ~/exports/lfm3-tool-tool-calls\n"
             "  stella import ~/exports/lfm3-tool-tool-calls "
             "--profile-merge take")
    p.add_argument(
        "dir",
        help="folder or .stella file holding the package to import",
    )
    p.add_argument(
        "--profile-merge", choices=["keep", "take"], default=None,
        help="when the profile already exists and the package's tag, "
        "role or base differ: keep uses this profile's values, take "
        "uses the package's. Without this flag Stella asks, or keeps "
        "yours when it cannot ask.",
    )
    p.add_argument(
        "--preview", action="store_true",
        help="show what the package is and what it carries, and "
        "import nothing.",
    )
    p.add_argument(
        "--as-copy", action="store_true",
        help="when the project already exists, import it as a copy "
        "under a new name (<name>-copy) instead of refusing (T117).",
    )
    p.add_argument(
        "--replace", action="store_true",
        help="when the project already exists, move the old project "
        "to the trash and import over it (T117).",
    )
    p.set_defaults(func=cmd_import)

    p = _cmd(
        "create-profile", "create a profile",
        "examples:\n"
        "  stella create-profile lfm3 --tag lfm3:1.7b --role fast "
        "--base LiquidAI/LFM3-1.7B\n"
        "  stella create-profile lfm3 --tag lfm3:1.7b",
    )
    p.add_argument("name", help="profile name, e.g. lfm3")
    p.add_argument("--tag", default="",
                   help="Ollama tag of the model this profile uses "
                   "(e.g. lfm3:1.7b)")
    p.add_argument("--role", default="",
                   help="what this profile is for, in plain words "
                   "(e.g. fast)")
    p.add_argument("--display", default="",
                   help="display name shown in the window (defaults to "
                   "the profile name)")
    p.add_argument("--base", default="",
                   help="Hugging Face repo or local folder of the base "
                   "weights (for training, e.g. LiquidAI/LFM3-1.7B)")
    p.set_defaults(func=cmd_create_profile)

    p = _cmd(
        "create-project", "create a project in a profile",
        "examples:\n"
        "  stella create-project lfm3-tool tool-calls "
        "--dataset sample-tool-calls.jsonl\n"
        "  stella create-project lfm3-tool tool-calls "
        "--template lfm3-tool-format",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument("--display", default="",
                   help="display name shown in the window (defaults to "
                   "the project name)")
    p.add_argument("--dataset", default="",
                   help="dataset file for this project (.jsonl, "
                   "e.g. sample-tool-calls.jsonl)")
    p.add_argument("--template", default=None,
                   help="start from a project template (e.g. "
                   "lfm3-tool-format): its dataset, settings, and "
                   "mode. Explicit flags win over the template.")
    # R110: "Mode", like the window says (T71) — the product
    # name never appears in a visible string. The mode is a
    # label stored with the project; it does not change training
    # (audit-7: a morph run and a compress run train identically).
    p.add_argument("--metamorph", default=None,
                   choices=["morph", "compress", "both"],
                   help="Mode for this project: morph, compress, "
                   "or both (default morph). A label stored with "
                   "the project; it does not change training.")
    p.add_argument("--metamorph-notes", default=None,
                   help="why this metamorph mode (shown with the "
                   "project)")
    _add_setting_flags(p)
    p.set_defaults(func=cmd_create_project)

    # -- T87: rename, delete, update, show (profiles + projects) --
    p = _cmd("rename-profile", "rename a profile",
             "examples:\n  stella rename-profile lfm3 lfm3-tool")
    p.add_argument("old", help="current profile name")
    p.add_argument("new", help="new profile name")
    p.set_defaults(func=cmd_rename_profile)

    p = _cmd("delete-profile", "delete a profile (to the trash)",
             "examples:\n"
             "  stella delete-profile lfm3-tool\n"
             "  stella delete-profile lfm3-tool --purge")
    p.add_argument("name", help="profile name, e.g. lfm3-tool")
    p.add_argument(
        "--purge", action="store_true",
        help="delete forever instead of moving to the trash.",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="purge without asking first (for scripts).",
    )
    p.set_defaults(func=cmd_delete_profile)

    p = _cmd("update-profile", "change a profile",
             "examples:\n"
             "  stella update-profile lfm3-tool --role fast "
             "--tag lfm3:1.7b\n"
             "  stella update-profile lfm3-tool "
             "--config '{\"key\": \"value\"}' --dependencies a,b")
    p.add_argument("name", help="profile name, e.g. lfm3-tool")
    p.add_argument("--role", default=None,
                   help="what this profile is for, in plain words")
    p.add_argument("--tag", default=None,
                   help="Ollama tag of the model this profile uses")
    p.add_argument("--display", default=None,
                   help="display name shown in the window")
    p.add_argument("--base", default=None,
                   help="Hugging Face repo or local folder of the base "
                   "weights")
    p.add_argument("--config", default=None,
                   help="profile config as a JSON object, e.g. "
                   "'{\"key\": \"value\"}' (replaces the whole config)")
    p.add_argument("--dependencies", default=None,
                   help="dependencies as a comma-separated list, e.g. "
                   "torch,transformers (replaces the whole list)")
    p.add_argument("--governing-seat", default=None,
                   help="the Forge governing seat this profile is bound "
                   "for: driver, reviewer, tester, or fast (empty to "
                   "clear it)")
    p.set_defaults(func=cmd_update_profile)

    p = _cmd("show-profile", "show a profile's record",
             "examples:\n  stella show-profile lfm3-tool")
    p.add_argument("name", help="profile name, e.g. lfm3-tool")
    p.set_defaults(func=cmd_show_profile)

    p = _cmd("clone-profile", "copy a profile under a new name",
             "examples:\n"
             "  stella clone-profile lfm3-tool lfm3-tool-2\n"
             "  stella clone-profile lfm3-tool lfm3-tool-2 "
             "--with-projects")
    p.add_argument("name", help="profile name, e.g. lfm3-tool")
    p.add_argument("new_name", metavar="new-name",
                   help="name for the copy, e.g. lfm3-tool-2")
    p.add_argument(
        "--with-projects", action="store_true",
        help="copy the profile's projects too (each copy starts "
        "with no checkpoints and fresh notes). Without it, the "
        "copy has no projects.",
    )
    p.set_defaults(func=cmd_clone_profile)

    p = _cmd("rename-project", "rename a project",
             "examples:\n"
             "  stella rename-project lfm3-tool tool-calls tool-calls-2")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("old", help="current project name")
    p.add_argument("new", help="new project name")
    p.set_defaults(func=cmd_rename_project)

    p = _cmd("delete-project", "delete a project (to the trash)",
             "examples:\n"
             "  stella delete-project lfm3-tool tool-calls\n"
             "  stella delete-project lfm3-tool tool-calls --purge")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument(
        "--purge", action="store_true",
        help="delete forever instead of moving to the trash.",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="purge without asking first (for scripts).",
    )
    p.set_defaults(func=cmd_delete_project)

    p = _cmd("update-project", "change a project",
             "examples:\n"
             "  stella update-project lfm3-tool tool-calls "
             "--metamorph both --rank 16")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument("--display", default=None,
                   help="display name shown in the window")
    p.add_argument("--dataset", default=None,
                   help="dataset file for this project (.jsonl)")
    # R110: "Mode", like the window says (T71) — see
    # create-project above.
    p.add_argument("--metamorph", default=None,
                   choices=["morph", "compress", "both"],
                   help="Mode for this project: morph, compress, "
                   "or both. A label stored with the project; it "
                   "does not change training.")
    p.add_argument("--metamorph-notes", default=None,
                   help="why this metamorph mode (shown with the "
                   "project)")
    _add_setting_flags(p)
    p.set_defaults(func=cmd_update_project)

    p = _cmd("show-project", "show a project's record and checkpoints",
             "examples:\n  stella show-project lfm3-tool tool-calls")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.set_defaults(func=cmd_show_project)

    p = _cmd("delete-checkpoint", "delete one checkpoint forever",
             "examples:\n"
             "  stella delete-checkpoint lfm3-tool tool-calls 50")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument("step", type=int,
                   help="checkpoint step, e.g. 50 for step-50")
    p.add_argument(
        "--yes", action="store_true",
        help="delete without asking first (for scripts).",
    )
    p.set_defaults(func=cmd_delete_checkpoint)

    p = _cmd("prune-checkpoints",
             "delete all but the newest checkpoints",
             "examples:\n"
             "  stella prune-checkpoints lfm3-tool tool-calls\n"
             "  stella prune-checkpoints lfm3-tool tool-calls "
             "--keep 5")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument(
        "--keep", type=int, default=3,
        help="how many of the newest checkpoints to keep (default 3)",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="prune without asking first (for scripts).",
    )
    p.set_defaults(func=cmd_prune_checkpoints)

    p = _cmd("clone-project", "copy a project under a new name",
             "examples:\n"
             "  stella clone-project lfm3-tool tool-calls "
             "tool-calls-2")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument("new_name", metavar="new-name",
                   help="name for the copy, e.g. tool-calls-2")
    p.set_defaults(func=cmd_clone_project)

    p = _cmd(
        "train", "LoRA-tune a project on CPU",
        "examples:\n"
        "  stella train lfm3-tool tool-calls\n"
        "  stella train lfm3-tool tool-calls --resume",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("--steps", type=_positive_int, default=None,
                   help="cap the run at N optimizer steps (proof run)")
    p.add_argument("--dry-run", action="store_true",
                   help="estimate only: show RAM fit, step count, "
                   "disk needed, and a rough time, without loading "
                   "the model or training anything")
    p.add_argument("--resume", action="store_true",
                   help="continue from the latest checkpoint")
    p.add_argument("--from-checkpoint", type=int, default=None,
                   help="resume from checkpoints/step-N instead of "
                   "the latest one (implies --resume)")
    p.add_argument("--force", action="store_true",
                   help="re-train a project that already finished "
                   "training (replaces the adapter)")
    p.add_argument("--dataset", default=None,
                   help="dataset file (overrides the project's dataset)")
    p.add_argument("--base", default=None,
                   help="Hugging Face repo or local folder of the base "
                   "weights (overrides the profile base_ref)")
    p.add_argument("--target-modules", default=None,
                   help="LoRA target layers, comma-separated "
                   "(e.g. q_proj,k_proj). For a model Stella does not "
                   "recognize: name the layers to train by hand. "
                   "Leave unset and Stella finds them itself")
    p.set_defaults(func=cmd_train)

    p = _cmd(
        "export-gguf", "merge + convert + quantize to GGUF",
        "examples:\n"
        "  stella export-gguf lfm3-tool tool-calls ~/exports/gguf",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("dir", help="folder to write the GGUF into")
    p.add_argument("--quant", default="Q4_K_M",
                   help="llama.cpp quant type (default Q4_K_M; common values "
                   "Q4_K_M, Q5_K_M, Q8_0, Q2_K; any other value "
                   "is refused with the full list)")
    p.add_argument("--from-checkpoint", type=int, default=None,
                   help="export from checkpoints/step-N instead of the "
                   "final adapter")
    p.add_argument("--from-sleep", type=int, default=None,
                   help="export from a sleep cycle's adapter "
                   "(sleep/cycle-N/adapter) instead of the final "
                   "adapter")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing GGUF at the output path")
    p.add_argument("--create", action="store_true",
                   help="also run `ollama create` with the exported "
                   "name and Modelfile, instead of leaving it to a "
                   "copy-paste (T89). The manual commands are still "
                   "printed.")
    p.add_argument("--yes", action="store_true",
                   help="answer yes to questions (with --create: "
                   "replace an Ollama model with the same name "
                   "without asking first)")
    p.set_defaults(func=cmd_export_gguf)

    p = _cmd("probe", "refusal probe, before vs after tuning",
             "examples:\n"
             "  stella probe lfm3-tool tool-calls\n"
             "  stella probe lfm3-tool tool-calls --informational")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument(
        "--informational", action="store_true",
        help="informational mode: report the before/after counts "
        "and the change with no pass/fail verdict, and exit 0 "
        "regardless. Without it the probe is a gate for a "
        "governing-seat profile (a failed gate exits 3) and "
        "informational for every other profile, the same as the "
        "window.",
    )
    p.add_argument(
        "--gate", action="store_true",
        help="force the gate on a profile that is not bound for a "
        "governing seat: a failed gate exits 3. Without it, a "
        "non-governing profile probes informationally.",
    )
    p.set_defaults(func=cmd_probe)

    p = _cmd(
        "sleep",
        "sleep cycle: consolidate new rows into a new LoRA "
        "adapter, with a replay check against old rows",
        "examples:\n"
        "  stella sleep lfm3-tool tool-calls\n"
        "  stella sleep lfm3-tool tool-calls --dream",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("--dream", action="store_true",
                   help="dream synthetic practice rows from the local "
                   "Ollama model before consolidating")
    p.add_argument("--dream-model", default=None,
                   help="Ollama tag to dream with (default: the "
                   "profile's ollama_tag)")
    p.add_argument("--rows", default=None,
                   help="JSONL file of new rows (default: the project's "
                   "dataset rows not yet slept on)")
    p.add_argument("--threshold", type=float, default=0.10,
                   help="forgetting threshold: a cycle is DEGRADED when "
                   "the old loss rises more than this, relative "
                   "(default 0.10)")
    p.set_defaults(func=cmd_sleep)

    p = _cmd("sleep-status", "per-cycle sleep stats",
             "examples:\n  stella sleep-status lfm3-tool tool-calls")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.set_defaults(func=cmd_sleep_status)

    p = _cmd("sleep-delete", "delete one sleep cycle for good",
             "examples:\n  stella sleep-delete lfm3-tool tool-calls 1")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("cycle", type=int, help="cycle number, e.g. 1")
    p.add_argument(
        "--yes", action="store_true",
        help="delete without asking first (for scripts).",
    )
    p.set_defaults(func=cmd_sleep_delete)

    p = _cmd("sleep-prune", "delete all but the newest sleep cycles",
             "examples:\n  stella sleep-prune lfm3-tool tool-calls\n"
             "  stella sleep-prune lfm3-tool tool-calls --keep 2")
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument(
        "--keep", type=int, default=3,
        help="how many of the newest cycles to keep (default 3); "
        "the rest are deleted for good",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="delete without asking first (for scripts).",
    )
    p.set_defaults(func=cmd_sleep_prune)

    p = _cmd(
        "chat",
        "talk to Stella: the chat sets up and runs training "
        "for you (/quit to exit)",
        "examples:\n"
        "  stella chat\n"
        "  stella chat --model qwen3.5:4b",
    )
    p.add_argument("--model", default="",
                   help="model to chat with (if left out, Stella asks "
                   "which installed model to use; for Groq and Gemini "
                   "the first suggested model is used)")
    p.add_argument("--provider", default="ollama",
                   choices=["ollama", "groq", "gemini", "custom"],
                   help="where the chat model runs: on this PC "
                   "(ollama), or a cloud provider with your key "
                   "(groq, gemini, custom)")
    p.set_defaults(func=cmd_chat)

    p = _cmd(
        "save-key",
        "save a cloud provider key, typed without showing it",
        "examples:\n"
        "  stella save-key groq\n"
        "  stella save-key custom --base-url https://example.com/v1 "
        "--model my-model",
    )
    p.add_argument(
        "provider",
        help="provider to save a key for: groq, gemini, or custom",
    )
    p.add_argument(
        "--base-url", default="",
        help="for custom: the provider's address "
        "(e.g. https://example.com/v1)",
    )
    p.add_argument(
        "--model", default="",
        help="for custom: the model name to chat with",
    )
    p.set_defaults(func=cmd_save_key)

    p = _cmd(
        "list-keys",
        "which providers have a key saved (never the keys)",
        "examples:\n  stella list-keys",
    )
    p.set_defaults(func=cmd_list_keys)

    p = _cmd(
        "remove-key",
        "forget a saved provider key",
        "examples:\n  stella remove-key groq",
    )
    p.add_argument(
        "provider",
        help="provider to forget the key for: groq, gemini, or custom",
    )
    p.set_defaults(func=cmd_remove_key)

    p = _cmd(
        "requant",
        "re-quantize an installed Ollama model to a smaller "
        "quant and register it as a new tag",
        "examples:\n"
        "  stella requant qwen3.5:4b\n"
        "  stella requant qwen3.5:4b --quant Q2_K --as qwen3.5:4b-q2",
    )
    p.add_argument("tag", help="installed Ollama tag, e.g. qwen3.5:4b")
    p.add_argument("--quant", default="Q4_K_M",
                   help="llama.cpp quant type (default Q4_K_M; common values "
                   "Q4_K_M, Q5_K_M, Q8_0, Q2_K; any other value "
                   "is refused with the full list)")
    p.add_argument("--as", dest="as_tag", default=None,
                   help="name for the smaller model "
                   "(default: the old tag plus the quant)")
    p.set_defaults(func=cmd_requant)

    p = _cmd(
        "bridge",
        "find the Hugging Face repo to train from for an Ollama "
        "tag (training needs HF weights, never a GGUF file)",
        "examples:\n"
        "  stella bridge qwen3.5:4b\n"
        "  stella bridge lfm3",
    )
    p.add_argument("tag", help="installed Ollama tag, e.g. qwen3.5:4b")
    p.set_defaults(func=cmd_bridge)

    p = _cmd(
        "pc-info",
        "what this PC can do, and the training settings "
        "Stella picks for it",
        "examples:\n  stella pc-info",
    )
    p.set_defaults(func=cmd_pc_info)

    p = _cmd(
        "doctor",
        "check the install and repair what a move broke",
        "examples:\n"
        "  stella doctor\n"
        "  stella doctor --check",
    )
    p.add_argument(
        "--check", action="store_true",
        help="check only: report what is stale without fixing it.",
    )
    p.set_defaults(func=cmd_doctor)

    p = _cmd(
        "distill",
        "ask a teacher model each prompt in a file and save "
        "the answers as the project's dataset",
        "examples:\n"
        "  stella distill lfm3-tool tool-calls "
        "--teacher qwen3.5:4b --prompts prompts.txt",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("project", help="project name, e.g. tool-calls")
    p.add_argument("--teacher", required=True,
                   help="installed Ollama tag to learn from")
    p.add_argument("--prompts", required=True,
                   help="plain text file, one prompt per line")
    # S3: the default matches distill.DEFAULT_TIMEOUT_SECONDS (a
    # test pins the two together); the distill module is imported
    # lazily by cmd_distill, so the parser carries the number.
    p.add_argument("--timeout", type=_positive_timeout, default=300.0,
                   help="seconds to wait for each answer "
                   "(default 300)")
    p.set_defaults(func=cmd_distill)

    # -- R112: mark-ready, notes, probe-results, howto,
    # debug-report. Prune is deliberately not here: R77 covers
    # it, and it is already done (prune-checkpoints, sleep-prune).
    p = _cmd(
        "mark-ready",
        "mark a project ready to train",
        "examples:\n  stella mark-ready lfm3-tool tool-calls",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.set_defaults(func=cmd_mark_ready)

    p = _cmd(
        "notes",
        "read a project's notes (or write them with --set)",
        "examples:\n"
        "  stella notes lfm3-tool tool-calls\n"
        "  stella notes lfm3-tool tool-calls --set "
        "\"first run looked good\"",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument(
        "--set", dest="set", default=None,
        help="write this text as the project's notes (the old "
        "notes are kept as notes.md.1). Leave it out to read.",
    )
    p.set_defaults(func=cmd_notes)

    p = _cmd(
        "probe-results",
        "show the saved refusal-probe results (does not re-run it)",
        "examples:\n  stella probe-results lfm3-tool tool-calls",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.set_defaults(func=cmd_probe_results)

    p = _cmd(
        "howto",
        "read a How to Use topic (or list the topics)",
        "examples:\n"
        "  stella howto\n"
        "  stella howto Training",
    )
    p.add_argument(
        "topic", nargs="?", default=None,
        help="topic title, e.g. Training (leave it out to list "
        "the topics)",
    )
    p.set_defaults(func=cmd_howto)

    p = _cmd(
        "debug-report",
        "write a debug report file",
        "examples:\n  stella debug-report",
    )
    p.set_defaults(func=cmd_debug_report)
    return parser


def _silence_library_warnings() -> None:
    """Filter the known-noisy library warnings (T110) so stderr
    carries Stella's messages, not the libraries': transformers
    deprecation notices (`torch_dtype`, gradient-checkpointing
    renames), peft's fan_in_fan_out note, and the notice peft
    prints for the metamorph_mode key Stella records in the
    adapter config (T143 — peft ignores the key, the warning is
    noise). Advisory warnings go off at the source
    (TRANSFORMERS_NO_ADVISORY_WARNINGS); tqdm bars go off too
    (TQDM_DISABLE). setdefault: a user-set value wins. Called at
    the top of main(), before any heavy import, so the env vars
    are read while they still take effect. (The train.py:642
    float() fix this task also named already landed: both loss
    accumulations use .detach(), so this task is the filtering
    only.)

    The GUI entry point (gui.main) calls this too, so a probe or
    merge loading an adapter does not print the peft notice into
    the window's stderr either.

    R111(b): the huggingface_hub "unauthenticated requests"
    advisory is silenced here too, but not with filterwarnings.
    Probed in huggingface_hub 2.4.0: the Hub sends the advisory
    as an X-HF-Warning response header, and the library logs it
    with logger.warning on its own root logger (a StreamHandler
    on stderr, level WARNING). No warnings filter can catch a
    logging call, so the logger's level goes to ERROR instead, and
    real hub errors still show.
    """
    import logging
    import os
    import warnings

    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    warnings.filterwarnings(
        "ignore", message=".*torch_dtype.*is deprecated.*"
    )
    warnings.filterwarnings(
        "ignore", message=".*fan_in_fan_out.*"
    )
    warnings.filterwarnings(
        "ignore",
        message=".*Unexpected keyword arguments.*metamorph_mode.*",
    )
    # Library deprecation warnings in general (transformers/peft
    # internals rename things between releases): the user cannot
    # act on them, and a redirected stderr log should not be
    # mostly chatter. Scoped to the two libraries' modules, so
    # Stella's own warnings still show.
    warnings.filterwarnings(
        "ignore", category=FutureWarning, module="transformers.*"
    )
    warnings.filterwarnings(
        "ignore", category=DeprecationWarning, module="transformers.*"
    )
    warnings.filterwarnings(
        "ignore", category=FutureWarning, module="peft.*"
    )
    warnings.filterwarnings(
        "ignore", category=DeprecationWarning, module="peft.*"
    )


def main(argv: list[str] | None = None) -> int:
    _silence_library_warnings()
    parser = build_parser()
    args = parser.parse_args(argv)
    # R27: a crashed run's "training" status is reconciled at
    # start-up, so the CLI never lists a dead run as live either
    # (the window does the same on open). Best effort: a failure
    # here never blocks the command itself.
    if hasattr(args, "func"):
        try:
            from .train import reconcile_stale_training

            reconcile_stale_training(_store())
        except Exception:
            pass
    if not hasattr(args, "func"):
        # T187: bare `stella` prints the command list (the top
        # --help) instead of argparse's "arguments are required"
        # error — a first-time user gets the manual, not an error.
        parser.print_help()
        return 0
    # R52: --json is honoured or refused, never silently ignored.
    # The gate is closed by default: a command prints JSON only
    # when it is in JSON_COMMANDS (or is a train dry run, whose
    # estimate is a report). Anything else is refused here, before
    # it can print a line of plain text with exit 0.
    if _as_json(args):
        command = getattr(args, "command", "")
        dry_run = (
            command == "train" and bool(getattr(args, "dry_run", False))
        )
        if command not in JSON_COMMANDS and not dry_run:
            return _refuse_json(command)
    try:
        return args.func(args)
    except StellaError as exc:
        # R108: a --json failure still prints a JSON error document
        # on stdout (matching verify's ok field shape), so a script
        # reading stdout gets JSON instead of silence — probe
        # --json against a missing adapter used to print nothing.
        # The stderr line and exit 1 stay; only the missing
        # document is added. Probe's gate-fail 3 is untouched: it
        # returns 3 from cmd_probe, not through here.
        if _as_json(args):
            _print_json({"ok": False, "error": str(exc)})
        print(f"stella: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Last-resort net (T5): an unexpected failure is one clean
        # line on stderr, exit 1 — never a raw traceback on the
        # default path. (KeyboardInterrupt/SystemExit still pass
        # through: except Exception does not catch them.)
        # T172 --verbose: print the full traceback behind the
        # catch-all first, for when the clean line is not enough.
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        message = str(exc).strip() or f"unexpected {type(exc).__name__}"
        print(f"stella: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
