"""How to Use content tests: the full index exists, in order,
in plain words, with no em-dashes and no bare ampersands, and
accurate about what Stella actually does."""
from stella.howto import TOPICS, topic_text, topic_titles

EXPECTED_TITLES = [
    "Getting started",
    "Chat",
    "Picking a model",
    "Profiles",
    "Projects",
    "Training",
    "Sleep",
    "Export and import",
    "The refusal probe",
    "GGUF export to Ollama",
    "Making a model smaller",
    "Teaching a small model",
    "Troubleshooting",
]


def test_thirteen_topics_in_order():
    assert topic_titles() == EXPECTED_TITLES
    assert len(TOPICS) == 13


def test_every_topic_has_real_content():
    for title in EXPECTED_TITLES:
        text = topic_text(title)
        assert text is not None
        assert len(text) > 200, title


def test_unknown_topic_is_none():
    assert topic_text("No such topic") is None


def test_no_em_dash_in_any_topic():
    for title, body in TOPICS:
        assert "—" not in body, title


def test_no_bare_ampersand_in_any_topic():
    for title, body in TOPICS:
        assert "&" not in body, title
        assert "&" not in title, title


def test_content_is_honest_about_limits():
    training = topic_text("Training")
    assert "hours" in training
    projects = topic_text("Projects")
    # The Projects topic no longer mentions MetaMorphAi: the setting
    # is gone from the window, so there is nothing to explain.
    assert "metamorph" not in projects.lower()
    troubleshooting = topic_text("Troubleshooting")
    assert "Download model" in troubleshooting
    gguf = topic_text("GGUF export to Ollama")
    assert "Q4_K_M" in gguf
    sleep = topic_text("Sleep")
    assert "DEGRADED" in sleep
    smaller = topic_text("Making a model smaller")
    assert "loses a little quality" in smaller
    assert "never touched" in smaller
    teaching = topic_text("Teaching a small model")
    assert "only as good as the teacher" in teaching
    assert "untouched" in teaching
