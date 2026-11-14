"""Project template tests (T112): JSON in stella/templates/."""
import pytest

from stella import templates as templates_mod
from stella.model import StellaError


def test_lfm3_tool_format_template_loads():
    """T112 Done: the first template is the LFM3 tool-format
    preset, carrying the audit's recommended defaults."""
    template = templates_mod.load_template("lfm3-tool-format")
    assert template["name"] == "lfm3-tool-format"
    assert template["title"] == "LFM3 tool calls"
    assert template["description"]
    assert template["mode"] == "both"
    assert template["dataset_ref"] == "sample-tool-calls.jsonl"
    assert template["base_ref"] == "LiquidAI/LFM3-1.7B"
    settings = template["settings"]
    assert settings["rank"] == 8
    assert settings["learning_rate"] == 0.0002
    assert settings["epochs"] == 3
    assert settings["batch_size"] == 1
    assert settings["method"] == "lora"


def test_list_templates_includes_lfm3():
    names = [t["name"] for t in templates_mod.list_templates()]
    assert "lfm3-tool-format" in names
    assert names == sorted(names)


def test_load_unknown_template_raises():
    with pytest.raises(StellaError) as exc:
        templates_mod.load_template("no-such-template")
    assert "no template named" in str(exc.value)
    assert "lfm3-tool-format" in str(exc.value)


def test_template_project_kwargs_carry_dataset_settings_mode():
    """T112: a template gives create_project its dataset, settings,
    and mode — and never the base (the base belongs to the
    profile, not the project)."""
    template = templates_mod.load_template("lfm3-tool-format")
    kwargs = templates_mod.template_project_kwargs(template)
    assert kwargs["dataset_ref"] == "sample-tool-calls.jsonl"
    assert kwargs["metamorph_mode"] == "both"
    assert kwargs["settings"]["rank"] == 8
    assert "base_ref" not in kwargs


def test_template_prefills_a_project(store):
    """T112 Done: creating from the LFM3 template pre-fills the
    preset values."""
    from stella.model import metamorph_mode

    store.create_profile("p1", base_ref="LiquidAI/LFM3-1.7B")
    template = templates_mod.load_template("lfm3-tool-format")
    data = store.create_project(
        "p1", "tool-try",
        **templates_mod.template_project_kwargs(template),
    )
    assert data["dataset_ref"] == "sample-tool-calls.jsonl"
    assert metamorph_mode(data) == "both"
    assert data["settings"]["rank"] == 8
    assert data["settings"]["epochs"] == 3


def test_template_validation_rejects_bad_mode():
    with pytest.raises(StellaError, match="mode must be"):
        templates_mod._validate_template(
            {
                "name": "bad", "title": "Bad", "description": "d",
                "mode": "shrink", "dataset_ref": "x.jsonl",
                "base_ref": "b",
            },
            "bad.json",
        )


def test_template_validation_rejects_bad_setting():
    with pytest.raises(StellaError):
        templates_mod._validate_template(
            {
                "name": "bad", "title": "Bad", "description": "d",
                "mode": "morph", "dataset_ref": "x.jsonl",
                "base_ref": "b", "settings": {"rank": 999},
            },
            "bad.json",
        )
