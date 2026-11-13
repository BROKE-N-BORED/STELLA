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


def test_cli_distill_teacher_unreachable_exit_1(home, tmp_path):
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
