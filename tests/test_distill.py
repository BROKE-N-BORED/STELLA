"""Distillation tests.

No real Ollama, no real network: the teacher check is faked by
monkeypatching the ollama client, and the teacher's answers come
from an injected _generate function. The one exception is the CLI
teacher-unreachable test, which relies on Ollama being down in the
sandbox (reachable() returns False) — no server is started.
"""
import json

import pytest

from stella.distill import DISTILLED_FILENAME, distill_dataset
from stella.model import StellaError
from test_cli import run_cli

TEACHER = "qwen3.5:4b"


@pytest.fixture()
def teacher_up(monkeypatch):
    """Ollama answers, and the teacher tag is installed."""
    import stella.distill as distill_mod

    monkeypatch.setattr(
        distill_mod.ollama_client, "reachable", lambda url=None: True
    )
    monkeypatch.setattr(
        distill_mod.ollama_client,
        "list_models",
        lambda url=None: [TEACHER, "lfm3:1.7b"],
    )


def make_prompts(tmp_path, prompts):
    path = tmp_path / "prompts.txt"
    path.write_text("\n".join(prompts) + "\n", encoding="utf-8")
    return path


def read_rows(store, profile="lfm3-tool", project="tool-calls"):
    out = store.project_dir(profile, project) / DISTILLED_FILENAME
    return [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def fake_teacher(answers):
    """A _generate that answers from a dict, counting its calls."""
    calls = []

    def _generate(tag, prompt):
        calls.append((tag, prompt))
        return answers.get(prompt, f"answer to {prompt}")

    _generate.calls = calls
    return _generate


def test_distill_happy_path(seeded, teacher_up, tmp_path):
    prompts = make_prompts(
        tmp_path, ["write a haiku", "name a color", "say hello"]
    )
    report = distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        _generate=fake_teacher({}),
    )
    assert report["teacher"] == TEACHER
    assert report["prompts"] == 3
    assert report["asked"] == 3
    assert report["rows"] == 3
    assert report["skipped_empty"] == 0
    assert report["skipped_dup"] == 0
    assert report["skipped_resumed"] == 0
    rows = read_rows(seeded)
    assert [r["prompt"] for r in rows] == [
        "write a haiku", "name a color", "say hello",
    ]
    assert all(r["completion"].startswith("answer to ") for r in rows)
    project = seeded.get_project("lfm3-tool", "tool-calls")
    assert project["dataset_ref"] == DISTILLED_FILENAME


def test_distill_skips_empty_answers(seeded, teacher_up, tmp_path):
    prompts = make_prompts(
        tmp_path, ["one", "two", "three"]
    )
    gen = fake_teacher({"two": "   "})
    report = distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        _generate=gen,
    )
    assert report["asked"] == 3
    assert report["skipped_empty"] == 1
    assert report["rows"] == 2
    rows = read_rows(seeded)
    assert [r["prompt"] for r in rows] == ["one", "three"]


def test_distill_dedupes_repeated_prompts(seeded, teacher_up, tmp_path):
    prompts = make_prompts(
        tmp_path, ["same prompt", "same prompt", "other prompt"]
    )
    gen = fake_teacher({})
    report = distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        _generate=gen,
    )
    assert report["asked"] == 2
    assert report["skipped_dup"] == 1
    assert report["rows"] == 2
    assert len(gen.calls) == 2


def test_distill_resume_skips_answered(seeded, teacher_up, tmp_path):
    prompts = make_prompts(tmp_path, ["first", "second"])
    gen = fake_teacher({})
    first = distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        _generate=gen,
    )
    assert first["rows"] == 2
    # A longer list on the second run: the two answered prompts are
    # skipped, only the new one is asked.
    prompts = make_prompts(tmp_path, ["first", "second", "third"])
    gen2 = fake_teacher({})
    second = distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        _generate=gen2,
    )
    assert second["asked"] == 1
    assert second["skipped_resumed"] == 2
    assert second["rows"] == 3
    assert len(gen2.calls) == 1
    rows = read_rows(seeded)
    assert [r["prompt"] for r in rows] == ["first", "second", "third"]


def test_distill_progress_events(seeded, teacher_up, tmp_path):
    prompts = make_prompts(tmp_path, ["a", "b"])
    events = []
    distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        on_event=events.append,
        _generate=fake_teacher({}),
    )
    kinds = [e["type"] for e in events]
    assert kinds == ["prompt", "prompt", "done"]
    assert events[0]["index"] == 1 and events[0]["total"] == 2
    assert events[1]["index"] == 2 and events[1]["total"] == 2
    assert events[2]["rows"] == 2


def test_distill_teacher_unreachable(seeded, monkeypatch, tmp_path):
    import stella.distill as distill_mod

    monkeypatch.setattr(
        distill_mod.ollama_client, "reachable", lambda url=None: False
    )
    prompts = make_prompts(tmp_path, ["a", "b"])
    with pytest.raises(StellaError, match="Ollama is not running"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
            _generate=fake_teacher({}),
        )


def test_distill_teacher_not_installed(seeded, monkeypatch, tmp_path):
    import stella.distill as distill_mod

    monkeypatch.setattr(
        distill_mod.ollama_client, "reachable", lambda url=None: True
    )
    monkeypatch.setattr(
        distill_mod.ollama_client, "list_models", lambda url=None: []
    )
    prompts = make_prompts(tmp_path, ["a", "b"])
    with pytest.raises(StellaError, match="does not have a model"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
            _generate=fake_teacher({}),
        )


def test_distill_empty_prompts_file(seeded, teacher_up, tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(StellaError, match="is empty"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, path,
            _generate=fake_teacher({}),
        )


def test_distill_missing_prompts_file(seeded, teacher_up, tmp_path):
    with pytest.raises(StellaError, match="No prompts file"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER,
            tmp_path / "no-such-file.txt",
            _generate=fake_teacher({}),
        )


def test_distill_needs_two_good_rows(seeded, teacher_up, tmp_path):
    prompts = make_prompts(tmp_path, ["only one"])
    with pytest.raises(StellaError, match="At least 2 are needed"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
            _generate=fake_teacher({}),
        )


def test_distill_corrupt_output_file_fails_plainly(
    seeded, teacher_up, tmp_path
):
    # A hand-corrupted distilled.jsonl: the final validation names
    # the bad line instead of training on garbage.
    out = (
        seeded.project_dir("lfm3-tool", "tool-calls") / DISTILLED_FILENAME
    )
    out.write_text('{"prompt": "a", "completion": "b"}\nnot json\n',
                   encoding="utf-8")
    prompts = make_prompts(tmp_path, ["a", "c"])
    with pytest.raises(StellaError, match="not valid JSON"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
            _generate=fake_teacher({}),
        )


def test_distill_unknown_profile_or_project(seeded, teacher_up, tmp_path):
    prompts = make_prompts(tmp_path, ["a", "b"])
    with pytest.raises(StellaError):
        distill_dataset(
            seeded, "no-such-profile", "tool-calls", TEACHER, prompts,
            _generate=fake_teacher({}),
        )
    with pytest.raises(StellaError):
        distill_dataset(
            seeded, "lfm3-tool", "no-such-project", TEACHER, prompts,
            _generate=fake_teacher({}),
        )


# -- CLI end to end (real subprocess, no Ollama server) ---------------

def test_cli_distill_missing_prompts_exit_1(home, tmp_path):
    from stella.model import Store

    store = Store(home)
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    store.create_project("lfm3-tool", "tool-calls")
    res = run_cli(
        home, "distill", "lfm3-tool", "tool-calls",
        "--teacher", TEACHER, "--prompts", str(tmp_path / "nope.txt"),
    )
    assert res.returncode == 1
    assert "No prompts file" in res.stderr


def test_cli_distill_teacher_unreachable_exit_1(home, tmp_path, monkeypatch):
    # The subprocess must see Ollama down even when a live Ollama
    # answers on this machine: point it at a dead port, so the
    # test does not depend on the machine's Ollama state.
    monkeypatch.setenv("STELLA_OLLAMA_URL", "http://127.0.0.1:9")
    from stella.model import Store

    store = Store(home)
    store.create_profile("lfm3-tool", ollama_tag="lfm3:1.7b")
    store.create_project("lfm3-tool", "tool-calls")
    prompts = make_prompts(tmp_path, ["a", "b"])
    res = run_cli(
        home, "distill", "lfm3-tool", "tool-calls",
        "--teacher", TEACHER, "--prompts", str(prompts),
    )
    assert res.returncode == 1
    assert "Ollama is not running" in res.stderr


# -- T74: cancel ------------------------------------------------------


def test_distill_cancel_stops_and_keeps_answers(seeded, teacher_up, tmp_path):
    """The job card's Cancel stops distillation; the answers so far
    are saved, and a later run resumes past them."""
    prompts = make_prompts(tmp_path, ["one", "two", "three", "four"])
    gen = fake_teacher({})
    state = {"asked": 0}

    def _generate(tag, prompt):
        state["asked"] += 1
        return gen(tag, prompt)

    def should_stop():
        return state["asked"] >= 2

    with pytest.raises(StellaError, match="Cancelled"):
        distill_dataset(
            seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
            should_stop=should_stop, _generate=_generate,
        )
    assert state["asked"] == 2
    rows = read_rows(seeded)
    assert [r["prompt"] for r in rows] == ["one", "two"]


def test_distill_emits_prompt_events(seeded, teacher_up, tmp_path):
    prompts = make_prompts(tmp_path, ["one", "two", "three"])
    events = []
    distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        on_event=events.append, _generate=fake_teacher({}),
    )
    prompt_events = [e for e in events if e["type"] == "prompt"]
    assert [(e["index"], e["total"]) for e in prompt_events] == [
        (1, 3), (2, 3), (3, 3),
    ]
    assert events[-1]["type"] == "done"
    assert events[-1]["rows"] == 3


# -- S3: the timeout knob + S4: keep the teacher warm -----------------


def test_distill_passes_timeout_to_generate(seeded, teacher_up, tmp_path,
                                            monkeypatch):
    """The timeout reaches ollama.generate: a fake generate records
    the timeout it was called with."""
    import stella.distill as distill_mod

    seen = []

    def fake_generate(model, prompt, url=None, timeout=None, **kwargs):
        seen.append({"timeout": timeout, **kwargs})
        return f"answer to {prompt}"

    monkeypatch.setattr(
        distill_mod.ollama_client, "generate", fake_generate
    )
    prompts = make_prompts(tmp_path, ["a", "b"])
    distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
        timeout=600,
    )
    assert [call["timeout"] for call in seen] == [600, 600]


def test_distill_default_timeout_is_300(seeded, teacher_up, tmp_path,
                                        monkeypatch):
    """No timeout passed: generate gets the 300-second default."""
    import stella.distill as distill_mod
    from stella.distill import DEFAULT_TIMEOUT_SECONDS

    assert DEFAULT_TIMEOUT_SECONDS == 300.0
    seen = []

    def fake_generate(model, prompt, url=None, timeout=None, **kwargs):
        seen.append(timeout)
        return f"answer to {prompt}"

    monkeypatch.setattr(
        distill_mod.ollama_client, "generate", fake_generate
    )
    prompts = make_prompts(tmp_path, ["a", "b"])
    distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
    )
    assert seen == [300.0, 300.0]


def test_distill_keeps_teacher_warm(seeded, teacher_up, tmp_path,
                                    monkeypatch):
    """S4: every prompt's call carries the run's keep-alive, so
    the teacher stays loaded across prompts."""
    import stella.distill as distill_mod
    from stella.distill import DISTILL_KEEP_ALIVE

    assert DISTILL_KEEP_ALIVE == "30m"
    # Never forever: the model must unload after the run on an
    # 8 GB PC.
    assert DISTILL_KEEP_ALIVE != "-1"
    seen = []

    def fake_generate(model, prompt, url=None, timeout=None, **kwargs):
        seen.append(kwargs.get("keep_alive"))
        return f"answer to {prompt}"

    monkeypatch.setattr(
        distill_mod.ollama_client, "generate", fake_generate
    )
    prompts = make_prompts(tmp_path, ["a", "b"])
    distill_dataset(
        seeded, "lfm3-tool", "tool-calls", TEACHER, prompts,
    )
    assert seen == ["30m", "30m"]


# -- S3: the CLI --timeout flag reaches the engine --------------------


def _fake_cli_distill(seen):
    """A distill_dataset stand-in for in-process CLI tests: records
    its keyword arguments and reports a finished run."""

    def fake_distill(store, profile, project, teacher, prompts, **kwargs):
        seen.update(kwargs)
        on_event = kwargs.get("on_event")
        if on_event is not None:
            on_event(
                {"type": "prompt", "index": 1, "total": 2, "prompt": "a"}
            )
            on_event(
                {"type": "prompt", "index": 2, "total": 2, "prompt": "b"}
            )
        return {
            "teacher": teacher, "prompts": 2, "asked": 2,
            "skipped_empty": 0, "skipped_dup": 0, "skipped_resumed": 0,
            "rows": 2, "dataset": "/tmp/x/distilled.jsonl",
        }

    return fake_distill


def test_cli_distill_timeout_reaches_engine(home, monkeypatch, capsys):
    import stella.cli as cli_mod
    import stella.distill as distill_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}
    monkeypatch.setattr(
        distill_mod, "distill_dataset", _fake_cli_distill(seen)
    )
    run_cli(home, "create-profile", "lfm3-tool", "--tag", "lfm3:1.7b")
    run_cli(home, "create-project", "lfm3-tool", "tool-calls")
    code = cli_mod.main([
        "distill", "lfm3-tool", "tool-calls",
        "--teacher", TEACHER, "--prompts", "/tmp/prompts.txt",
        "--timeout", "600",
    ])
    assert code == 0
    assert seen["timeout"] == 600.0


def test_cli_distill_timeout_defaults_to_300(home, monkeypatch, capsys):
    import stella.cli as cli_mod
    import stella.distill as distill_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    seen = {}
    monkeypatch.setattr(
        distill_mod, "distill_dataset", _fake_cli_distill(seen)
    )
    run_cli(home, "create-profile", "lfm3-tool", "--tag", "lfm3:1.7b")
    run_cli(home, "create-project", "lfm3-tool", "tool-calls")
    code = cli_mod.main([
        "distill", "lfm3-tool", "tool-calls",
        "--teacher", TEACHER, "--prompts", "/tmp/prompts.txt",
    ])
    assert code == 0
    assert seen["timeout"] == 300.0


# -- S21: the CLI distill ETA -----------------------------------------


def test_cli_distill_shows_eta_after_two_prompts(home, monkeypatch, capsys):
    """The prompt lines gain a time-left tail once two prompts
    have been answered (a rate from one sample would be bogus).
    The clock is faked: 30 seconds per prompt, 10 prompts."""
    import time

    import stella.cli as cli_mod
    import stella.distill as distill_mod

    monkeypatch.setenv("STELLA_HOME", str(home))
    now = [1000.0]

    def fake_distill(store, profile, project, teacher, prompts, **kwargs):
        on_event = kwargs["on_event"]
        for index in range(1, 6):
            now[0] += 30.0
            on_event({
                "type": "prompt", "index": index, "total": 10,
                "prompt": f"prompt {index}",
            })
        return {
            "teacher": teacher, "prompts": 10, "asked": 5,
            "skipped_empty": 0, "skipped_dup": 0, "skipped_resumed": 0,
            "rows": 5, "dataset": "/tmp/x/distilled.jsonl",
        }

    monkeypatch.setattr(distill_mod, "distill_dataset", fake_distill)
    run_cli(home, "create-profile", "lfm3-tool", "--tag", "lfm3:1.7b")
    run_cli(home, "create-project", "lfm3-tool", "tool-calls")
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    code = cli_mod.main([
        "distill", "lfm3-tool", "tool-calls",
        "--teacher", TEACHER, "--prompts", "/tmp/prompts.txt",
    ])
    assert code == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.startswith("prompt ")]
    assert len(lines) == 5
    # No ETA yet: 0 and 1 prompts done.
    assert lines[0] == "prompt 1 of 10"
    assert lines[1] == "prompt 2 of 10"
    # Prompt 3: 2 done in 60s, 8 to go at 30s each: 4 minutes.
    assert lines[2] == "prompt 3 of 10, about 4 minutes left"
    # Prompt 5: 4 done in 120s, 6 to go: 3 minutes.
    assert lines[4] == "prompt 5 of 10, about 3 minutes left"
