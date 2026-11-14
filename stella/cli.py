"""STELLA command line.

    stella profiles                       list profiles (role + base tag)
    stella projects <profile>             list projects in a profile
    stella export <profile> <project> <dir>
                                          export a project package
    stella import <export-dir>            import a package back
    stella create-profile <name> [--tag <ollama-tag>] [--role <role>]
                                          [--display <name>]
                                          [--base <hf-repo>]
                                          create a profile
    stella create-project <profile> <name> [--display <name>]
                                          [--dataset <file>]
                                          create a project in a profile
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
    stella chat [--provider groq|gemini|custom|ollama] [--model <name>]
                                          talk to Stella: the chat sets
                                          up and runs training for you
                                          (/quit to exit). Cloud
                                          providers need a key saved in
                                          Settings under AI providers.
    stella requant <tag>                  re-quantize an installed Ollama
                                          model to a smaller quant (default
                                          Q4_K_M) and register it as a new
                                          tag; the original is untouched
    stella distill <profile> <project> --teacher <tag> --prompts <file>
                                          ask a teacher model each prompt
                                          and save the answers as the
                                          project's dataset
    stella pc-info                        what this PC can do, and the
                                          training settings Stella picks
                                          for it
    stella doctor [--check]               check the install and repair
                                          what a move broke (--check
                                          only reports, without fixing)

Reads STELLA_HOME for the home dir (default ~/.stella).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import export as export_mod
from .autoconfig import auto_settings, format_report
from .model import STELLA_VERSION, StellaError, Store, metamorph_problem


def _store() -> Store:
    return Store()


def cmd_profiles(args) -> int:
    store = _store()
    profiles = store.list_profiles()
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
        name = p.get("name") or p.get("display_name") or "(unnamed profile)"
        if not p.get("name"):
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
    projects = store.list_projects(args.profile)
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
    print(format_report(measurement, settings))
    return 0


def cmd_doctor(args) -> int:
    """Check the install and repair what a move broke (T66)."""
    from . import doctor as doctor_mod

    checks = doctor_mod.run_checks(
        doctor_mod.find_install_dir(), Path.home(), fix=not args.check
    )
    print(doctor_mod.format_report(checks))
    return 1 if any(c.status == doctor_mod.BROKEN for c in checks) else 0


def cmd_export(args) -> int:
    store = _store()
    out = export_mod.export_project(
        store, args.profile, args.project, args.dir,
        bundle_dataset=getattr(args, "bundle_dataset", False),
    )
    print(f"Exported to {out}")
    return 0


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
    print(export_mod.format_preview(summary))
    if getattr(args, "preview", False):
        return 0
    result = export_mod.import_export(
        store, args.dir,
        profile_choice=choice, on_profile_conflict=on_conflict,
        installed_models=models,
    )
    print(f"Imported project {result['project']!r} into profile {result['profile']!r}")
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
    if health["status"] == "ok":
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
        )
        print(format_estimate(estimate))
        return 0
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
    def _sigint(signum, frame):
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
            dataset_path=args.dataset,
            base_ref=args.base,
            force=args.force,
            target_modules=target_modules,
            on_event=on_event,
            controller=controller,
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
    result = export_gguf(
        store,
        args.profile,
        args.project,
        args.dir,
        quant=args.quant,
        from_checkpoint=args.from_checkpoint,
        force=args.force,
        on_warning=print,  # T31: the converter warning, before the merge
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
    result = probe_project(
        store, args.profile, args.project,
        informational=args.informational,
    )
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
    if args.informational:
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
    data = store.create_project(
        args.profile,
        args.name,
        display_name=args.display or "",
        dataset_ref=args.dataset or "",
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
            print(
                "Custom provider needs a model name. Pass --model "
                "<name>, or set one in Settings under AI providers."
            )
            return 1
        if not has_key(store.home, provider):
            print(missing_key_message(provider))
            return 1
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
    agent = ChatAgent(store, model, provider=provider)
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


def cmd_distill(args) -> int:
    from .distill import distill_dataset

    store = _store()

    def on_event(event: dict):
        kind = event.get("type")
        if kind == "prompt":
            print(
                f"prompt {event['index']} of {event['total']}",
                flush=True,
            )

    report = distill_dataset(
        store,
        args.profile,
        args.project,
        args.teacher,
        args.prompts,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stella", description="Stella: fine-tune models on your own PC."
    )
    parser.add_argument("--version", action="version", version=f"stella {STELLA_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def _cmd(name, text, epilog):
        """A subcommand whose help keeps its example lines: the
        default formatter would collapse the epilog into one
        wrapped paragraph (T51). For a user who hand-types from a
        phone screen, --help is the manual — every command shows
        a worked example."""
        return sub.add_parser(
            name, help=text, description=text, epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
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
    p.set_defaults(func=cmd_export)

    p = _cmd("import", "import an export package",
             "examples:\n  stella import ~/exports/lfm3-tool-tool-calls\n"
             "  stella import ~/exports/lfm3-tool-tool-calls "
             "--profile-merge take")
    p.add_argument("dir", help="folder holding the package to import")
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
        "--dataset sample-tool-calls.jsonl",
    )
    p.add_argument("profile", help="profile name, e.g. lfm3-tool")
    p.add_argument("name", help="project name, e.g. tool-calls")
    p.add_argument("--display", default="",
                   help="display name shown in the window (defaults to "
                   "the project name)")
    p.add_argument("--dataset", default="",
                   help="dataset file for this project (.jsonl, "
                   "e.g. sample-tool-calls.jsonl)")
    p.set_defaults(func=cmd_create_project)

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
                   help="llama.cpp quant type (default Q4_K_M)")
    p.add_argument("--from-checkpoint", type=int, default=None,
                   help="export from checkpoints/step-N instead of the "
                   "final adapter")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing GGUF at the output path")
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
        "regardless. Without it the probe is a gate: a failed "
        "gate exits 3.",
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
        "requant",
        "re-quantize an installed Ollama model to a smaller "
        "quant and register it as a new tag",
        "examples:\n"
        "  stella requant qwen3.5:4b\n"
        "  stella requant qwen3.5:4b --quant Q2_K --as qwen3.5:4b-q2",
    )
    p.add_argument("tag", help="installed Ollama tag, e.g. qwen3.5:4b")
    p.add_argument("--quant", default="Q4_K_M",
                   help="llama.cpp quant type (default Q4_K_M)")
    p.add_argument("--as", dest="as_tag", default=None,
                   help="name for the smaller model "
                   "(default: the old tag plus the quant)")
    p.set_defaults(func=cmd_requant)

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
    p.set_defaults(func=cmd_distill)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except StellaError as exc:
        print(f"stella: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Last-resort net (T5): an unexpected failure is one clean
        # line on stderr, exit 1 — never a raw traceback on the
        # default path. (KeyboardInterrupt/SystemExit still pass
        # through: except Exception does not catch them.)
        message = str(exc).strip() or f"unexpected {type(exc).__name__}"
        print(f"stella: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
