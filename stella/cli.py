"""STELLA command line.

    stella profiles                       list profiles (role + base tag)
    stella projects <profile>             list projects in a profile
    stella export <profile> <project> <dir>
                                          export a project package
    stella import <export-dir>            import a package back
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
    stella chat [--model <ollama-tag>]    talk to Stella: the chat sets
                                          up and runs training for you
                                          (/quit to exit)

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
        base_ref=args.base or "",
    )
    print(f"Created profile {data['name']!r} (role: {data.get('role') or '-'})")
    return 0


def cmd_train(args) -> int:
    import signal

    from .train import TrainController, train_project

    store = _store()
    controller = TrainController()
    events = {"last": 0}

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "started":
            print(
                f"Training: {event['total_steps']} steps, "
                f"LoRA rank {event['rank']} (CPU, batch 1. This is slow, "
                "checkpoints save as it goes)"
            )
        elif kind == "step":
            events["last"] = event["step"]
            print(
                f"step {event['step']}/{event['total_steps']} "
                f"epoch {event['epoch']} loss {event['loss']:.4f} "
                f"lr {event['lr']:.2e}",
                flush=True,
            )
        elif kind == "checkpoint":
            print(f"checkpoint saved: step {event['step']}", flush=True)
        elif kind == "val":
            print(f"epoch {event['epoch']} validation loss {event['loss']:.4f}")
        elif kind == "paused":
            print(f"Paused at step {event['step']}. Resume with --resume.")
        elif kind == "done":
            print(f"Done. Adapter saved to {event['adapter']}")

    # Ctrl+C pauses cleanly: the loop checkpoints after the current
    # step and the run resumes with --resume. A hard kill mid-step
    # loses at most the steps since the last checkpoint.
    def _sigint(signum, frame):
        controller.request_stop()
        print("\nPausing after this step (checkpoint will save)...",
              flush=True)

    old_handler = signal.signal(signal.SIGINT, _sigint)
    try:
        summary = train_project(
            store,
            args.profile,
            args.project,
            max_steps=args.steps,
            resume=args.resume,
            dataset_path=args.dataset,
            base_ref=args.base,
            on_event=on_event,
            controller=controller,
        )
    finally:
        signal.signal(signal.SIGINT, old_handler)
    final_loss = summary["final_loss"]
    loss_text = f"{final_loss:.4f}" if final_loss is not None else "n/a"
    print(
        f"Trained {summary['steps']} steps, "
        f"final loss {loss_text}, "
        f"{summary['trainable_params']:,} trainable params, "
        f"about {summary['ram_estimate_gb']} GB RAM used."
    )
    return 0


def cmd_export_gguf(args) -> int:
    from .gguf import export_gguf

    store = _store()
    result = export_gguf(
        store,
        args.profile,
        args.project,
        args.dir,
        quant=args.quant,
        from_checkpoint=args.from_checkpoint,
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
    return 0


def cmd_probe(args) -> int:
    from .probe import probe_gate, probe_project

    store = _store()
    result = probe_project(store, args.profile, args.project)
    before = result["before"]
    after = result["after"]
    print(
        f"Before tuning: {before['refusals']}/{before['total']} refusals "
        f"({before['rate']:.0%})"
    )
    print(
        f"After tuning:  {after['refusals']}/{after['total']} refusals "
        f"({after['rate']:.0%})"
    )
    passed, message = probe_gate(result)
    print(message)
    return 0 if passed else 1


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


def _fmt_loss(value) -> str:
    return f"{value:.4f}" if value is not None else "n/a"


def cmd_sleep(args) -> int:
    import signal

    from .sleep import sleep_project
    from .train import TrainController

    store = _store()
    controller = TrainController()

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "started":
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
            print(
                f"step {event['step']}/{event['total_steps']} "
                f"epoch {event['epoch']} loss {event['loss']:.4f} "
                f"lr {event['lr']:.2e}",
                flush=True,
            )
        elif kind == "checkpoint":
            print(f"checkpoint saved: step {event['step']}", flush=True)
        elif kind == "val":
            print(f"epoch {event['epoch']} validation loss {event['loss']:.4f}")
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
    def _sigint(signum, frame):
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
                f"{c['steps']} steps, old-loss delta {delta_text}"
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


def cmd_chat(args) -> int:
    """Talk to Stella: the same agent core as the Chat window, as a
    small read-a-line loop. /quit (or Ctrl+C / Ctrl+D) exits."""
    from .chat_agent import ChatAgent
    from .ollama import list_models

    model = args.model or ""
    if not model:
        models = list_models()
        if not models:
            print(
                "Ollama is not answering, so I cannot see which models "
                "are installed. Start Ollama and try again, or pass "
                "--model <tag>."
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
            print(f"No model called {picked!r}.")
            return 1
        model = picked
    agent = ChatAgent(_store(), model)
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
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stella", description="Stella: fine-tune models on your own PC."
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
    p.add_argument("--base", default="",
                   help="Hugging Face repo or local folder of the base "
                   "weights (for training, e.g. LiquidAI/LFM3-1.7B)")
    p.set_defaults(func=cmd_create_profile)

    p = sub.add_parser("create-project", help="create a project in a profile")
    p.add_argument("profile")
    p.add_argument("name")
    p.add_argument("--display", default="")
    p.add_argument("--dataset", default="")
    p.add_argument("--metamorph", default="morph",
                   choices=["morph", "compress", "both"])
    p.set_defaults(func=cmd_create_project)

    p = sub.add_parser("train", help="LoRA-tune a project on CPU")
    p.add_argument("profile")
    p.add_argument("project")
    p.add_argument("--steps", type=int, default=None,
                   help="cap the run at N optimizer steps (proof run)")
    p.add_argument("--resume", action="store_true",
                   help="continue from the latest checkpoint")
    p.add_argument("--dataset", default=None,
                   help="dataset file (overrides the project's dataset)")
    p.add_argument("--base", default=None,
                   help="Hugging Face repo or local folder of the base "
                   "weights (overrides the profile base_ref)")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("export-gguf", help="merge + convert + quantize to GGUF")
    p.add_argument("profile")
    p.add_argument("project")
    p.add_argument("dir")
    p.add_argument("--quant", default="Q4_K_M",
                   help="llama.cpp quant type (default Q4_K_M)")
    p.add_argument("--from-checkpoint", type=int, default=None,
                   help="export from checkpoints/step-N instead of the "
                   "final adapter")
    p.set_defaults(func=cmd_export_gguf)

    p = sub.add_parser("probe", help="refusal probe, before vs after tuning")
    p.add_argument("profile")
    p.add_argument("project")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser(
        "sleep",
        help="sleep cycle: consolidate new rows into a new LoRA "
        "adapter, with a replay check against old rows",
    )
    p.add_argument("profile")
    p.add_argument("project")
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

    p = sub.add_parser("sleep-status", help="per-cycle sleep stats")
    p.add_argument("profile")
    p.add_argument("project")
    p.set_defaults(func=cmd_sleep_status)

    p = sub.add_parser(
        "chat",
        help="talk to Stella: the chat sets up and runs training "
        "for you (/quit to exit)",
    )
    p.add_argument("--model", default="",
                   help="Ollama tag to chat with (if left out, Stella "
                   "asks which installed model to use)")
    p.set_defaults(func=cmd_chat)
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
