"""v0.26.0 tests — the review P2 batch 1 (R24–R51): the dry-run
fit that counts dataset RAM, the offline cached model, the dataset
fingerprint on resume, the crashed-run reconciliation, the end of
`method: full` on the CLI, the byte-weighted GGUF quant, the
distill run that survives a bad prompt, the export and requant
disk guards, the cleanup that runs on interrupts too, the requant
timeout, the truncated-teacher check, the truthful recipe import,
the model layer's type checks, the export that validates what it
writes, the import size and disk guards, the clone that names its
dropped projects, the status bar that stays true with a live
session, the Settings Ollama overlap, the reconciled fit verdict,
the run-button row in view at 1366x768, the kept cloud-model pick
when Ollama is down, bounded chat history, every tool block run
and no raw JSON in the chat, agent-side template step tracking,
one model-list fetch per agent loop, and dated cloud model lists
with a staleness warning. The topical tests live with their
modules; this file carries the version pins and the slice-level
checks.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_cli(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store (one profile, one
    project) — the same fixture test_gui.py uses, defined here so
    this file stands alone."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    yield win
    win.close()


# -- Version --------------------------------------------------------
# (moved to test_v27.py — the version is 0.27.0 now)


# -- Slice: the CLI still offers --method, but only lora -----------


def test_method_flag_still_listed(home):
    """`stella create-project --method` is still a real option
    (R28): it accepts lora and refuses full in plain words."""
    res = run_cli(home, "create-project", "--help")
    assert res.returncode == 0
    assert "--method" in res.stdout


# -- Slice: the new mechanisms exist --------------------------------


def test_curated_lists_carry_a_check_date():
    """R51: every curated cloud list records when it was checked."""
    from stella.providers import PROVIDERS, list_checked_date

    for pid in ("groq", "gemini"):
        assert PROVIDERS[pid].get("checked")
        assert list_checked_date(pid) is not None


def test_agent_runs_every_tool_block():
    """R47/R48: the parser returns every tool call in a reply."""
    from stella.chat_agent import parse_tool_calls

    text = (
        "```tool\n{\"tool\": \"list_profiles\", \"args\": {}}\n```\n"
        "```tool\n{\"tool\": \"list_projects\", \"args\": {}}\n```"
    )
    plain, calls = parse_tool_calls(text)
    assert [name for name, _args in calls] == [
        "list_profiles",
        "list_projects",
    ]
    assert "{" not in plain
