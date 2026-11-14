"""Ollama lookup tests — fake localhost server + the down case."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from stella.ollama import list_model_sizes, list_models


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
