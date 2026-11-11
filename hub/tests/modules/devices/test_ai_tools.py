"""The tool configuration a managed machine's AI tools setting holds.

Every model nobody chose is the default model it is given. Codex and
Gemini given no model wrote cc-switch's own defaults, names the gateway did
not serve, and OpenCode's provider names its one model.
"""

from neutrino_hub.modules.devices.ai_tools import resolved_tool_configs


def test_every_unchosen_model_is_the_default_model_given():
    resolved = resolved_tool_configs({"claude": {"opus": "m2"}}, "m1")

    assert resolved == {
        "claude": {"default": "m1", "opus": "m2", "sonnet": "m1", "haiku": "m1"},
        "codex": {"model": "m1", "model_reasoning_effort": ""},
        "gemini": {"model": "m1"},
        "opencode": {"model": "m1"},
    }


def test_a_chosen_model_and_effort_stay_as_chosen():
    resolved = resolved_tool_configs(
        {
            "codex": {"model": "m3", "model_reasoning_effort": "high"},
            "gemini": {"model": "m4"},
            "opencode": {"model": "m5"},
        },
        "m1",
    )

    assert resolved["codex"] == {"model": "m3", "model_reasoning_effort": "high"}
    assert resolved["gemini"] == {"model": "m4"}
    assert resolved["opencode"] == {"model": "m5"}
