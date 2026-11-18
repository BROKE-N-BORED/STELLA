"""Chat agent tests: the tool protocol, the template walk, and every
tool against a temp Store. No real Ollama server, no real training,
no real downloads: the chat function is scripted and the heavy
engine calls are monkeypatched."""
import json

import pytest

import stella.chat_agent as chat_mod
from stella.chat_agent import (
    MAX_TOOL_CALLS,
    TEMPLATE_STEPS,
    ChatAgent,
    ToolParseError,
    build_system_prompt,
    parse_tool_call,
)
from stella.ollama import OllamaError


def tool_block(name, args=None):
    return (
        "```tool\n"
        + json.dumps({"tool": name, "args": args or {}})
        + "\n```"
    )


class ScriptedChat:
    """A fake Ollama chat: returns the scripted replies in order,
    then a plain fallback. Records every messages list it was given."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.fallback = "Done. Anything else?"

    def __call__(self, model, messages):
        self.calls.append(messages)
        if self.replies:
            return self.replies.pop(0)
        return self.fallback


@pytest.fixture()
def fake_models(monkeypatch):
    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:2b"]
    )


@pytest.fixture()
def agent(store, fake_models):
    return ChatAgent(store, "lfm3:1.7b")


# -- parsing --------------------------------------------------------


def test_parse_plain_text():
    plain, name, args = parse_tool_call("Hello there.")
    assert plain == "Hello there."
    assert name is None
    assert args is None


def test_parse_tool_block_with_narration():
    text = "Setting it up.\n" + tool_block(
        "create_profile", {"model": "LiquidAI/LFM3-1.7B"}
    )
    plain, name, args = parse_tool_call(text)
    assert plain == "Setting it up."
    assert name == "create_profile"
    assert args == {"model": "LiquidAI/LFM3-1.7B"}


def test_parse_tool_block_without_fence_is_plain_text():
    plain, name, _args = parse_tool_call('{"tool": "list_profiles"}')
    assert name is None
    assert plain == '{"tool": "list_profiles"}'


def test_parse_malformed_json_raises():
    with pytest.raises(ToolParseError):
        parse_tool_call("```tool\n{not json\n```")


def test_parse_missing_tool_name_raises():
    with pytest.raises(ToolParseError):
        parse_tool_call("```tool\n{}\n```")


def test_parse_non_object_args_raises():
    with pytest.raises(ToolParseError):
        parse_tool_call(
            '```tool\n{"tool": "list_profiles", "args": []}\n```'
        )


# -- the loop -------------------------------------------------------


def test_plain_reply_passes_through(agent):
    agent._chat_fn = ScriptedChat(["Hello, what shall we train?"])
    assert agent.reply("hi") == "Hello, what shall we train?"


def test_tool_call_executes_and_feeds_back(agent, store):
    scripted = ScriptedChat(
        [
            tool_block("create_profile", {"model": "LiquidAI/LFM3-1.7B"}),
            "Your profile is ready.",
        ]
    )
    agent._chat_fn = scripted
    reply = agent.reply("make a profile for LFM3")
    assert reply == "Your profile is ready."
    assert store.get_profile("lfm3-1-7b")["base_ref"] == "LiquidAI/LFM3-1.7B"
    # The second model call saw the tool result.
    second = scripted.calls[1]
    tool_msgs = [m for m in second if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "Created profile" in tool_msgs[0]["content"]
    assert "lfm3-1-7b" in tool_msgs[0]["content"]


def test_full_template_walk(agent, store, monkeypatch):
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(
        chat_mod,
        "weights_status",
        lambda store, profile: {
            "repo": "LiquidAI/LFM3-1.7B",
            "state": "ready",
            "size_bytes": 100,
            "path": "/tmp/x",
        },
    )

    def fake_train(store, profile, project, **kwargs):
        return {"steps": 9, "final_loss": 2.5, "stopped": False}

    monkeypatch.setattr(chat_mod, "train_project", fake_train)
    scripted = ScriptedChat(
        [
            "Step 1 of 8: Goal. Training LFM3 on tool calls.\n"
            + tool_block("create_profile", {"model": "LiquidAI/LFM3-1.7B"}),
            tool_block("create_project", {"name": "tool-calls"}),
            tool_block("use_sample_dataset", {}),
            tool_block("start_training", {}),
            "All done. Training finished with final loss 2.5000.",
        ]
    )
    agent._chat_fn = scripted
    # T76: "just do it" shows the plan first and waits — nothing
    # runs until the user says go ahead.
    plan = agent.reply("just do it: train LFM3 on tool calls")
    assert "I will:" in plan
    assert agent.pending_plan is not None
    assert scripted.calls == []  # no model call, no tools ran
    reply = agent.reply("go ahead")
    assert "All done" in reply
    proj = store.get_project("lfm3-1-7b", "tool-calls")
    assert proj["dataset_ref"] == "sample-tool-calls.jsonl"
    # No settings step in the script (T16): the project keeps the
    # auto recipe Stella picked for this PC.
    assert proj["settings_source"] == "auto"
    assert agent.current_profile == "lfm3-1-7b"
    assert agent.current_project == "tool-calls"


def test_malformed_tool_json_asks_plainly(agent):
    agent._chat_fn = ScriptedChat(["```tool\n{broken\n```"])
    reply = agent.reply("train something")
    assert "mixed up" in reply
    assert "plain words" in reply


def test_missing_tool_name_asks_plainly(agent):
    agent._chat_fn = ScriptedChat(["```tool\n{}\n```"])
    reply = agent.reply("train something")
    assert "mixed up" in reply


def test_unknown_tool_reported_then_loop_continues(agent):
    scripted = ScriptedChat(
        [tool_block("delete_everything", {}), "Sorry, I cannot do that."]
    )
    agent._chat_fn = scripted
    reply = agent.reply("delete everything")
    assert reply == "Sorry, I cannot do that."
    tool_msgs = [
        m for m in scripted.calls[1] if m["role"] == "tool"
    ]
    assert "no tool called" in tool_msgs[0]["content"]


def test_twelve_call_cap(agent):
    calls = {"n": 0}

    def always_tool(model, messages):
        calls["n"] += 1
        return tool_block("list_profiles", {})

    agent._chat_fn = always_tool
    reply = agent.reply("go")
    assert calls["n"] == MAX_TOOL_CALLS
    assert "stopping here" in reply
    # R99: the cap-hit reply is recorded in the history like any
    # other reply — the record has no hole where the agent stopped.
    assert agent._history[-1] == {"role": "assistant", "content": reply}


def test_ollama_error_is_plain_words(agent):
    def failing(model, messages):
        raise OllamaError("Ollama is not answering.")

    agent._chat_fn = failing
    assert agent.reply("hi") == "Ollama is not answering."


def test_cancel_stops_the_loop(agent):
    def cancelling(model, messages):
        agent.request_cancel()
        return "still thinking"

    agent._chat_fn = cancelling
    assert agent.reply("hi").startswith("Stopped.")


def test_empty_plain_reply_gets_a_fallback(agent):
    agent._chat_fn = ScriptedChat(["   "])
    reply = agent.reply("hi")
    assert "Tell me what you want to do" in reply


# -- template + system prompt ---------------------------------------


def test_template_has_eight_steps_in_order():
    titles = [title for _key, title, _meaning in TEMPLATE_STEPS]
    assert titles == [
        "Goal",
        "Base model",
        "Data",
        "Recipe",  # T16: step 4 no longer names settings.
        "Train",
        "Check",
        "Export",
        "Test and back up",
    ]


def test_template_step_four_names_no_settings():
    """T16: the recipe step tells the user there is nothing to set,
    and names no setting."""
    _key, title, meaning = TEMPLATE_STEPS[3]
    assert title == "Recipe"
    assert "Nothing to set" in meaning
    for word in ("rank", "learning rate", "epochs", "batch size", "seq len"):
        assert word not in meaning.lower(), word


def test_system_prompt_names_template_tools_and_session():
    prompt = build_system_prompt(
        profile="lfm3-tool",
        project="tool-calls",
        installed_models=["lfm3:1.7b"],
    )
    assert "1. Goal" in prompt
    assert "8. Test and back up" in prompt
    assert "create_profile" in prompt
    assert "start_training" in prompt
    assert "Current profile: lfm3-tool" in prompt
    assert "Current project: tool-calls" in prompt
    assert "lfm3:1.7b" in prompt
    assert "just do it" in prompt
    assert "—" not in prompt


# -- tools against a real temp Store --------------------------------


def test_create_profile_tool_ollama_tag(agent, store):
    result = agent.call_tool("create_profile", {"model": "lfm3:1.7b"})
    assert "Created profile 'lfm3-1-7b'" in result
    data = store.get_profile("lfm3-1-7b")
    assert data["ollama_tag"] == "lfm3:1.7b"
    assert agent.current_profile == "lfm3-1-7b"


def test_create_profile_tool_name_collision_gets_suffix(agent, store):
    agent.call_tool("create_profile", {"model": "lfm3:1.7b"})
    result = agent.call_tool("create_profile", {"model": "lfm3:1.7b"})
    assert "lfm3-1-7b-2" in result


def test_create_profile_tool_needs_a_model(agent):
    result = agent.call_tool("create_profile", {})
    assert "Tell me which model" in result


def test_list_profiles_tool_empty_and_full(agent, store):
    assert "No profiles yet" in agent.call_tool("list_profiles", {})
    agent.call_tool("create_profile", {"model": "lfm3:1.7b"})
    result = agent.call_tool("list_profiles", {})
    assert "lfm3-1-7b" in result


def test_create_project_tool_and_session(agent, store):
    agent.call_tool("create_profile", {"model": "lfm3:1.7b"})
    result = agent.call_tool("create_project", {"name": "tool-calls"})
    assert "Created project 'tool-calls'" in result
    assert store.get_project("lfm3-1-7b", "tool-calls")["name"] == "tool-calls"
    assert agent.current_project == "tool-calls"


def test_create_project_tool_auto_name(agent, store):
    agent.call_tool("create_profile", {"model": "lfm3:1.7b"})
    result = agent.call_tool("create_project", {})
    assert "fine-tune" in result
    assert store.get_project("lfm3-1-7b", "fine-tune") is not None


def test_create_project_tool_needs_a_profile(agent):
    assert "which profile" in agent.call_tool("create_project", {})


def test_list_projects_tool(agent, store, seeded):
    result = agent.call_tool(
        "list_projects", {"profile": "lfm3-tool"}
    )
    assert "tool-calls" in result
    assert "draft" in result


def test_no_settings_tool(agent):
    # T16: the chat has no way to read or write training settings —
    # Stella picks the recipe for this PC, and the user never touches
    # it. A model asking for the old tool gets the unknown-tool reply,
    # and the system prompt never names it.
    result = agent.call_tool(
        "set_project_settings",
        {
            "profile": "lfm3-tool",
            "project": "tool-calls",
            "settings": {"rank": 4},
        },
    )
    assert "no tool called 'set_project_settings'" in result
    assert "set_project_settings" not in build_system_prompt(
        profile="lfm3-tool", project="tool-calls", installed_models=[]
    )


def test_set_dataset_tool_with_real_file(agent, store, seeded, tmp_path):
    data = tmp_path / "data.jsonl"
    data.write_text(
        '{"prompt": "a", "completion": "b"}\n'
        '{"prompt": "c", "completion": "d"}\n'
    )
    result = agent.call_tool(
        "set_project_dataset",
        {
            "profile": "lfm3-tool",
            "project": "tool-calls",
            "path": str(data),
        },
    )
    assert "2 examples" in result
    assert (
        store.get_project("lfm3-tool", "tool-calls")["dataset_ref"]
        == str(data)
    )


def test_set_dataset_tool_missing_file(agent, store, seeded):
    result = agent.call_tool(
        "set_project_dataset",
        {
            "profile": "lfm3-tool",
            "project": "tool-calls",
            "path": "/no/such/file.jsonl",
        },
    )
    assert "not found" in result


def test_use_sample_dataset_tool(agent, store, seeded):
    result = agent.call_tool(
        "use_sample_dataset", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "sample dataset" in result
    assert (
        store.get_project("lfm3-tool", "tool-calls")["dataset_ref"]
        == "sample-tool-calls.jsonl"
    )


def test_training_status_tool(agent, store, seeded):
    result = agent.call_tool(
        "training_status", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "status: draft" in result
    assert "No checkpoints yet" in result


def test_start_training_missing_deps(agent, store, seeded, monkeypatch):
    monkeypatch.setattr(
        chat_mod, "training_deps_missing", lambda: ["torch", "peft"]
    )
    result = agent.call_tool(
        "start_training", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "install-training.sh" in result


def test_start_training_missing_weights(agent, store, seeded, monkeypatch):
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(
        chat_mod,
        "weights_status",
        lambda store, profile: {
            "repo": "LiquidAI/LFM3-1.7B",
            "state": "missing",
            "size_bytes": 0,
            "path": None,
        },
    )
    result = agent.call_tool(
        "start_training", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "not downloaded yet" in result


def test_start_training_runs_with_monkeypatched_engine(
    agent, store, seeded, monkeypatch
):
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(
        chat_mod,
        "weights_status",
        lambda store, profile: {
            "repo": "LiquidAI/LFM3-1.7B",
            "state": "ready",
            "size_bytes": 100,
            "path": "/tmp/x",
        },
    )

    def fake_train(store, profile, project, **kwargs):
        assert kwargs["controller"] is not None
        return {"steps": 12, "final_loss": 1.2345, "stopped": False}

    monkeypatch.setattr(chat_mod, "train_project", fake_train)
    result = agent.call_tool(
        "start_training", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "Training done: 12 steps, final loss 1.2345" in result


def test_start_training_paused_report(agent, store, seeded, monkeypatch):
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    monkeypatch.setattr(
        chat_mod,
        "weights_status",
        lambda store, profile: {
            "repo": "x",
            "state": "ready",
            "size_bytes": 1,
            "path": "/tmp/x",
        },
    )
    monkeypatch.setattr(
        chat_mod,
        "train_project",
        lambda *a, **k: {"steps": 5, "final_loss": 3.0, "stopped": True},
    )
    result = agent.call_tool(
        "start_training", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "paused at step 5" in result


def test_run_probe_tool(agent, store, seeded, monkeypatch):
    def fake_probe(store, profile, project):
        # R65: a realistic probe result carries the empty counts
        # — the gate refuses a result that leaves them out.
        return {
            "before": {"total": 12, "refusals": 0, "empty": 0, "rate": 0.0},
            "after": {"total": 12, "refusals": 1, "empty": 0, "rate": 0.083},
            "delta": 0.083,
        }

    monkeypatch.setattr(chat_mod, "probe_project", fake_probe)
    result = agent.call_tool(
        "run_probe", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "0/12 refusals before tuning" in result
    assert "1/12 after" in result


def test_export_gguf_tool(agent, store, seeded, monkeypatch):
    def fake_export(store, profile, project, dest, **kwargs):
        return {
            "gguf": "/tmp/x/model.gguf",
            "gguf_bytes": 1234,
            "ollama_create": "ollama create lfm3-tool-tool-calls -f /tmp/x/Modelfile",
        }

    monkeypatch.setattr(chat_mod, "export_gguf", fake_export)
    result = agent.call_tool(
        "export_gguf", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "GGUF ready" in result
    assert "ollama create lfm3-tool-tool-calls" in result


def test_list_checkpoints_tool_empty(agent, store, seeded):
    result = agent.call_tool(
        "list_checkpoints", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "No checkpoints" in result


def test_run_sleep_tool(agent, store, seeded, monkeypatch):
    def fake_sleep(store, profile, project, **kwargs):
        return {
            "cycle": 1,
            "status": "OK",
            "real_rows": 5,
            "dreamed_rows": 0,
            "steps": 9,
        }

    monkeypatch.setattr(chat_mod, "sleep_project", fake_sleep)
    result = agent.call_tool(
        "run_sleep", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "Sleep cycle 1: OK" in result
    assert "5 new rows" in result


def test_sleep_status_tool(agent, store, seeded):
    result = agent.call_tool(
        "sleep_status", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "No sleep cycles yet" in result


def test_download_weights_no_repo(agent, store, seeded):
    result = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "no Hugging Face repo set" in result


def test_download_weights_already_ready(agent, store, seeded, monkeypatch):
    monkeypatch.setattr(
        chat_mod,
        "weights_status",
        lambda store, profile: {
            "repo": "LiquidAI/LFM3-1.7B",
            "state": "ready",
            "size_bytes": 3500000000,
            "path": "/tmp/x",
        },
    )
    result = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "already downloaded" in result


def test_download_weights_runs(monkeypatch, agent, store, seeded):
    monkeypatch.setattr(
        chat_mod,
        "weights_status",
        lambda store, profile: {
            "repo": "LiquidAI/LFM3-1.7B",
            "state": "missing",
            "size_bytes": 0,
            "path": None,
        },
    )
    monkeypatch.setattr(chat_mod, "hub_available", lambda: True)

    def fake_download(repo_id, _print=print):
        _print("PROGRESS 5 10")
        _print("PROGRESS 10 10")
        return 0

    monkeypatch.setattr(chat_mod, "run_download", fake_download)
    progress = []
    agent.set_callbacks(on_progress=progress.append)
    result = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "downloaded and ready" in result
    assert "Downloaded 100%." in progress


def test_get_help_tool(agent):
    assert "hours" in agent.call_tool("get_help", {"topic": "Training"})
    assert "Getting started" in agent.call_tool("get_help", {})
    assert "No topic called" in agent.call_tool(
        "get_help", {"topic": "No such topic"}
    )


def test_tool_without_session_asks(agent):
    result = agent.call_tool("start_training", {})
    assert "which profile" in result


def test_no_em_dash_in_tool_text(agent):
    for name, help_text in chat_mod.TOOL_HELP.items():
        assert "—" not in help_text, name
    for name, narration in chat_mod.TOOL_NARRATION.items():
        assert "—" not in narration, name
    for _key, _title, meaning in TEMPLATE_STEPS:
        assert "—" not in meaning


# -- distill + requant tools (v0.8) -----------------------------------


def test_distill_tool(agent, store, seeded, monkeypatch):
    seen = {}

    def fake_distill(store, profile, project, teacher, prompts, **kwargs):
        seen.update(
            profile=profile, project=project,
            teacher=teacher, prompts=prompts,
        )
        return {
            "teacher": teacher, "prompts": 3, "asked": 3,
            "skipped_empty": 1, "skipped_dup": 0, "skipped_resumed": 0,
            "rows": 2, "dataset": "/tmp/x/distilled.jsonl",
        }

    monkeypatch.setattr(chat_mod, "distill_dataset", fake_distill)
    result = agent.call_tool(
        "distill",
        {"profile": "lfm3-tool", "project": "tool-calls",
         "teacher": "qwen3.5:4b", "prompts": "/tmp/prompts.txt"},
    )
    assert "Asked the teacher 3 prompt(s)" in result
    assert "kept 2 answer(s)" in result
    assert "1 empty answer(s) were skipped" in result
    assert "say train to start" in result
    assert seen["teacher"] == "qwen3.5:4b"
    assert seen["prompts"] == "/tmp/prompts.txt"


def test_distill_tool_needs_teacher_and_prompts(agent, store, seeded):
    result = agent.call_tool(
        "distill", {"profile": "lfm3-tool", "project": "tool-calls"}
    )
    assert "which teacher model" in result
    result = agent.call_tool(
        "distill",
        {"profile": "lfm3-tool", "project": "tool-calls",
         "teacher": "qwen3.5:4b"},
    )
    assert "prompts file" in result


def test_distill_tool_failure_is_plain_words(
    agent, store, seeded, monkeypatch
):
    from stella.model import StellaError

    def fake_distill(*args, **kwargs):
        raise StellaError(
            "Ollama is not running, so the teacher cannot answer."
        )

    monkeypatch.setattr(chat_mod, "distill_dataset", fake_distill)
    result = agent.call_tool(
        "distill",
        {"profile": "lfm3-tool", "project": "tool-calls",
         "teacher": "qwen3.5:4b", "prompts": "/tmp/prompts.txt"},
    )
    assert "That did not work" in result
    assert "Ollama is not running" in result


def test_distill_tool_timeout_reaches_engine(agent, store, seeded,
                                             monkeypatch):
    """S3: an optional timeout in the tool args reaches
    distill_dataset; without one, no timeout is passed and the
    engine keeps its usual default."""
    seen = {}

    def fake_distill(store, profile, project, teacher, prompts, **kwargs):
        seen.update(kwargs)
        return {
            "teacher": teacher, "prompts": 3, "asked": 3,
            "skipped_empty": 0, "skipped_dup": 0, "skipped_resumed": 0,
            "rows": 3, "dataset": "/tmp/x/distilled.jsonl",
        }

    monkeypatch.setattr(chat_mod, "distill_dataset", fake_distill)
    agent.call_tool(
        "distill",
        {"profile": "lfm3-tool", "project": "tool-calls",
         "teacher": "qwen3.5:4b", "prompts": "/tmp/prompts.txt",
         "timeout": 900},
    )
    assert seen["timeout"] == 900.0
    seen.clear()
    agent.call_tool(
        "distill",
        {"profile": "lfm3-tool", "project": "tool-calls",
         "teacher": "qwen3.5:4b", "prompts": "/tmp/prompts.txt"},
    )
    assert "timeout" not in seen


@pytest.mark.parametrize("bad", ["soon", -5, 0, True, None])
def test_distill_tool_bad_timeout_keeps_default(agent, store, seeded,
                                                monkeypatch, bad):
    """S3: a timeout that is not a positive number is ignored, not
    passed on: a bad model value never breaks the run."""
    seen = {}

    def fake_distill(store, profile, project, teacher, prompts, **kwargs):
        seen.update(kwargs)
        return {
            "teacher": teacher, "prompts": 3, "asked": 3,
            "skipped_empty": 0, "skipped_dup": 0, "skipped_resumed": 0,
            "rows": 3, "dataset": "/tmp/x/distilled.jsonl",
        }

    monkeypatch.setattr(chat_mod, "distill_dataset", fake_distill)
    agent.call_tool(
        "distill",
        {"profile": "lfm3-tool", "project": "tool-calls",
         "teacher": "qwen3.5:4b", "prompts": "/tmp/prompts.txt",
         "timeout": bad},
    )
    assert "timeout" not in seen


def test_requant_tool(agent, store, seeded, monkeypatch):
    seen = {}

    def fake_requant(tag, **kwargs):
        seen.update(tag=tag, **kwargs)
        return {
            "source_tag": tag, "source_bytes": 2700000000,
            "source_quant": "Q8_0", "new_tag": "qwen3.5:4b-q4-k-m",
            "quant": "Q4_K_M", "output_bytes": 1800000000,
            "ollama_run": "ollama run qwen3.5:4b-q4-k-m",
        }

    monkeypatch.setattr(chat_mod, "requant_model", fake_requant)
    result = agent.call_tool("requant", {"tag": "qwen3.5:4b"})
    assert "qwen3.5:4b-q4-k-m" in result
    assert "untouched" in result
    assert "ollama run qwen3.5:4b-q4-k-m" in result
    assert seen["quant"] == "Q4_K_M"
    assert seen["new_tag"] is None


def test_requant_tool_passes_quant_and_name(agent, monkeypatch):
    seen = {}

    def fake_requant(tag, **kwargs):
        seen.update(tag=tag, **kwargs)
        return {
            "source_tag": tag, "source_bytes": 2700000000,
            "source_quant": "Q8_0", "new_tag": "small:1b",
            "quant": "Q8_0", "output_bytes": 2600000000,
            "ollama_run": "ollama run small:1b",
        }

    monkeypatch.setattr(chat_mod, "requant_model", fake_requant)
    result = agent.call_tool(
        "requant",
        {"tag": "qwen3.5:4b", "quant": "Q8_0", "new_tag": "small:1b"},
    )
    assert "small:1b" in result
    assert seen["quant"] == "Q8_0"
    assert seen["new_tag"] == "small:1b"


def test_requant_tool_needs_a_tag(agent):
    result = agent.call_tool("requant", {})
    assert "which installed model" in result


def test_requant_tool_failure_is_plain_words(agent, monkeypatch):
    from stella.model import StellaError

    def fake_requant(tag, **kwargs):
        raise StellaError("llama-quantize was not found.")

    monkeypatch.setattr(chat_mod, "requant_model", fake_requant)
    result = agent.call_tool("requant", {"tag": "qwen3.5:4b"})
    assert "That did not work" in result
    assert "llama-quantize was not found" in result


def test_requant_tool_via_chat_loop(agent, store, seeded, monkeypatch):
    def fake_requant(tag, **kwargs):
        return {
            "source_tag": tag, "source_bytes": 2700000000,
            "source_quant": "Q8_0", "new_tag": "qwen3.5:4b-q4-k-m",
            "quant": "Q4_K_M", "output_bytes": 1800000000,
            "ollama_run": "ollama run qwen3.5:4b-q4-k-m",
        }

    monkeypatch.setattr(chat_mod, "requant_model", fake_requant)
    scripted = ScriptedChat(
        [
            tool_block("requant", {"tag": "qwen3.5:4b"}),
            "All done. Your smaller model is ready.",
        ]
    )
    agent._chat_fn = scripted
    reply = agent.reply("make qwen smaller")
    assert reply == "All done. Your smaller model is ready."
    second = scripted.calls[1]
    tool_msgs = [m for m in second if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "qwen3.5:4b-q4-k-m" in tool_msgs[0]["content"]


# -- T76: plan before it runs, replies that stream -------------------


def test_just_do_it_shows_plan_and_waits(agent):
    reply = agent.reply("just do it")
    assert "I will:" in reply
    assert "Say go ahead to run it, or cancel to stop." in reply
    assert agent.pending_plan is not None
    assert len(agent.pending_plan) >= 5
    # Nothing ran: no profile or project was created.
    assert agent.current_profile is None
    assert agent.current_project is None


def test_plan_refusal_clears_plan(agent):
    agent.reply("just do it")
    assert agent.pending_plan is not None
    reply = agent.reply("cancel")
    assert agent.pending_plan is None
    assert "will not" in reply


def test_plan_other_message_drops_plan(agent):
    agent.reply("just do it")
    assert agent.pending_plan is not None
    agent._chat_fn = ScriptedChat(["A profile is one base model."])
    reply = agent.reply("what is a profile?")
    assert agent.pending_plan is None
    assert reply == "A profile is one base model."


def test_plan_approval_runs_the_plan(agent):
    agent.reply("just do it")
    scripted = ScriptedChat(["Done it."])
    agent._chat_fn = scripted
    reply = agent.reply("go ahead")
    assert agent.pending_plan is None
    assert reply == "Done it."
    # The internal "run the plan" message reached the model.
    users = [m for m in scripted.calls[0] if m["role"] == "user"]
    assert any("Run the plan we agreed on" in m["content"] for m in users)


class StreamingChat:
    """A fake stream_fn: emits each scripted reply in small chunks,
    then returns the full text."""

    def __init__(self, texts, chunk=4):
        self.texts = list(texts)
        self.chunk = chunk
        self.calls = []

    def __call__(self, model, messages, on_token=None):
        self.calls.append(messages)
        text = self.texts.pop(0) if self.texts else "Done."
        for i in range(0, len(text), self.chunk):
            if on_token is not None:
                on_token(text[i:i + self.chunk])
        return text


def test_streaming_calls_on_token_and_records_plain(store):
    streamed = []
    stream = StreamingChat(["Hello there, this is a reply."])
    agent = ChatAgent(
        store, "lfm3:1.7b", stream_fn=stream, on_token=streamed.append
    )
    reply = agent.reply("hi")
    assert reply == "Hello there, this is a reply."
    assert "".join(streamed) == "Hello there, this is a reply."
    assert agent.last_streamed_plain == "Hello there, this is a reply."


def test_streaming_never_streams_a_tool_block(store):
    streamed = []
    text = "Setting it up.\n" + tool_block("list_profiles")
    stream = StreamingChat([text, "Here they are."], chunk=3)
    agent = ChatAgent(
        store, "lfm3:1.7b", stream_fn=stream, on_token=streamed.append
    )
    reply = agent.reply("list my profiles")
    assert reply == "Here they are."
    # The user saw the plain words only — never the tool JSON.
    shown = "".join(streamed)
    assert "Setting it up." in shown
    assert "Here they are." in shown
    assert "```tool" not in shown
    assert "list_profiles" not in shown
    # But the tool still ran: the model was called twice.
    assert len(stream.calls) == 2


def test_streamed_narration_is_not_doubled(store):
    narrated = []
    streamed = []
    stream = StreamingChat(["A plain reply."])
    agent = ChatAgent(
        store, "lfm3:1.7b", stream_fn=stream,
        on_token=streamed.append, on_narration=narrated.append,
    )
    reply = agent.reply("hi")
    assert reply == "A plain reply."
    assert "".join(streamed) == "A plain reply."
    # Streamed words are not narrated again: the window shows them
    # once, as they arrive.
    assert narrated == []


# -- v0.26.0: R46–R50 ------------------------------------------------


def json_block(name, args=None):
    """A tool call in a ```json fence (R48): the fence small models
    most commonly produce."""
    return (
        "```json\n"
        + json.dumps({"tool": name, "args": args or {}})
        + "\n```"
    )


def test_parse_two_tool_blocks_returns_both_and_strips_json():
    """R47: a reply with two tool blocks yields both calls, and the
    plain text holds no raw JSON from either."""
    from stella.chat_agent import parse_tool_calls

    text = (
        "Doing both.\n"
        + tool_block("list_profiles")
        + "\n"
        + tool_block("list_projects", {"profile": "lfm3-tool"})
    )
    plain, calls = parse_tool_calls(text)
    assert [name for name, _args in calls] == [
        "list_profiles",
        "list_projects",
    ]
    assert plain == "Doing both."
    assert "{" not in plain
    assert "tool" not in plain


def test_parse_tool_call_strips_the_second_block_too():
    """R47: the single-call wrapper still strips every block, so a
    second block never leaks through this path either."""
    text = tool_block("list_profiles") + "\n" + tool_block("list_projects")
    plain, name, _args = parse_tool_call(text)
    assert name == "list_profiles"
    assert plain == ""
    assert "{" not in plain


def test_two_tool_blocks_both_run(agent, store):
    """R47: one reply, two tool blocks — both calls run."""
    scripted = ScriptedChat(
        [
            tool_block("create_profile", {"model": "LiquidAI/LFM3-1.7B"})
            + "\n"
            + tool_block(
                "create_project",
                {"profile": "lfm3-1-7b", "name": "two-blocks"},
            ),
            "Both done.",
        ]
    )
    agent._chat_fn = scripted
    assert agent.reply("set me up") == "Both done."
    assert store.get_profile("lfm3-1-7b")["base_ref"] == "LiquidAI/LFM3-1.7B"
    assert (
        store.get_project("lfm3-1-7b", "two-blocks")["name"]
        == "two-blocks"
    )
    # Both tool results reached the second model call.
    second = scripted.calls[1]
    assert len([m for m in second if m["role"] == "tool"]) == 2


def test_two_tool_blocks_count_as_two_calls(agent, monkeypatch):
    """R47: each block counts against the cap — with one call left,
    the second block does not run."""
    monkeypatch.setattr(chat_mod, "MAX_TOOL_CALLS", 1)
    narrated = []
    agent._on_narration = narrated.append
    scripted = ScriptedChat(
        [
            tool_block("list_profiles")
            + "\n"
            + tool_block("list_projects"),
        ]
    )
    agent._chat_fn = scripted
    reply = agent.reply("list everything")
    assert "stopping here" in reply
    # Only the first tool's narration ran.
    assert narrated.count("Looking at your profiles...") == 1
    assert "Looking at the projects..." not in narrated


def test_malformed_second_block_gets_plain_words_recovery(agent):
    """R47: a malformed second block gets the same garbled-call
    recovery as the first — never a leak of raw JSON."""
    scripted = ScriptedChat(
        [tool_block("list_profiles") + "\n```tool\n{not json\n```"]
    )
    agent._chat_fn = scripted
    reply = agent.reply("list everything")
    assert "I got mixed up there" in reply
    assert "{" not in reply


def test_parse_json_fenced_tool_call():
    """R48: a ```json block holding a tool object is a tool call."""
    plain, name, args = parse_tool_call(json_block("list_profiles"))
    assert plain == ""
    assert name == "list_profiles"
    assert args == {}


def test_json_fenced_tool_call_runs(agent, store):
    """R48: the ```json-fenced call runs, end to end."""
    scripted = ScriptedChat(
        [
            json_block("create_profile", {"model": "LiquidAI/LFM3-1.7B"}),
            "Your profile is ready.",
        ]
    )
    agent._chat_fn = scripted
    assert agent.reply("make a profile") == "Your profile is ready."
    assert store.get_profile("lfm3-1-7b")["base_ref"] == "LiquidAI/LFM3-1.7B"


def test_parse_unclosed_tool_fence_runs_when_json_complete():
    """R48: an unclosed ```tool fence with complete JSON runs."""
    plain, name, args = parse_tool_call(
        '```tool\n{"tool": "list_profiles", "args": {}}'
    )
    assert plain == ""
    assert name == "list_profiles"
    assert args == {}


def test_parse_unclosed_json_fence_runs_when_json_complete():
    """R48: an unclosed ```json fence with complete JSON runs."""
    plain, name, _args = parse_tool_call(
        '```json\n{"tool": "list_profiles", "args": {}}'
    )
    assert plain == ""
    assert name == "list_profiles"


def test_parse_unclosed_fence_keeps_trailing_words_as_text():
    """R48: words after the JSON in an unclosed block stay in the
    plain text — only the JSON itself is consumed."""
    plain, name, _args = parse_tool_call(
        'Before.\n```tool\n{"tool": "list_profiles", "args": {}} please'
    )
    assert name == "list_profiles"
    assert "Before." in plain
    assert "please" in plain
    assert "{" not in plain


def test_parse_unclosed_truncated_json_raises():
    """R48: an unclosed fence whose JSON is itself incomplete gets
    the garbled-call recovery, not a leak."""
    import pytest as _pytest

    with _pytest.raises(ToolParseError):
        parse_tool_call('```tool\n{"tool": "list_profiles", "args": ')


def test_parse_non_tool_json_block_stays_text():
    """R48: a ```json block without a tool object is ordinary
    text — a JSON example the user asked about must stay text."""
    text = '```json\n{"name": "example", "count": 3}\n```'
    plain, name, _args = parse_tool_call(text)
    assert name is None
    assert plain == text
    plain, name, _args = parse_tool_call('```json\n[1, 2, 3]\n```')
    assert name is None
    assert "[1, 2, 3]" in plain


def test_parse_json_tool_block_with_bad_args_raises():
    """R48: a ```json tool object with non-object args is
    garbled, not text — it was clearly meant as a call."""
    import pytest as _pytest

    with _pytest.raises(ToolParseError):
        parse_tool_call(
            '```json\n{"tool": "list_profiles", "args": []}\n```'
        )


def test_json_fence_is_never_streamed(store):
    """R48: a ```json tool block is held back from the live
    stream like a ```tool block — the user never sees JSON."""
    streamed = []
    stream = StreamingChat(
        ['Hello.\n```json\n{"tool": "list_profiles", "args": {}}\n```'],
        chunk=3,
    )
    agent = ChatAgent(
        store, "lfm3:1.7b", stream_fn=stream, on_token=streamed.append
    )
    agent.reply("hi")
    shown = "".join(streamed)
    assert shown.startswith("Hello.")
    assert "{" not in shown
    assert "list_profiles" not in shown


def test_long_chat_sends_bounded_history(agent):
    """R46: after 15 plain turns (30 history entries), the model
    is sent at most the last 20 — while the full history is
    still kept."""
    from stella.chat_agent import MAX_HISTORY_MESSAGES

    scripted = ScriptedChat([])
    scripted.fallback = "Okay."
    agent._chat_fn = scripted
    for i in range(15):
        agent.reply(f"message {i}")
    assert len(agent._history) == 30
    last = scripted.calls[-1]
    assert len(last) <= 1 + MAX_HISTORY_MESSAGES
    # The sent window starts on a user message (a turn boundary),
    # never mid-turn.
    assert last[1]["role"] == "user"
    # And it is the RECENT history, not the first turns.
    assert "message 14" in last[-1]["content"]


def test_messages_cut_keeps_tool_results_with_their_call(agent):
    """R46: the history cap never orphans a tool result from the
    assistant message that called it — the cut lands on a user
    message."""
    agent._history = []
    for i in range(10):
        agent._history.append({"role": "user", "content": f"ask {i}"})
        agent._history.append(
            {"role": "assistant", "content": f"```tool call {i}"}
        )
        agent._history.append({"role": "tool", "content": f"result {i}"})
    messages = agent._messages()
    sent = messages[1:]
    assert len(sent) <= 20
    assert sent[0]["role"] == "user"
    # Every tool result in the window still has its assistant
    # message before it.
    for i, entry in enumerate(sent):
        if entry["role"] == "tool":
            assert any(
                m["role"] == "assistant" for m in sent[:i]
            )


def test_one_loop_makes_one_model_list_fetch(agent, monkeypatch):
    """R50: a 2-call loop makes exactly one /api/tags fetch — the
    list is fetched once per reply and reused."""
    fetches = []

    def counting():
        fetches.append(1)
        return ["lfm3:1.7b", "qwen3.5:2b"]

    monkeypatch.setattr(chat_mod, "list_models", counting)
    scripted = ScriptedChat(
        [
            tool_block("list_profiles"),
            tool_block("list_projects"),
            "Done.",
        ]
    )
    agent._chat_fn = scripted
    assert agent.reply("list things") == "Done."
    assert len(fetches) == 1
    # The cache does not leak across turns: a second reply fetches
    # again, once.
    assert agent._turn_models is None
    agent.reply("hi again")
    assert len(fetches) == 2


def test_create_profile_tool_uses_the_turn_fetch(agent, monkeypatch):
    """R50: the create_profile tool reads the turn's list too, so
    a loop that creates a profile still makes one fetch."""
    fetches = []

    def counting():
        fetches.append(1)
        return ["lfm3:1.7b"]

    monkeypatch.setattr(chat_mod, "list_models", counting)
    scripted = ScriptedChat(
        [
            tool_block("create_profile", {"model": "LiquidAI/LFM3-1.7B"}),
            "Done.",
        ]
    )
    agent._chat_fn = scripted
    agent.reply("make a profile")
    assert len(fetches) == 1


def test_template_step_from_store_state(store):
    """R49: the step comes from real store state at every stage."""
    from stella.chat_agent import template_step_for

    assert template_step_for(store, None, None) == (1, "goal", "Goal")
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    assert template_step_for(store, "lfm3-tool", None) == (
        2, "model", "Base model",
    )
    store.create_project("lfm3-tool", "tool-calls")
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        3, "data", "Data",
    )
    store.update_project(
        "lfm3-tool", "tool-calls", dataset_ref="data.jsonl"
    )
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        4, "recipe", "Recipe",
    )
    store.update_project("lfm3-tool", "tool-calls", status="training")
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        5, "train", "Train",
    )
    store.update_project("lfm3-tool", "tool-calls", status="paused")
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        5, "train", "Train",
    )
    store.update_project("lfm3-tool", "tool-calls", status="done")
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        6, "check", "Check",
    )
    # A passed probe moves it to Export; a missing probe does not.
    probe_path = store.project_dir("lfm3-tool", "tool-calls") / (
        "probe_results.json"
    )
    probe_path.write_text(
        json.dumps({
            "before": {"rate": 0.1, "total": 10, "empty": 0},
            "after": {"rate": 0.1, "total": 10, "empty": 0},
        }),
        encoding="utf-8",
    )
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        7, "export", "Export",
    )
    store.update_project("lfm3-tool", "tool-calls", status="exported")
    assert template_step_for(store, "lfm3-tool", "tool-calls") == (
        8, "test", "Test and back up",
    )
    # A deleted profile or project falls back honestly, never
    # crashes.
    assert template_step_for(store, "gone", None) == (1, "goal", "Goal")
    assert template_step_for(store, "lfm3-tool", "gone") == (
        2, "model", "Base model",
    )


def test_agent_reports_step_after_creating_profile_and_project(agent, store):
    """R49: scripted model creates profile + project — the agent
    reports step 3 (Data), not step 1, and says so in narration."""
    narrated = []
    agent._on_narration = narrated.append
    scripted = ScriptedChat(
        [
            tool_block("create_profile", {"model": "LiquidAI/LFM3-1.7B"}),
            tool_block(
                "create_project",
                {"profile": "lfm3-1-7b", "name": "tool-calls"},
            ),
            "All set.",
        ]
    )
    agent._chat_fn = scripted
    agent.reply("set me up")
    assert agent.current_template_step() == (3, "data", "Data")
    assert agent.current_step_text() == "Step 3 of 8: Data."
    assert "Step 3 of 8: Data." in narrated
    # The system prompt told the model where it was, per call:
    # step 1 before anything existed, step 2 after the profile.
    assert "currently on step 1 of 8: Goal" in scripted.calls[0][0]["content"]
    assert "currently on step 2 of 8: Base model" in (
        scripted.calls[1][0]["content"]
    )


def test_system_prompt_without_step_has_no_step_line():
    """R49: build_system_prompt without a step reads as before —
    the step line is added, not assumed."""
    prompt = build_system_prompt(
        profile=None, project=None, installed_models=[]
    )
    assert "currently on step" not in prompt
    prompt = build_system_prompt(
        profile="lfm3-tool", project="tool-calls",
        installed_models=["lfm3:1.7b"],
        current_step=(3, "data", "Data"),
    )
    assert "currently on step 3 of 8: Data" in prompt
