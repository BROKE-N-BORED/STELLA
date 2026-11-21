"""STELLA v0.33.0 tests — the live Hugging Face lookup.

When the curated bridge map does not know a model's repo, Stella
searches Hugging Face itself (public Hub API, no key) and offers
what it finds in one tap. The tests run against a FAKE Hub server
(the R62 pattern): search results mixing GGUF and MLX repos with
one real training repo, ranking, the honest endings (nothing
offerable, Hub unreachable), and all four walls — the download
button, the train pre-check, and the chat tools. The bridge map
still wins: a mapped tag never triggers a search.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

import stella.chat_agent as chat_mod
import stella.gui as gui_mod
import stella.hub_lookup as hub_mod
import stella.provision as prov
from stella.chat_agent import ChatAgent
from stella.hub_lookup import (
    OFFLINE_MESSAGE,
    UNKNOWN_MESSAGE,
    lookup_hf_repos,
    search_terms,
)
from stella.model import STELLA_VERSION

ROOT = Path(__file__).resolve().parent.parent

REVIEWER_TAG = "dolphinlabs/qwen3.5-uncensored:latest"
FOUND_REPO = "dolphinlabs/qwen3.5-uncensored"


def _run_cli_subprocess(home, *args):
    """Run the real `python -m stella.cli` in a subprocess."""
    env = dict(os.environ)
    env["STELLA_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "stella.cli", *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )


# -- Version --------------------------------------------------------


# NOTE: the version tests moved to test_v34.py (test_version_is_0_36_0,
# test_window_title_carries_version) — the version is 0.36.0 now.


@pytest.fixture()
def window(qapp, seeded, settings):
    """The main window on the seeded store — the same fixture
    test_v30.py uses. Teardown also waits for the lookup worker,
    so a lookup cannot leak into the next test."""
    from stella.gui import MainWindow

    win = MainWindow(store=seeded, settings=settings)
    win.show()
    qapp.processEvents()
    if win._model_list_worker is not None:
        win._model_list_worker.wait(5000)
        qapp.processEvents()
    yield win
    from tests.test_gui import _wait_for_all_workers

    _wait_for_all_workers(win, qapp)
    if win._hub_lookup_worker is not None:
        win._hub_lookup_worker.wait(5000)
        qapp.processEvents()
    win.close()


# -- The fake Hub ---------------------------------------------------


def _weights_detail(*extra):
    """A repo detail with real training weights."""
    siblings = [{"rfilename": "config.json"}] + [
        {"rfilename": name} for name in extra
    ]
    return {"siblings": siblings}


class _FakeHub:
    """A local Hugging Face stand-in: /api/models?search= serves
    the configured result lists per term, /api/models/<id> serves
    the configured details. Records what was asked, in order."""

    def __init__(self, searches=None, details=None, delay=0.0):
        self.searches = searches or {}
        self.details = details or {}
        self.delay = delay
        self.asked_searches = []
        self.asked_details = []
        hub = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if hub.delay:
                    time.sleep(hub.delay)
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/api/models":
                    query = urllib.parse.parse_qs(parsed.query)
                    term = (query.get("search") or [""])[0]
                    hub.asked_searches.append(term)
                    payload = hub.searches.get(term, [])
                    self._json(payload)
                    return
                if parsed.path.startswith("/api/models/"):
                    repo = urllib.parse.unquote(
                        parsed.path[len("/api/models/"):]
                    )
                    hub.asked_details.append(repo)
                    detail = hub.details.get(repo)
                    if detail is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                    self._json(detail)
                    return
                self.send_response(404)
                self.end_headers()

            def _json(self, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.base = (
            f"http://127.0.0.1:{self._server.server_address[1]}"
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def fake_hub(monkeypatch):
    """Start a fake Hub and point the lookup at it. Yields a
    factory: fake_hub(searches=..., details=..., delay=...)."""
    hubs = []

    def make(**kwargs):
        hub = _FakeHub(**kwargs)
        hubs.append(hub)
        monkeypatch.setattr(hub_mod, "HUB_API_BASE", hub.base)
        return hub

    yield make
    for hub in hubs:
        hub.close()


# -- The query ladder -----------------------------------------------


def test_ladder_for_reviewer_tag():
    """No size anywhere: name, dashed name, then the family."""
    assert search_terms(REVIEWER_TAG) == [
        "qwen3.5-uncensored",
        "qwen-3.5-uncensored",
        "qwen",
    ]


def test_ladder_for_granite_tag():
    """The size comes from the version: family + size is the
    last rung, and the family alone is not searched."""
    assert search_terms("huihui_ai/granite4.1-abliterated:3b") == [
        "granite4.1-abliterated",
        "granite-4.1-abliterated",
        "granite 3b",
    ]


def test_ladder_for_bonsai_tag():
    """The dashed form equals the name, so it is not repeated."""
    assert search_terms("bonsai-2:4b") == ["bonsai-2", "bonsai 4b"]


# -- The lookup against the fake Hub --------------------------------


def test_lookup_filters_gguf_and_mlx_and_offers_the_real_repo(fake_hub):
    """A Granite-style search: mostly GGUF/MLX repos, one real
    training repo. Only the real one is offered, and the name
    filter keeps the GGUF/MLX repos from even being opened."""
    hub = fake_hub(
        searches={
            "granite4.1-abliterated": [
                {"id": "mradermacher/Granite-4.1-3B-Abliterated-GGUF",
                 "downloads": 5000},
                {"id": "nightmedia/granite-4.1-3b-mlx", "downloads": 900},
                {"id": "ibm-granite/granite-4.1-3b-base",
                 "downloads": 10000},
            ],
        },
        details={
            "ibm-granite/granite-4.1-3b-base": _weights_detail(
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ),
        },
    )
    result = lookup_hf_repos("huihui_ai/granite4.1-abliterated:3b")
    assert result["state"] == "found"
    assert result["candidates"] == [
        {"repo": "ibm-granite/granite-4.1-3b-base",
         "source": "found on Hugging Face"}
    ]
    assert hub.asked_details == ["ibm-granite/granite-4.1-3b-base"]


def test_lookup_rejects_gguf_only_files(fake_hub):
    """A repo whose name passes the filter but whose files are
    GGUF-only is not offerable: no config.json, no safetensors."""
    fake_hub(
        searches={
            "bonsai-2": [
                {"id": "someone/bonsai-2-port", "downloads": 10},
            ],
            "bonsai 4b": [],
        },
        details={
            "someone/bonsai-2-port": {
                "siblings": [{"rfilename": "bonsai-2-q4_k_m.gguf"}]
            },
        },
    )
    result = lookup_hf_repos("bonsai-2:4b")
    assert result == {"state": "none", "candidates": []}


def test_lookup_ranking_exact_then_own_org_then_downloads(fake_hub):
    """Ranking is deterministic: an exact name match beats the
    tag's own org, which beats raw downloads."""
    ids = [
        {"id": "bigcorp/qwen3.5-uncensored-xl", "downloads": 900000},
        {"id": "dolphinlabs/qwen3.5-uncensored-plus", "downloads": 50},
        {"id": "someone/qwen3.5-uncensored", "downloads": 5},
    ]
    fake_hub(
        searches={"qwen3.5-uncensored": ids},
        details={
            item["id"]: _weights_detail("model.safetensors")
            for item in ids
        },
    )
    result = lookup_hf_repos(REVIEWER_TAG)
    assert result["state"] == "found"
    assert [c["repo"] for c in result["candidates"]] == [
        "someone/qwen3.5-uncensored",
        "dolphinlabs/qwen3.5-uncensored-plus",
        "bigcorp/qwen3.5-uncensored-xl",
    ]


def test_lookup_walks_the_ladder_until_a_rung_pays_off(fake_hub):
    """The first rung finds nothing; the dashed rung finds the
    repo. The family rung is never searched."""
    hub = fake_hub(
        searches={
            "qwen3.5-uncensored": [],
            "qwen-3.5-uncensored": [
                {"id": FOUND_REPO, "downloads": 42},
            ],
        },
        details={FOUND_REPO: _weights_detail("model.safetensors")},
    )
    result = lookup_hf_repos(REVIEWER_TAG)
    assert result["state"] == "found"
    assert hub.asked_searches == [
        "qwen3.5-uncensored", "qwen-3.5-uncensored",
    ]


def test_lookup_none_when_nothing_offerable(fake_hub):
    """Every rung empty: the search completed, nothing to offer."""
    fake_hub(searches={})
    result = lookup_hf_repos("bonsai-2:4b")
    assert result == {"state": "none", "candidates": []}


def test_lookup_offline_when_hub_is_down(monkeypatch):
    """Connection refused: the offline state, never an exception."""
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setattr(
        hub_mod, "HUB_API_BASE", f"http://127.0.0.1:{port}"
    )
    result = lookup_hf_repos(REVIEWER_TAG, timeout=5.0)
    assert result == {"state": "offline", "candidates": []}


def test_lookup_timeout_is_offline(fake_hub):
    """A Hub that answers too slowly is the offline state too."""
    fake_hub(searches={}, delay=2.0)
    result = lookup_hf_repos(REVIEWER_TAG, timeout=0.3)
    assert result == {"state": "offline", "candidates": []}


# -- The GUI walls ----------------------------------------------------


def _wait_for_lookup(window, qapp, timeout_ms=10000):
    """Wait for the window's lookup worker and its done slot."""
    waited = 0
    while window._hub_lookup_in_flight():
        QTest.qWait(50)
        waited += 50
        assert waited < timeout_ms, "lookup did not finish in time"
    qapp.processEvents()


def _mock_download(window, monkeypatch, started):
    monkeypatch.setattr(prov, "hub_available", lambda: True)
    monkeypatch.setattr(window.download_manager, "start", started.append)


def _reviewer_profile(window):
    window.store.create_profile(
        "reviewer", ollama_tag=REVIEWER_TAG, role="fast"
    )


def _found_one(monkeypatch, repo=FOUND_REPO):
    monkeypatch.setattr(
        gui_mod, "lookup_hf_repos",
        lambda tag, **k: {
            "state": "found",
            "candidates": [
                {"repo": repo, "source": "found on Hugging Face"}
            ],
        },
    )


def test_gui_lookup_yes_sets_repo_and_starts_download(
    window, qapp, monkeypatch
):
    """The reviewer has no bridge entry: the lookup runs, the
    offer names what Stella found, Yes stores the repo and the
    download starts at once."""
    _reviewer_profile(window)
    _found_one(monkeypatch)
    asked = []

    def fake_question(self, title, text, *a, **k):
        asked.append(text)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    _wait_for_lookup(window, qapp)
    assert asked == [
        f"Stella found {FOUND_REPO} on Hugging Face for this "
        "model. Use it?"
    ]
    assert window.store.get_profile("reviewer")["base_ref"] == (
        FOUND_REPO
    )
    assert started == [FOUND_REPO]


def test_gui_lookup_declined_sets_nothing(window, qapp, monkeypatch):
    """No at the offer: nothing stored, nothing downloaded."""
    _reviewer_profile(window)
    _found_one(monkeypatch)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.No
    )
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    _wait_for_lookup(window, qapp)
    assert window.store.get_profile("reviewer")["base_ref"] == (
        REVIEWER_TAG
    )
    assert started == []


def test_gui_lookup_several_candidates_pick_one(
    window, qapp, monkeypatch
):
    """Several found repos: the pick-one dialog, in ranking
    order; the pick is stored and downloaded."""
    _reviewer_profile(window)
    monkeypatch.setattr(
        gui_mod, "lookup_hf_repos",
        lambda tag, **k: {
            "state": "found",
            "candidates": [
                {"repo": "someone/qwen3.5-uncensored",
                 "source": "found on Hugging Face"},
                {"repo": FOUND_REPO,
                 "source": "found on Hugging Face"},
            ],
        },
    )
    seen = {}

    class FakePick:
        def __init__(self, candidates, parent=None):
            seen["candidates"] = [c["repo"] for c in candidates]
            self.chosen = FOUND_REPO

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(gui_mod, "BridgePickDialog", FakePick)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    _wait_for_lookup(window, qapp)
    assert seen["candidates"] == [
        "someone/qwen3.5-uncensored", FOUND_REPO,
    ]
    assert window.store.get_profile("reviewer")["base_ref"] == (
        FOUND_REPO
    )
    assert started == [FOUND_REPO]


def test_gui_lookup_none_shows_the_unknown_message(
    window, qapp, monkeypatch
):
    """The search completed and found nothing offerable: the
    honest unknown message, nothing stored."""
    _reviewer_profile(window)
    monkeypatch.setattr(
        gui_mod, "lookup_hf_repos",
        lambda tag, **k: {"state": "none", "candidates": []},
    )
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    _wait_for_lookup(window, qapp)
    assert warnings == [UNKNOWN_MESSAGE]
    assert started == []
    assert window.store.get_profile("reviewer")["base_ref"] == (
        REVIEWER_TAG
    )


def test_gui_lookup_offline_shows_the_try_again_message(
    window, qapp, monkeypatch
):
    """The Hub unreachable: the plain couldn't-reach message,
    never the old go-find-it-yourself wording."""
    _reviewer_profile(window)
    monkeypatch.setattr(
        gui_mod, "lookup_hf_repos",
        lambda tag, **k: {"state": "offline", "candidates": []},
    )
    warnings = []
    monkeypatch.setattr(window, "_warn", warnings.append)
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    _wait_for_lookup(window, qapp)
    assert warnings == [OFFLINE_MESSAGE]
    assert "Find the model on huggingface.co" not in warnings[0]
    assert started == []


def test_gui_bridge_map_wins_and_never_looks_up(
    window, qapp, monkeypatch
):
    """A mapped tag (lfm3) is answered by the bridge alone: the
    lookup is never called."""
    def forbidden(tag, **k):
        raise AssertionError("a mapped tag must not trigger a search")

    monkeypatch.setattr(gui_mod, "lookup_hf_repos", forbidden)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    started = []
    _mock_download(window, monkeypatch, started)
    window.set_session("lfm3-tool", "tool-calls")
    window.start_download()
    assert window.store.get_profile("lfm3-tool")["base_ref"] == (
        "LiquidAI/LFM3-1.7B"
    )
    assert started == ["LiquidAI/LFM3-1.7B"]


def test_gui_weights_offer_lookup_then_download_question(
    window, qapp, monkeypatch
):
    """The train pre-check on an unknown tag: the lookup offer,
    then the same "Download the model first?" question the
    bridge path falls through to."""
    _reviewer_profile(window)
    _found_one(monkeypatch)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    started = []
    monkeypatch.setattr(
        window, "start_download",
        lambda profile=None: started.append(profile),
    )
    assert window._weights_offer("reviewer") is False
    _wait_for_lookup(window, qapp)
    assert window.store.get_profile("reviewer")["base_ref"] == (
        FOUND_REPO
    )
    assert started == ["reviewer"]


def test_gui_lookup_end_to_end_against_the_fake_hub(
    window, qapp, monkeypatch, fake_hub
):
    """The whole flow over real HTTP: the reviewer profile, a
    search mixing a GGUF repo with the real one, the offer, the
    download. This is the drive the screenshots verify."""
    _reviewer_profile(window)
    fake_hub(
        searches={
            "qwen3.5-uncensored": [
                {"id": "mradermacher/qwen3.5-uncensored-GGUF",
                 "downloads": 8000},
                {"id": FOUND_REPO, "downloads": 120},
            ],
        },
        details={FOUND_REPO: _weights_detail("model.safetensors")},
    )
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.Yes
    )
    started = []
    _mock_download(window, monkeypatch, started)
    window.start_download("reviewer")
    _wait_for_lookup(window, qapp)
    assert window.store.get_profile("reviewer")["base_ref"] == (
        FOUND_REPO
    )
    assert started == [FOUND_REPO]


# -- The chat walls ---------------------------------------------------


@pytest.fixture()
def agent(store, monkeypatch):
    monkeypatch.setattr(
        chat_mod, "list_models", lambda: ["lfm3:1.7b", "qwen3.5:2b"]
    )
    return ChatAgent(store, "lfm3:1.7b")


def _chat_found(monkeypatch, repo=FOUND_REPO):
    monkeypatch.setattr(
        chat_mod, "lookup_hf_repos",
        lambda tag, **k: {
            "state": "found",
            "candidates": [
                {"repo": repo, "source": "found on Hugging Face"}
            ],
        },
    )


def test_chat_lookup_offer_then_confirm_downloads(
    agent, store, seeded, monkeypatch
):
    """The chat round-trip for a found repo: the first call names
    what Stella found and asks; confirm + repo stores it and the
    download runs."""
    store.create_profile(
        "reviewer", ollama_tag=REVIEWER_TAG, role="fast"
    )
    _chat_found(monkeypatch)
    first = agent.call_tool(
        "download_weights", {"profile": "reviewer"}
    )
    assert (
        f"Stella found {FOUND_REPO} on Hugging Face for this model."
        in first
    )
    assert "Say yes" in first
    assert store.get_profile("reviewer")["base_ref"] == REVIEWER_TAG
    monkeypatch.setattr(chat_mod, "hub_available", lambda: True)
    monkeypatch.setattr(chat_mod, "run_download", lambda repo, **k: 0)
    second = agent.call_tool(
        "download_weights",
        {"profile": "reviewer", "confirm": True, "repo": FOUND_REPO},
    )
    assert store.get_profile("reviewer")["base_ref"] == FOUND_REPO
    assert "downloaded and ready" in second


def test_chat_lookup_confirm_wrong_repo_refused(
    agent, store, seeded, monkeypatch
):
    """A confirm naming a repo the lookup did not find is
    refused — a made-up name is never silently stored."""
    store.create_profile(
        "reviewer", ollama_tag=REVIEWER_TAG, role="fast"
    )
    _chat_found(monkeypatch)
    result = agent.call_tool(
        "download_weights",
        {
            "profile": "reviewer",
            "confirm": True,
            "repo": "SomeoneElse/NotACandidate",
        },
    )
    assert "not one of the repos I suggested" in result
    assert store.get_profile("reviewer")["base_ref"] == REVIEWER_TAG


def test_chat_lookup_offline_message(agent, store, seeded, monkeypatch):
    """The Hub unreachable in chat: the plain try-again message."""
    store.create_profile(
        "reviewer", ollama_tag=REVIEWER_TAG, role="fast"
    )
    monkeypatch.setattr(
        chat_mod, "lookup_hf_repos",
        lambda tag, **k: {"state": "offline", "candidates": []},
    )
    result = agent.call_tool(
        "download_weights", {"profile": "reviewer"}
    )
    assert result == OFFLINE_MESSAGE


def test_chat_lookup_none_is_the_unknown_message(
    agent, store, seeded, monkeypatch
):
    """A completed search with nothing offerable in chat: the
    honest unknown answer."""
    store.create_profile(
        "reviewer", ollama_tag=REVIEWER_TAG, role="fast"
    )
    monkeypatch.setattr(
        chat_mod, "lookup_hf_repos",
        lambda tag, **k: {"state": "none", "candidates": []},
    )
    result = agent.call_tool(
        "download_weights", {"profile": "reviewer"}
    )
    assert result == UNKNOWN_MESSAGE


def test_chat_mapped_tag_never_looks_up(agent, store, seeded, monkeypatch):
    """The bridge answers lfm3 alone in chat too: no lookup."""
    def forbidden(tag, **k):
        raise AssertionError("a mapped tag must not trigger a search")

    monkeypatch.setattr(chat_mod, "lookup_hf_repos", forbidden)
    result = agent.call_tool(
        "download_weights", {"profile": "lfm3-tool"}
    )
    assert "LiquidAI/LFM3-1.7B" in result
    assert "Liquid AI's own repo for this model" in result


def test_chat_start_training_lookup_offer(
    agent, store, seeded, monkeypatch
):
    """start_training on an unknown tag offers the found repo and
    still says the weights need downloading first."""
    store.create_profile(
        "reviewer", ollama_tag=REVIEWER_TAG, role="fast"
    )
    store.create_project("reviewer", "job")
    _chat_found(monkeypatch)
    monkeypatch.setattr(chat_mod, "training_deps_missing", lambda: [])
    result = agent.call_tool(
        "start_training",
        {"profile": "reviewer", "project": "job"},
    )
    assert (
        f"Stella found {FOUND_REPO} on Hugging Face for this model."
        in result
    )
    assert "Training still needs the weights downloaded first" in (
        result
    )
    assert store.get_profile("reviewer")["base_ref"] == REVIEWER_TAG
