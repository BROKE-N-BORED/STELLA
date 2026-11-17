"""model_info tests: what-it-does lines, size parsing, fit verdicts
(T18 — the model picker shows one plain line plus a fit verdict)."""
from stella.model_info import (
    GENERIC_DESCRIPTION,
    describe_model,
    estimate_training_ram_gb,
    fit_verdict,
    fits_this_pc,
    params_from_tag,
)


def test_describe_known_models():
    assert "fast" in describe_model("lfm3:1.7b").lower()
    assert "small" in describe_model("minicpm5-heretic:2b").lower()
    assert "following instructions" in describe_model(
        "qwen3-vl:2b-instruct"
    )
    assert "code" in describe_model("codellama:7b").lower()


def test_describe_longer_name_wins():
    # "codellama" and "tinyllama" both contain "llama": the longer,
    # more specific line must win, not Meta's general chat line.
    assert describe_model("codellama:7b") == "A model built for writing code."
    assert describe_model("tinyllama:1.1b") == "A tiny model for simple jobs."
    assert describe_model("llama3:8b") == "Meta's general chat model."


def test_describe_unknown_model_is_generic():
    assert describe_model("some-random-model:9b") == GENERIC_DESCRIPTION
    assert describe_model("") == GENERIC_DESCRIPTION


def test_params_from_tag():
    assert params_from_tag("lfm3:1.7b") == 1.7
    assert params_from_tag("qwen3.5:4b") == 4.0
    assert params_from_tag("LiquidAI/LFM3-1.7B") == 1.7
    assert params_from_tag("maternion/minicpm5-heretic:2b") == 2.0
    assert params_from_tag("qwen3-vl:2b-instruct") == 2.0
    # No size in the tag: nothing to estimate from.
    assert params_from_tag("lfm3:latest") is None
    assert params_from_tag("") is None


def test_estimate_training_ram_gb():
    # R43: 1.7B: 1.7 * 1.0 + 2.7 = 4.4 GB — reconciled with the
    # recalibrated training estimate (4.34 GB), not the old
    # 2.0/B + 3.0 rule that said 6.4 GB.
    assert estimate_training_ram_gb(1.7) == 4.4
    assert estimate_training_ram_gb(3.0) == 5.7
    assert estimate_training_ram_gb(8.0) == 10.7


def test_picker_estimate_matches_training_estimator():
    """R43: the picker formula and train.estimate_training_bytes
    agree at LFM3 scale. If the estimator changes, this fails and
    the picker's constants move with it — the two must not drift
    again."""
    from stella.train import (
        estimate_lora_params,
        estimate_training_bytes,
    )

    trainable = estimate_lora_params(
        hidden_size=2048, intermediate_size=8192,
        num_layers=24, rank=8,
    )
    total_bytes, _breakdown = estimate_training_bytes(
        params=1_700_000_000, trainable_params=trainable,
    )
    training_gb = total_bytes / 1024**3
    picker_gb = estimate_training_ram_gb(1.7)
    assert abs(picker_gb - training_gb) < 0.5
    # And the picker never understates the training estimate: the
    # coarse guide must err on the side of caution.
    assert picker_gb >= training_gb


def test_fits_this_pc():
    # R43: judged against TOTAL RAM now — free RAM is transient.
    assert fits_this_pc("lfm3:1.7b", 8.0) is True
    assert fits_this_pc("qwen3.5:4b", 8.0) is True  # needs 6.7 GB
    assert fits_this_pc("qwen3.5:8b", 8.0) is False  # needs 10.7 GB
    assert fits_this_pc("lfm3:1.7b", None) is None  # RAM unknown
    assert fits_this_pc("lfm3:latest", 8.0) is None  # size unknown


def test_fit_verdict_fits():
    line = fit_verdict("lfm3:1.7b", 2_000_000_000, 8.0)
    assert "Fits this PC" in line
    assert "4.4 GB" in line
    assert "1.9 GB" in line


def test_fit_verdict_too_big():
    line = fit_verdict("qwen3.5:8b", 5_000_000_000, 8.0)
    assert "Too big for this PC" in line
    assert "10.7 GB" in line
    assert "8.0 GB" in line
    # Honest wording (R43): total RAM, and the free-RAM check
    # still happens at train time.
    assert "in total" in line
    assert "checks the free RAM again when you train" in line


def test_fit_verdict_unknown_size():
    line = fit_verdict("lfm3:latest", 2_000_000_000, 8.0)
    assert "check it fits this PC when you train" in line


def test_fit_verdict_unknown_ram():
    line = fit_verdict("lfm3:1.7b", 2_000_000_000, None)
    assert "4.4 GB" in line
    assert "could not be measured" in line


def test_fit_verdict_no_em_dash():
    for line in (
        fit_verdict("lfm3:1.7b", 2_000_000_000, 8.0),
        fit_verdict("qwen3.5:8b", 5_000_000_000, 8.0),
        fit_verdict("lfm3:latest", None, None),
    ):
        assert "—" not in line
