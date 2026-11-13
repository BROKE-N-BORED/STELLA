"""Debug log layer tests (U12): ring buffer, scrubbing, report,
crash handler."""
import sys

from stella.debug_log import (
    DebugLogger,
    check_ollama,
    is_sensitive_key,
    scrub_dict,
    scrub_text,
)


def _logger(tmp_path, **kwargs):
    return DebugLogger("stella", "0.4.0", log_dir=str(tmp_path / "logs"),
                       **kwargs)


def test_ring_buffer_keeps_last_n(tmp_path):
    log = _logger(tmp_path, history=5)
    for i in range(7):
        log.action(f"step {i}")
    assert len(log._ring.records) == 5
    assert "step 6" in log._ring.records[-1]
    assert not any("step 0" in r for r in log._ring.records)
    assert not any("step 1" in r for r in log._ring.records)


def test_action_goes_to_ring_buffer(tmp_path):
    log = _logger(tmp_path)
    log.action("profile created: lfm3-tool")
    assert any("profile created: lfm3-tool" in r
               for r in log._ring.records)


def test_scrub_text_redacts_secrets():
    assert "[REDACTED]" in scrub_text("api_key=hunter2")
    assert "hunter2" not in scrub_text("api_key=hunter2")
    assert "[REDACTED]" in scrub_text("Authorization: Bearer abc123")
    assert "abc123" not in scrub_text("Authorization: Bearer abc123")
    assert "plain text" in scrub_text("plain text")


def test_is_sensitive_key():
    assert is_sensitive_key("api_key")
    assert is_sensitive_key("HF_TOKEN")
    assert is_sensitive_key("password")
    assert not is_sensitive_key("model")
    assert not is_sensitive_key("home")


def test_scrub_dict_marks_secrets_present_or_absent():
    out = scrub_dict({"api_key": "hunter2", "token": "", "model": "lfm3"})
    assert out["api_key"] == "[REDACTED], present"
    assert out["token"] == "[absent]"
    assert out["model"] == "lfm3"


def test_report_sections_and_scrubbing(tmp_path):
    log = _logger(tmp_path)
    log.set_setting("api_key", "hunter2")
    log.set_setting("home", "/home/joshua/.stella")
    log.register_service("ollama", lambda: "not reachable")
    log.register_dependency("PySide6")
    log.action("did a thing")
    log.error("something broke")
    report = log.build_report()
    assert "DEBUG REPORT: stella 0.4.0" in report
    assert "== Context ==" in report
    assert "== Settings ==" in report
    assert "== Services ==" in report
    assert "== Recent actions" in report
    assert "== Errors ==" in report
    assert "== Log tail" in report
    assert "hunter2" not in report
    assert "[REDACTED], present" in report
    assert "/home/joshua/.stella" in report
    assert "did a thing" in report
    assert "something broke" in report
    assert "PySide6" in report


def test_generate_report_writes_file_and_suffixes(tmp_path):
    log = _logger(tmp_path)
    first = log.generate_report()
    second = log.generate_report()
    assert first != second
    assert first.endswith(".txt")
    assert "-2.txt" in second
    text = open(first, encoding="utf-8").read()
    assert "DEBUG REPORT: stella 0.4.0" in text


def test_crash_handler_writes_report(tmp_path):
    log = _logger(tmp_path)
    original_hook = sys.excepthook
    sys.excepthook = lambda *args: None  # keep the test output clean
    try:
        log.install_crash_handler()
        log.install_crash_handler()  # safe to call twice
        sys.excepthook(ValueError, ValueError("boom"), None)
    finally:
        log.uninstall_crash_handler()
        sys.excepthook = original_hook
    reports = list((tmp_path / "logs").glob("debug-report-stella-*.txt"))
    assert len(reports) == 1
    assert "boom" in reports[0].read_text(encoding="utf-8")


def test_check_ollama_unreachable():
    # Port 9 (discard) is closed: connection refused, instantly.
    result = check_ollama("http://127.0.0.1:9", timeout=1)
    assert "not reachable" in result
