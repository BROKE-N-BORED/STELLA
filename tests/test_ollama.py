"""Ollama lookup tests — fake localhost server + the down case."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from stella.ollama import (
    MODEL_CACHE,
    ModelListCache,
    OllamaError,
    chat_stream,
    list_model_sizes,
    list_models,
)


class FakeOllama(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps({
                "models": [
                    {"name": "lfm3:1.7b", "size": 2000000000},
                    {"name": "qwen3-vl:2b-instruct", "size": 1500000000},
                ]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def test_list_models_from_fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert list_models(url) == ["lfm3:1.7b", "qwen3-vl:2b-instruct"]
    finally:
        server.shutdown()
        server.server_close()


def test_list_models_offline_returns_empty():
    # Nothing listens on this port — must return [], never raise.
    assert list_models("http://127.0.0.1:9") == []


def test_list_models_bad_payload_returns_empty():
    class BadHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"this is not json"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), BadHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert list_models(url) == []
    finally:
        server.shutdown()
        server.server_close()


def test_list_model_sizes_from_fake_server():
    """T18: the picker reads download sizes from /api/tags."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert list_model_sizes(url) == {
            "lfm3:1.7b": 2000000000,
            "qwen3-vl:2b-instruct": 1500000000,
        }
    finally:
        server.shutdown()
        server.server_close()


def test_list_model_sizes_offline_returns_empty():
    assert list_model_sizes("http://127.0.0.1:9") == {}


# -- T76: streaming chat ---------------------------------------------


class FakeStreamingOllama(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode())
        assert body["stream"] is True
        lines = [
            {"message": {"content": "Hello "}, "done": False},
            {"message": {"content": "there."}, "done": False},
            {"message": {"content": ""}, "done": True},
        ]
        payload = "".join(json.dumps(l) + "\n" for l in lines).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def test_chat_stream_streams_tokens_and_returns_full_text():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStreamingOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        tokens = []
        text = chat_stream(
            "lfm3:1.7b", [{"role": "user", "content": "hi"}],
            url=url, on_token=tokens.append,
        )
        assert text == "Hello there."
        assert tokens == ["Hello ", "there."]
    finally:
        server.shutdown()
        server.server_close()


def test_chat_stream_offline_raises_plain_words():
    # Nothing listens on this port — OllamaError, never a raw
    # connection error.
    with pytest.raises(OllamaError):
        chat_stream(
            "lfm3:1.7b", [{"role": "user", "content": "hi"}],
            url="http://127.0.0.1:9",
        )


# -- T43: the model-list cache ---------------------------------------


def _counting_server(delay=0.0, models=None):
    """A fake Ollama that counts /api/tags hits. Returns (server,
    url, state) where state["hits"] is the count."""
    state = {"hits": 0}
    if models is None:
        models = [
            {"name": "lfm3:1.7b", "size": 2000000000},
            {"name": "qwen3-vl:2b-instruct", "size": 1500000000},
        ]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/tags":
                state["hits"] += 1
                if delay:
                    time.sleep(delay)
                body = json.dumps({"models": models}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", state


def test_cache_refresh_fetches_once_and_serves_reads():
    """T43: one refresh fetches once and yields names + sizes;
    reads after it never touch the network."""
    server, url, state = _counting_server()
    try:
        cache = ModelListCache()
        assert cache.loaded is False
        models, sizes, loaded, up, _at = cache.refresh(url)
        assert state["hits"] == 1
        assert models == ["lfm3:1.7b", "qwen3-vl:2b-instruct"]
        assert sizes == {
            "lfm3:1.7b": 2000000000,
            "qwen3-vl:2b-instruct": 1500000000,
        }
        assert loaded is True
        assert up is True
        assert cache.models() == models
        assert cache.sizes() == sizes
        assert cache.snapshot()[0] == models
        assert state["hits"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_cache_refresh_always_refetches():
    """T43: a refresh is a refresh — it fetches again, it never
    serves a stale list as fresh."""
    server, url, state = _counting_server()
    try:
        cache = ModelListCache()
        cache.refresh(url)
        cache.refresh(url)
        assert state["hits"] == 2
    finally:
        server.shutdown()
        server.server_close()


def test_cache_concurrent_refreshes_make_one_fetch():
    """T43: refreshes racing each other make one fetch between
    them — the second waits for the first and takes its result."""
    server, url, state = _counting_server(delay=0.3)
    try:
        cache = ModelListCache()
        results = []

        def _refresh():
            results.append(cache.refresh(url))

        threads = [threading.Thread(target=_refresh) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert state["hits"] == 1
        assert len(results) == 4
        assert all(r[0] == ["lfm3:1.7b", "qwen3-vl:2b-instruct"] for r in results)
    finally:
        server.shutdown()
        server.server_close()


def test_cache_offline_refresh_marks_down_but_loaded():
    """T43: a refresh against a down Ollama still counts as loaded
    (the window knows Ollama is down; it does not keep asking)."""
    cache = ModelListCache()
    models, _sizes, loaded, up, _at = cache.refresh("http://127.0.0.1:9")
    assert models == []
    assert loaded is True
    assert up is False


def test_cache_set_snapshot_and_reset():
    """T43: the seed/reset pair tests use to control the cache."""
    cache = ModelListCache()
    cache.set_snapshot(["a:1"], {"a:1": 10})
    assert cache.loaded is True
    assert cache.models() == ["a:1"]
    assert cache.sizes() == {"a:1": 10}
    assert cache.ollama_up is True
    cache.reset()
    assert cache.loaded is False
    assert cache.models() == []
    assert cache.ollama_up is False


def test_cache_stale_refresh_does_not_overwrite_fresh():
    """T43: a slow refresh that lands after a fast one is
    discarded, not stored over the fresher list."""
    slow_server, slow_url, _slow = _counting_server(
        delay=0.5, models=[{"name": "slow:1", "size": 1}]
    )
    fast_server, fast_url, _fast = _counting_server(
        models=[{"name": "fast:1", "size": 1}]
    )
    try:
        cache = ModelListCache()
        slow_thread = threading.Thread(
            target=cache.refresh, args=(slow_url,), daemon=True
        )
        slow_thread.start()
        # The slow fetch is in flight before the fast one starts.
        deadline = 5000
        while _slow["hits"] == 0 and deadline > 0:
            time.sleep(0.05)
            deadline -= 50
        assert _slow["hits"] == 1
        cache.refresh(fast_url)
        assert cache.models() == ["fast:1"]
        slow_thread.join(timeout=10)
        assert cache.models() == ["fast:1"]
    finally:
        slow_server.shutdown()
        slow_server.server_close()
        fast_server.shutdown()
        fast_server.server_close()


def test_cache_different_urls_fetch_concurrently():
    """T43: the one-fetch dedup is per URL — two different URLs
    each get their own fetch, even when started together."""
    server_a, url_a, state_a = _counting_server(delay=0.2)
    server_b, url_b, state_b = _counting_server(delay=0.2)
    try:
        cache = ModelListCache()
        threads = [
            threading.Thread(target=cache.refresh, args=(url_a,)),
            threading.Thread(target=cache.refresh, args=(url_b,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert state_a["hits"] == 1
        assert state_b["hits"] == 1
    finally:
        server_a.shutdown()
        server_a.server_close()
        server_b.shutdown()
        server_b.server_close()


def test_module_cache_singleton_is_a_cache():
    assert isinstance(MODEL_CACHE, ModelListCache)
