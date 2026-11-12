"""STELLA command line.

    stella profiles                       list profiles (role + base tag)
    stella projects <profile>             list projects in a profile
    stella export <profile> <project> <dir>
                                          export a project package
    stella import <export-dir>            import a package back

Reads STELLA_HOME for the home dir (default ~/.stella).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import export as export_mod
from .model import STELLA_VERSION, StellaError, Store


def _store() -> Store:
    return Store()


def cmd_profiles(args) -> int:
    store = _store()
    profiles = store.list_profiles()
    if not profiles:
        print("No profiles yet. Create one in the Stella window,")
        print("or: stella create-profile <name> --tag <ollama-tag> --role <role>")
        return 0
    for p in profiles:
        role = p.get("role") or "-"
        tag = p.get("ollama_tag") or p.get("base_ref") or "-"
        print(f"{p['name']}\trole: {role}\tbase: {tag}")
    return 0


def cmd_projects(args) -> int:
    store = _store()
    projects = store.list_projects(args.profile)
    if not projects:
        print(f"No projects in profile {args.profile!r}.")
        return 0
    for p in projects:
        mode = (p.get("metamorph") or {}).get("mode", "morph")
        print(f"{p['name']}\tstatus: {p.get('status', 'draft')}\tmetamorph: {mode}")
    return 0


def cmd_export(args) -> int:
    store = _store()
    out = export_mod.export_project(store, args.profile, args.project, args.dir)
    print(f"Exported to {out}")
    return 0


def cmd_import(args) -> int:
    store = _store()
    result = export_mod.import_export(store, args.dir)
    print(f"Imported project {result['project']!r} into profile {result['profile']!r}")
    return 0


def cmd_create_profile(args) -> int:
    store = _store()
    data = store.create_profile(
        args.name,
        ollama_tag=args.tag or "",
        role=args.role or "",
        display_name=args.display or "",
    )
    print(f"Created profile {data['name']!r} (role: {data.get('role') or '-'})")
    return 0


def cmd_create_project(args) -> int:
    store = _store()
    data = store.create_project(
        args.profile,
        args.name,
        display_name=args.display or "",
        dataset_ref=args.dataset or "",
        metamorph_mode=args.metamorph,
    )
    print(f"Created project {data['name']!r} in profile {args.profile!r}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stella", description="Stella — fine-tune models on your own PC."
    )
    parser.add_argument("--version", action="version", version=f"stella {STELLA_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profiles", help="list profiles")
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("projects", help="list projects in a profile")
    p.add_argument("profile")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("export", help="export a project package")
    p.add_argument("profile")
    p.add_argument("project")
    p.add_argument("dir")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="import an export package")
    p.add_argument("dir")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("create-profile", help="create a profile")
    p.add_argument("name")
    p.add_argument("--tag", default="")
    p.add_argument("--role", default="")
    p.add_argument("--display", default="")
    p.set_defaults(func=cmd_create_profile)

    p = sub.add_parser("create-project", help="create a project in a profile")
    p.add_argument("profile")
    p.add_argument("name")
    p.add_argument("--display", default="")
    p.add_argument("--dataset", default="")
    p.add_argument("--metamorph", default="morph",
                   choices=["morph", "compress", "both"])
    p.set_defaults(func=cmd_create_project)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StellaError as exc:
        print(f"stella: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
