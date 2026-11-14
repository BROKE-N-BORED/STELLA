"""STELLA provider chat: an AI chat that sets up and runs training.

The user talks, the chat does the work. The agent loop talks to a
model: on this PC through Ollama, or a cloud provider (Groq,
Gemini, or a custom OpenAI-compatible service) with the user's own
key, see providers.py. The model drives Stella's engine through
tools. Small local models do
not reliably support native tool calling, so the protocol is plain
text the model can actually emit: a fenced ```tool block holding
one JSON object {"tool": name, "args": {...}}. The agent parses it,
runs the tool, feeds the result back, and repeats until the model
answers in plain text.

Every tool wraps an EXISTING engine function (train, probe, gguf,
sleep, provision, model). There is no new training logic here.

The training template (TEMPLATE_STEPS) is the shape every training
platform needs, whatever the model: goal, base model, data,
recipe, train, check, export, test and back up. The agent walks
one step at a time, asks only for what it needs, and fills the rest
with defaults. On "just do it" it runs the whole template.

Qt-free on purpose: the CLI REPL drives the same core as the
window, and tests drive it with scripted replies and no server.
"""

from __future__ import annotations

import json
import re

from .distill import distill_dataset
from .gguf import export_gguf
from .howto import topic_text, topic_titles
from .model import StellaError, Store, slug_from_model
from .ollama import OllamaError, list_models
from .probe import probe_gate, probe_project
from .providers import ProviderError, make_chat_fn
from .provision import (
    format_size,
    hub_available,
    run_download,
    weights_status,
)
from .requant import requant_model
from .sleep import sleep_project, sleep_status
from .train import (
    TrainController,
    list_checkpoints,
    load_dataset,
    resolve_dataset_ref,
    train_project,
    training_deps_missing,
)

# How many tool calls one user message may trigger. A confused model
# that keeps calling tools forever is stopped here, in plain words.
MAX_TOOL_CALLS = 12

# The template: the steps every training run needs, whatever the
# model. Each step is (key, title, what it means in plain words).
TEMPLATE_STEPS: list[tuple[str, str, str]] = [
    ("goal", "Goal", "What should the model learn to do?"),
    ("model", "Base model", "Pick the base model to start from."),
    ("data", "Data", "The examples it learns from, or the sample dataset."),
    (
        "recipe",
        "Recipe",
        "Stella measures this PC and picks the training recipe. "
        "Nothing to set.",
    ),
    ("train", "Train", "Run the training. This takes hours on CPU."),
    ("check", "Check", "Validation loss and the refusal probe."),
    ("export", "Export", "A GGUF file and an Ollama model."),
    ("test", "Test and back up", "Try the tuned model, keep the export safe."),
]

# No settings tool (T16): Stella measures the PC and picks the training
# recipe itself, and nothing in the UI reads or writes the stored
# settings. The model still validates them (SETTING_RULES in model.py),
# for imports and stored projects — the chat just never touches them.

TOOL_BLOCK_RE = re.compile(r"```tool\s*\n?(.*?)\n?```", re.DOTALL)

# One line per tool, for the system prompt. Keep these short: the
# model reads them on every turn, and small models drown in text.
TOOL_HELP = {
    "list_profiles": "list_profiles {}: list the profiles.",
    "create_profile": (
        'create_profile {"model": "LiquidAI/LFM3-1.7B"}: make a profile '
        "from one model. The name comes from the model."
    ),
    "list_projects": (
        'list_projects {"profile": "lfm3-tool"}: list the projects in a '
        "profile. Leave profile out to use the current one."
    ),
    "create_project": (
        'create_project {"profile": "lfm3-tool", "name": "tool-calls"}: '
        "make a project. Leave name out and one is picked for you."
    ),
    "set_project_dataset": (
        'set_project_dataset {"profile": "lfm3-tool", "project": '
        '"tool-calls", "path": "/home/user/data.jsonl"}: set the '
        "dataset file."
    ),
    "use_sample_dataset": (
        'use_sample_dataset {"profile": "lfm3-tool", "project": '
        '"tool-calls"}: use the bundled sample dataset (20 examples).'
    ),
    "start_training": (
        'start_training {"profile": "lfm3-tool", "project": "tool-calls"}: '
        "train the project. Takes hours on CPU."
    ),
    "training_status": (
        'training_status {"profile": "lfm3-tool", "project": "tool-calls"}: '
        "how far training got, and the last loss."
    ),
    "run_probe": (
        'run_probe {"profile": "lfm3-tool", "project": "tool-calls"}: '
        "the refusal probe, before vs after tuning."
    ),
    "export_gguf": (
        'export_gguf {"profile": "lfm3-tool", "project": "tool-calls"}: '
        "make a GGUF file and an Ollama model from the trained project."
    ),
    "list_checkpoints": (
        'list_checkpoints {"profile": "lfm3-tool", "project": "tool-calls"}: '
        "the saved training checkpoints."
    ),
    "run_sleep": (
        'run_sleep {"profile": "lfm3-tool", "project": "tool-calls", '
        '"dream": false}: one sleep cycle on the new rows.'
    ),
    "sleep_status": (
        'sleep_status {"profile": "lfm3-tool", "project": "tool-calls"}: '
        "the sleep cycles so far, and how many rows are still awake."
    ),
    "download_weights": (
        'download_weights {"profile": "lfm3-tool"}: download the base '
        "model weights from Hugging Face."
    ),
    "distill": (
        'distill {"profile": "lfm3-tool", "project": "tool-calls", '
        '"teacher": "qwen3.5:4b", "prompts": "/home/user/prompts.txt"}: '
        "ask a teacher model each prompt in a file and save the "
        "answers as the project's dataset."
    ),
    "requant": (
        'requant {"tag": "qwen3.5:4b", "quant": "Q4_K_M", "new_tag": '
        '"qwen3.5:4b-small"}: make a smaller copy of an installed '
        "model. Leave quant out for Q4_K_M, leave new_tag out and "
        "one is picked for you."
    ),
    "get_help": (
        'get_help {"topic": "Training"}: read one How to Use topic. '
        "Leave topic out to list the topics."
    ),
}

# Plain-words narration for each tool, shown in the chat while the
# tool runs. The user sees what is happening, not tool names.
TOOL_NARRATION = {
    "list_profiles": "Looking at your profiles...",
    "create_profile": "Setting up a profile for that model...",
    "list_projects": "Looking at the projects...",
    "create_project": "Making the project...",
    "set_project_dataset": "Setting the dataset...",
    "use_sample_dataset": "Using the sample dataset...",
    "start_training": "Training started. This takes hours on CPU.",
    "training_status": "Checking how training is going...",
    "run_probe": "Running the refusal probe...",
    "export_gguf": "Making the GGUF file. This takes a few minutes...",
    "list_checkpoints": "Looking at the checkpoints...",
    "run_sleep": "Running a sleep cycle...",
    "sleep_status": "Checking the sleep cycles...",
    "download_weights": "Downloading the model weights...",
    "distill": "Asking the teacher your prompts...",
    "requant": "Making the smaller copy...",
    "get_help": "Looking that up in the guide...",
}


class ToolParseError(Exception):
    """The model emitted a tool block that is not usable JSON."""


def parse_tool_call(text: str) -> tuple[str, str | None, dict | None]:
    """Split a model reply into (plain text, tool name, args).

    The tool call is a fenced ```tool block holding one JSON object
    {"tool": name, "args": {...}}. Text outside the block is
    narration and comes back as the plain text. When there is no
    tool block, the whole reply is plain text. A tool block that is
    not valid JSON, or has no "tool" name, raises ToolParseError.
    """
    match = TOOL_BLOCK_RE.search(text)
    if match is None:
        return text.strip(), None, None
    plain = (text[: match.start()] + text[match.end() :]).strip()
    raw = match.group(1).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolParseError(f"the tool block was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolParseError("the tool block was not a JSON object")
    name = payload.get("tool")
    if not isinstance(name, str) or not name:
        raise ToolParseError("the tool block named no tool")
    args = payload.get("args", {})
    if not isinstance(args, dict):
        raise ToolParseError("the tool block args were not an object")
    return plain, name, args


def _template_text() -> str:
    lines = ["The training template. Walk one step at a time, in order:"]
    for i, (_key, title, meaning) in enumerate(TEMPLATE_STEPS, 1):
        lines.append(f"{i}. {title}. {meaning}")
    return "\n".join(lines)


def build_system_prompt(
    *,
    profile: str | None,
    project: str | None,
    installed_models: list[str],
) -> str:
    """The system prompt: template, tools, protocol, plain words."""
    session = (
        f"Current profile: {profile or 'none'}. "
        f"Current project: {project or 'none'}."
    )
    models = (
        "Installed Ollama models: " + ", ".join(installed_models) + "."
        if installed_models
        else "No installed Ollama models were found."
    )
    tools = "\n".join(f"- {help_text}" for help_text in TOOL_HELP.values())
    return (
        "You are Stella, a friendly helper inside the Stella program. "
        "You set up and run fine-tuning for the user. You talk in "
        "plain words, short sentences, no jargon. You never make up "
        "facts about the user's files or models: use the tools to look.\n\n"
        + _template_text()
        + "\n\n"
        "Rules:\n"
        "- One step at a time. Ask only for what you need, then do it. "
        "Fill everything else with the defaults. Say plainly which "
        "step you are on, like \"Step 3 of 8: Data.\"\n"
        "- If the user says just do it, do the whole thing, or go ahead, "
        "run the whole template end to end with the defaults and the "
        "sample dataset, and say what you did at each step.\n"
        "- Never invent a dataset path, a model name, or a setting. If "
        "you do not know it, ask, or use a tool to look it up.\n"
        "- Training takes hours on this CPU. Say so before you start it.\n"
        "- To use a tool, write a fenced block exactly like this:\n"
        "```tool\n"
        '{"tool": "list_profiles", "args": {}}\n'
        "```\n"
        "One tool per message. Put any plain words OUTSIDE the block. "
        "When the tool result comes back, answer the user in plain "
        "words. Never show the user raw JSON or tool names.\n\n"
        "Tools:\n" + tools + "\n\n" + session + "\n" + models
    )


class ChatAgent:
    """The agent loop: model reply, tool call, tool result, repeat.

    `chat_fn(model, messages) -> str` is the model call: Ollama by
    default, or the provider named by `provider` (Groq, Gemini,
    custom). Tests pass a scripted fake. `on_narration(text)` is
    called with plain-words updates while work runs (the GUI shows
    them in the chat). `on_progress(text)` is called with
    training/sleep progress lines.
    """

    def __init__(
        self,
        store: Store,
        model: str,
        *,
        provider: str = "ollama",
        profile: str | None = None,
        project: str | None = None,
        chat_fn=None,
        on_narration=None,
        on_progress=None,
    ):
        self.store = store
        self.model = model
        self.provider = provider or "ollama"
        self.current_profile = profile
        self.current_project = project
        # A supplied chat_fn (tests, fakes) is kept as-is; otherwise
        # the function comes from the provider, and follows later
        # provider switches. A missing key surfaces as a plain-words
        # ProviderError when the chat runs, never here.
        self._default_chat_fn = chat_fn is None
        self._chat_fn = chat_fn or make_chat_fn(self.provider, store.home)
        self._on_narration = on_narration
        self._on_progress = on_progress
        self._history: list[dict] = []
        self._cancelled = False
        self._controller: TrainController | None = None

    # -- control ----------------------------------------------------
    def set_model(self, model: str) -> None:
        """The user picked a different chat model."""
        self.model = model

    def set_provider(self, provider: str, model: str) -> None:
        """The user picked a different chat provider + model."""
        self.provider = provider or "ollama"
        self.model = model
        if self._default_chat_fn:
            self._chat_fn = make_chat_fn(self.provider, self.store.home)

    def set_callbacks(self, on_narration=None, on_progress=None) -> None:
        """Wire narration/progress callbacks (the GUI worker does
        this each run, so the callbacks reach the live signals)."""
        self._on_narration = on_narration
        self._on_progress = on_progress

    def request_cancel(self) -> None:
        """Stop the current reply (and any training/sleep it started).

        Training stops after the current step and saves a checkpoint,
        the same as the Pause button.
        """
        self._cancelled = True
        if self._controller is not None:
            self._controller.request_stop()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def _narrate(self, text: str) -> None:
        if self._on_narration is not None:
            self._on_narration(text)

    def _progress(self, text: str) -> None:
        if self._on_progress is not None:
            self._on_progress(text)

    def _messages(self) -> list[dict]:
        system = build_system_prompt(
            profile=self.current_profile,
            project=self.current_project,
            installed_models=list_models(),
        )
        return [{"role": "system", "content": system}] + self._history

    # -- the loop ---------------------------------------------------
    def reply(self, user_text: str) -> str:
        """One user message in, one plain-words reply out."""
        self._cancelled = False
        self._history.append({"role": "user", "content": user_text})
        calls = 0
        while calls < MAX_TOOL_CALLS:
            if self._cancelled:
                return "Stopped. Tell me what you want to do next."
            try:
                text = self._chat_fn(self.model, self._messages())
            except (OllamaError, ProviderError) as exc:
                reply = str(exc)
                self._history.append({"role": "assistant", "content": reply})
                return reply
            except Exception as exc:  # noqa: BLE001 - never crash the chat
                reply = f"The chat model hit a problem: {exc}"
                self._history.append({"role": "assistant", "content": reply})
                return reply
            if self._cancelled:
                # Cancel landed while the model call was in flight.
                return "Stopped. Tell me what you want to do next."
            try:
                plain, name, args = parse_tool_call(text)
            except ToolParseError:
                # The model garbled its own tool call. Never crash,
                # never show the user JSON: ask in plain words.
                reply = (
                    "I got mixed up there. Tell me in plain words what "
                    "you want, for example: train LFM3 to write short "
                    "replies, or: what projects do I have?"
                )
                self._history.append({"role": "assistant", "content": reply})
                return reply
            if name is None:
                reply = plain or (
                    "I did not get an answer out of that. Tell me what "
                    "you want to do, and I will do it."
                )
                self._history.append({"role": "assistant", "content": reply})
                return reply
            calls += 1
            if plain:
                self._narrate(plain)
            self._narrate(TOOL_NARRATION.get(name, f"Working on {name}..."))
            result = self.call_tool(name, args or {})
            self._history.append({"role": "assistant", "content": text})
            self._history.append({"role": "tool", "content": result})
            if self._cancelled:
                return "Stopped. Tell me what you want to do next."
        return (
            "I have done a lot of steps in a row, so I am stopping here "
            "rather than running away with your PC. Tell me what to do "
            "next, and I will carry on."
        )

    # -- tool dispatch ----------------------------------------------
    def call_tool(self, name: str, args: dict) -> str:
        """Run one tool by name. Always returns a plain-words string,
        never raises: a tool failure is a message, not a crash."""
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            known = ", ".join(sorted(TOOL_HELP))
            return (
                f"There is no tool called {name!r}. The tools are: {known}."
            )
        try:
            return handler(args)
        except StellaError as exc:
            return f"That did not work: {exc}"
        except Exception as exc:  # noqa: BLE001 - never crash the chat
            return f"That did not work: {exc}"

    # -- session helpers --------------------------------------------
    def _session(self, args: dict) -> tuple[str | None, str | None]:
        """Profile/project from the args, falling back to the current
        session. Returns (profile, project), either may be None."""
        profile = args.get("profile") or self.current_profile
        project = args.get("project") or self.current_project
        return profile, project

    def _need_session(self, args: dict) -> tuple[str, str] | str:
        """The session a project tool needs, or a plain-words ask."""
        profile, project = self._session(args)
        if not profile:
            return "I need to know which profile. Tell me the model, or pick one."
        if not project:
            return (
                f"I need to know which project in {profile!r}. Tell me the "
                "project name, or say make one."
            )
        return profile, project

    def _unique_slug(self, base: str, taken: set[str]) -> str:
        slug = base
        i = 2
        while slug in taken:
            slug = f"{base}-{i}"
            i += 1
        return slug

    # -- tools ------------------------------------------------------
    def _tool_list_profiles(self, args: dict) -> str:
        profiles = self.store.list_profiles()
        if not profiles:
            return "No profiles yet. Tell me a model and I will make one."
        lines = [f"You have {len(profiles)} profile(s):"]
        for p in profiles:
            label = p.get("display_name") or p["name"]
            tag = p.get("ollama_tag") or p.get("base_ref") or "no model set"
            lines.append(f"- {p['name']} ({label}), model: {tag}")
        return "\n".join(lines)

    def _tool_create_profile(self, args: dict) -> str:
        model = (args.get("model") or "").strip()
        if not model:
            return "Tell me which model, for example LiquidAI/LFM3-1.7B."
        installed = list_models()
        if model in installed or "/" not in model:
            tag, ref = model, ""
        else:
            tag, ref = "", model
        taken = {p["name"] for p in self.store.list_profiles()}
        slug = self._unique_slug(slug_from_model(model), taken)
        self.store.create_profile(slug, ollama_tag=tag, base_ref=ref)
        self.current_profile = slug
        self.current_project = None
        return (
            f"Created profile {slug!r} for {model}. "
            "Next step: make a project for it, or say what you want it to learn."
        )

    def _tool_list_projects(self, args: dict) -> str:
        profile = args.get("profile") or self.current_profile
        if not profile:
            return "Tell me which profile to look in."
        projects = self.store.list_projects(profile)
        if not projects:
            return f"No projects in {profile!r} yet."
        lines = [f"Projects in {profile!r}:"]
        for p in projects:
            lines.append(
                f"- {p['name']}, status: {p.get('status', 'draft')}, "
                f"dataset: {p.get('dataset_ref') or 'not set yet'}"
            )
        return "\n".join(lines)

    def _tool_create_project(self, args: dict) -> str:
        profile = args.get("profile") or self.current_profile
        if not profile:
            return "Tell me which profile the project belongs to."
        name = (args.get("name") or "").strip()
        taken = {p["name"] for p in self.store.list_projects(profile)}
        if not name:
            name = self._unique_slug("fine-tune", taken)
        else:
            name = self._unique_slug(slug_from_model(name), taken)
        self.store.create_project(profile, name)
        self.current_profile = profile
        self.current_project = name
        # The backend picked the training recipe for this PC
        # (auto-config); the numbers are never named here (T16).
        return (
            f"Created project {name!r} in profile {profile!r}. Stella "
            "picked the training recipe for this PC. "
            "Next step: the data. Say which dataset file to use, or say "
            "use the sample dataset."
        )

    def _tool_set_project_dataset(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        path = (args.get("path") or "").strip()
        if not path:
            return "Tell me the dataset file to use."
        data_path = resolve_dataset_ref(self.store, profile, project, path)
        _examples, info = load_dataset(data_path)
        self.store.update_project(profile, project, dataset_ref=path)
        return (
            f"Dataset for {project!r} is now {path} "
            f"({info['count']} examples). Ready to train when you are."
        )

    def _tool_use_sample_dataset(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        self.store.update_project(
            profile, project, dataset_ref="sample-tool-calls.jsonl"
        )
        return (
            "Dataset for "
            f"{project!r} is now the sample dataset "
            "(20 small tool-call examples). Ready to train when you are."
        )

    def _tool_start_training(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        missing = training_deps_missing()
        if missing:
            return (
                "Training packages missing: " + ", ".join(missing) + ". "
                "Run this once in the Stella folder: "
                "bash install-training.sh"
            )
        status = weights_status(self.store, profile)
        if status["state"] == "no-repo":
            return (
                f"Profile {profile!r} has no Hugging Face repo set. "
                "Set Base ref to a repo like LiquidAI/LFM3-1.7B first."
            )
        if status["state"] != "ready":
            return (
                "The base weights are not downloaded yet. Say download "
                "the model first, then train."
            )
        controller = TrainController()
        self._controller = controller
        seen = {"steps": 0}

        def on_event(event: dict):
            kind = event.get("type")
            if kind == "started":
                self._progress(
                    f"Training: {event['total_steps']} steps."
                )
            elif kind == "step":
                seen["steps"] = event["step"]
                if event["step"] % 25 == 0:
                    self._progress(
                        f"Step {event['step']}/{event['total_steps']}, "
                        f"loss {event['loss']:.4f}."
                    )
            elif kind == "val":
                self._progress(
                    f"Epoch {event['epoch']} validation loss "
                    f"{event['loss']:.4f}."
                )
            elif kind == "checkpoint":
                self._progress(f"Checkpoint saved: step {event['step']}.")

        try:
            summary = train_project(
                self.store,
                profile,
                project,
                resume=bool(args.get("resume", False)),
                on_event=on_event,
                controller=controller,
            )
        finally:
            self._controller = None
        if summary.get("stopped"):
            return (
                f"Training paused at step {summary['steps']}. "
                "Say resume training to pick it up."
            )
        loss = summary.get("final_loss")
        loss_text = f"{loss:.4f}" if loss is not None else "n/a"
        return (
            f"Training done: {summary['steps']} steps, final loss "
            f"{loss_text}. Next step: check it with the refusal probe, "
            "then export it as GGUF."
        )

    def _tool_training_status(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        proj = self.store.get_project(profile, project)
        status = proj.get("status", "draft")
        checkpoints = list_checkpoints(self.store, profile, project)
        lines = [f"Project {project!r} status: {status}."]
        if checkpoints:
            last = checkpoints[-1]
            loss = last.get("loss")
            lines.append(
                f"{len(checkpoints)} checkpoint(s), latest step "
                f"{last['step']}"
                + (f", loss {loss:.4f}." if loss is not None else ".")
            )
        else:
            lines.append("No checkpoints yet.")
        log_path = (
            self.store.project_dir(profile, project) / "train_log.jsonl"
        )
        if log_path.is_file():
            lines_text = log_path.read_text(encoding="utf-8").splitlines()
            if lines_text:
                try:
                    last = json.loads(lines_text[-1])
                except json.JSONDecodeError:
                    last = {}
                if "loss" in last:
                    lines.append(
                        f"Last step {last.get('step')}, loss "
                        f"{last['loss']:.4f}."
                    )
        return " ".join(lines)

    def _tool_run_probe(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        result = probe_project(self.store, profile, project)
        before = result["before"]
        after = result["after"]
        _passed, verdict = probe_gate(result)
        return (
            f"Refusal probe for {project!r}: {before['refusals']}/"
            f"{before['total']} refusals before tuning, "
            f"{after['refusals']}/{after['total']} after. {verdict}"
        )

    def _tool_export_gguf(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        dest = (args.get("dest") or "").strip()
        if not dest:
            dest = str(
                self.store.home / "exports" / f"{profile}-{project}"
            )
        result = export_gguf(self.store, profile, project, dest)
        return (
            f"GGUF ready: {result['gguf']} "
            f"({result['gguf_bytes']:,} bytes). "
            f"Create the Ollama model with: {result['ollama_create']}"
        )

    def _tool_list_checkpoints(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        checkpoints = list_checkpoints(self.store, profile, project)
        if not checkpoints:
            return f"No checkpoints for {project!r} yet."
        lines = [f"Checkpoints for {project!r}:"]
        for ck in checkpoints:
            loss = ck.get("loss")
            lines.append(
                f"- step {ck['step']}"
                + (f", loss {loss:.4f}" if loss is not None else "")
            )
        return "\n".join(lines)

    def _tool_run_sleep(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        controller = TrainController()
        self._controller = controller

        def on_event(event: dict):
            kind = event.get("type")
            if kind == "started":
                self._progress(
                    f"Sleep cycle {event['cycle']}: "
                    f"{event['new_rows']} new rows."
                )
            elif kind == "dream":
                self._progress(
                    f"Dreamed {event['kept']} practice rows."
                )
            elif kind == "replay_done":
                self._progress(
                    f"Replay check: {event['status']}."
                )

        try:
            report = sleep_project(
                self.store,
                profile,
                project,
                dream=bool(args.get("dream", False)),
                on_event=on_event,
                controller=controller,
            )
        finally:
            self._controller = None
        if report.get("status") == "paused":
            return (
                f"Sleep paused at step {report['steps']}. "
                "Say sleep again to pick it up."
            )
        return (
            f"Sleep cycle {report['cycle']}: {report['status']}. "
            f"{report['real_rows']} new rows, "
            f"{report.get('dreamed_rows', 0)} dreamed, "
            f"{report['steps']} steps."
        )

    def _tool_sleep_status(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        status = sleep_status(self.store, profile, project)
        cycles = status["cycles"]
        if not cycles:
            lines = [f"No sleep cycles yet for {project!r}."]
        else:
            lines = [f"Sleep cycles for {project!r}:"]
            for c in cycles:
                lines.append(
                    f"- cycle {c['cycle']}: {c['status']}, "
                    f"{c['real_rows']} new rows, "
                    f"{c['dreamed_rows']} dreamed, {c['steps']} steps"
                )
        if status["total_rows"] is not None:
            lines.append(
                f"{status['slept_rows']} rows slept on, "
                f"{status['unslept_rows']} of {status['total_rows']} "
                "still awake."
            )
        else:
            lines.append(
                f"{status['slept_rows']} rows slept on "
                "(no dataset set, so unslept rows are unknown)."
            )
        return " ".join(lines)

    def _tool_download_weights(self, args: dict) -> str:
        profile = args.get("profile") or self.current_profile
        if not profile:
            return "Tell me which profile to download the weights for."
        status = weights_status(self.store, profile)
        if status["state"] == "no-repo":
            return (
                f"Profile {profile!r} has no Hugging Face repo set. "
                "Set Base ref to a repo like LiquidAI/LFM3-1.7B first."
            )
        if status["state"] == "ready":
            return (
                f"The weights for {profile!r} are already downloaded "
                f"({format_size(status['size_bytes'])})."
            )
        if not hub_available():
            return (
                "The download tool is not installed. Run this once in "
                "the Stella folder: bash install-training.sh"
            )
        repo = status["repo"]
        last_pct = {"value": -1}

        def _print(line: str, **_kwargs):
            if line.startswith("PROGRESS "):
                try:
                    _tag, down, total = line.split()
                    down, total = int(down), int(total)
                except ValueError:
                    return
                if total > 0:
                    pct = down * 100 // total
                    if pct // 10 != last_pct["value"] // 10:
                        last_pct["value"] = pct
                        self._progress(f"Downloaded {pct}%.")
                return
            if line.startswith("ERROR "):
                self._progress(line[6:].strip())

        code = run_download(repo, _print=_print)
        if code != 0:
            return (
                "The download did not finish. Check the network and "
                "say download again: it picks up where it left off."
            )
        return f"Weights for {profile!r} downloaded and ready."

    def _tool_distill(self, args: dict) -> str:
        session = self._need_session(args)
        if isinstance(session, str):
            return session
        profile, project = session
        teacher = (args.get("teacher") or "").strip()
        if not teacher:
            return "Tell me which teacher model to learn from."
        prompts = (args.get("prompts") or "").strip()
        if not prompts:
            return (
                "Tell me the prompts file: a plain text file with "
                "one prompt per line."
            )

        def on_event(event: dict):
            if self._cancelled:
                # The loop's post-tool check turns this into the
                # plain "Stopped." reply; nothing is half-written,
                # the prompt event fires before the teacher is asked.
                raise StellaError("stopped by the user")
            if event.get("type") == "prompt":
                index = event.get("index", 0)
                total = event.get("total", 0)
                if total and (index == 1 or index % 10 == 0 or index == total):
                    self._progress(f"Prompt {index} of {total}.")

        report = distill_dataset(
            self.store, profile, project, teacher, prompts,
            on_event=on_event,
        )
        parts = [
            f"Asked the teacher {report['asked']} prompt(s) and kept "
            f"{report['rows']} answer(s) as the dataset for {project!r}."
        ]
        if report["skipped_empty"]:
            parts.append(
                f"{report['skipped_empty']} empty answer(s) were skipped."
            )
        if report["skipped_resumed"]:
            parts.append(
                f"{report['skipped_resumed']} prompt(s) were already "
                "answered in an earlier run."
            )
        parts.append("Look at the dataset, then say train to start.")
        return " ".join(parts)

    def _tool_requant(self, args: dict) -> str:
        tag = (args.get("tag") or "").strip()
        if not tag:
            return "Tell me which installed model to make smaller."
        quant = (args.get("quant") or "Q4_K_M").strip()
        new_tag = (args.get("new_tag") or "").strip() or None

        def on_event(event: dict):
            kind = event.get("type")
            if kind == "found":
                self._progress(
                    f"Found {event['source_tag']} "
                    f"({format_size(event['source_bytes'])}). "
                    f"Shrinking to {event['quant']}..."
                )
            elif kind == "quantized":
                self._progress(
                    f"Shrunk: {format_size(event['source_bytes'])} -> "
                    f"{format_size(event['output_bytes'])}."
                )

        report = requant_model(
            tag, quant=quant, new_tag=new_tag, on_event=on_event
        )
        return (
            f"Done. {report['new_tag']} is "
            f"{format_size(report['output_bytes'])} "
            f"(was {format_size(report['source_bytes'])}). "
            f"The original {report['source_tag']} is untouched. "
            f"Run it with: {report['ollama_run']}"
        )

    def _tool_get_help(self, args: dict) -> str:
        topic = (args.get("topic") or "").strip()
        if not topic:
            return (
                "The guide has these topics: "
                + ", ".join(topic_titles())
                + ". Ask for one by name."
            )
        text = topic_text(topic)
        if text is None:
            matches = [
                t for t in topic_titles() if topic.lower() in t.lower()
            ]
            if len(matches) == 1:
                return topic_text(matches[0])
            return (
                f"No topic called {topic!r}. The topics are: "
                + ", ".join(topic_titles())
                + "."
            )
        return text
