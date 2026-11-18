"""How to Use content tests: the full index exists, in order,
in plain words, with no em-dashes and no bare ampersands, and
accurate about what Stella actually does."""
from stella.howto import TOPICS, topic_text, topic_titles

EXPECTED_TITLES = [
    "Getting started",
    "Chat",
    "Picking a model",
    "Bridge",
    "Profiles",
    "Projects",
    "Training",
    "Checkpoints",
    "Sleep",
    "Export and import",
    "Recipe and adapter packages",
    "The refusal probe",
    "Governing seats",
    "GGUF export to Ollama",
    "Making a model smaller",
    "Teaching a small model",
    "Troubleshooting",
    "Shortcuts",
]


def test_eighteen_topics_in_order():
    # R70: four topics added (Bridge, Checkpoints, Recipe and
    # adapter packages, Governing seats) — the count moves
    # deliberately, from 13 to 17. R98: the Shortcuts topic,
    # generated from the shortcut registry, makes 18.
    assert topic_titles() == EXPECTED_TITLES
    assert len(TOPICS) == 18


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


def test_jobs_start_from_the_window_not_the_terminal():
    """T75: re-quantize and distill start from the window with no
    typing. How to Use stops sending the user to the terminal for
    them (the installer mention in Getting started is fine — it is
    not a job)."""
    smaller = topic_text("Making a model smaller")
    assert "stella-cli requant" not in smaller
    assert "terminal" not in smaller.lower()
    teach = topic_text("Teaching a small model")
    assert "stella-cli distill" not in teach
    assert "terminal" not in teach.lower()
    assert "stella train" not in teach
    assert "press Go" in smaller
    assert "press Go" in teach


def test_probe_topic_names_right_seats_and_counts():
    # R70: the probe topic names the real governing seats
    # (driver, reviewer, tester, fast — not judge/merger) and
    # the real prompt counts (18 by default, 24 for a
    # governing seat — not 12).
    probe = topic_text("The refusal probe")
    assert "18 plainly harmless" in probe
    assert "24 for a governing seat" in probe
    assert "12 plainly harmless" not in probe
    assert "driver, reviewer,\ntester, fast" in probe
    assert "judge" not in probe
    assert "merger" not in probe


def test_profiles_topic_tag_is_dreaming_only():
    # R70: the Ollama tag is used for dreaming, not for the
    # refusal probe (probe.py has no ollama_tag reference).
    profiles = topic_text("Profiles")
    assert "Used for\ndreaming" in profiles
    assert "The refusal probe does not use it" in profiles


def test_gguf_topic_names_the_quant_picker():
    # R70: the GGUF topic says the quant is picked, not fixed.
    gguf = topic_text("GGUF export to Ollama")
    assert "Quant list" in gguf
    assert "Q4_K_M\nby default" in gguf


def test_new_topics_cover_the_missing_features():
    # R70: the four added topics say what their feature does.
    bridge = topic_text("Bridge")
    assert "Hugging Face" in bridge
    assert "stella bridge" in bridge
    checkpoints = topic_text("Checkpoints")
    assert "Resume from selected" in checkpoints
    assert "Prune" in checkpoints
    packages = topic_text("Recipe and adapter packages")
    assert "no weights" in packages
    assert "bare trained weights" in packages
    seats = topic_text("Governing seats")
    assert "driver, reviewer, tester, and\nfast" in seats
    assert "governing-seat marker" in seats
    assert "cannot be exported" in seats


def test_profiles_topic_points_download_at_the_main_window():
    """T79: the download row lives in the main window only."""
    profiles = topic_text("Profiles")
    assert "The profile window also has the Download model button" not in profiles
    assert "main window has the Download model button" in profiles
