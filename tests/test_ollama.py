"""Ollama lookup tests — fake localhost server + the down case."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from stella.ollama import OllamaError, chat_stream, list_model_sizes, list_models


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
