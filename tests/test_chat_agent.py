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
            tool_block(
                "set_project_settings", {"settings": {"rank": 8, "epochs": 2}}
            ),
            tool_block("start_training", {}),
            "All done. Training finished with final loss 2.5000.",
        ]
    )
    agent._chat_fn = scripted
    reply = agent.reply("just do it: train LFM3 on tool calls")
    assert "All done" in reply
    proj = store.get_project("lfm3-1-7b", "tool-calls")
    assert proj["dataset_ref"] == "sample-tool-calls.jsonl"
    assert proj["settings"]["rank"] == 8
    assert proj["settings"]["epochs"] == 2
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
        "Settings",
        "Train",
        "Check",
        "Export",
        "Test and back up",
    ]


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


def test_settings_validation(agent, store, seeded):
    base = {"profile": "lfm3-tool", "project": "tool-calls"}
    bad_rank = dict(base, settings={"rank": -5})
    assert "between 1 and 64" in agent.call_tool(
        "set_project_settings", bad_rank
    )
    bad_lr = dict(base, settings={"learning_rate": -0.5})
    assert "between 0.0 and 1.0" in agent.call_tool(
        "set_project_settings", bad_lr
    )
    bad_method = dict(base, settings={"method": "full"})
    assert "does not run on this PC" in agent.call_tool(
        "set_project_settings", bad_method
    )
    unknown = dict(base, settings={"banana": 3})
    assert "no setting called 'banana'" in agent.call_tool(
        "set_project_settings", unknown
    )
    non_int = dict(base, settings={"rank": 2.5})
    assert "whole number" in agent.call_tool(
        "set_project_settings", non_int
    )
    # The bad sets stored nothing.
    assert store.get_project("lfm3-tool", "tool-calls")["settings"]["rank"] == 8
    good = dict(base, settings={"rank": 4, "epochs": 2})
    result = agent.call_tool("set_project_settings", good)
    assert "rank 4" in result
    settings = store.get_project("lfm3-tool", "tool-calls")["settings"]
    assert settings["rank"] == 4
    assert settings["epochs"] == 2


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
        return {
            "before": {"total": 12, "refusals": 0, "rate": 0.0},
            "after": {"total": 12, "refusals": 1, "rate": 0.083},
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
