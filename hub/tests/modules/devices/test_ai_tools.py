"""The tool configuration a managed machine's AI tools setting holds.

Every model nobody chose is the gateway's first served model. Codex and
Gemini given no model wrote cc-switch's own defaults, names the gateway did
not serve.
"""

from neutrino_hub.modules.devices.ai_tools import resolved_tool_configs


def test_every_unchosen_model_is_the_first_served_model():
    resolved = resolved_tool_configs({"claude": {"opus": "m2"}}, "m1")

    assert resolved == {
        "claude": {"default": "m1", "opus": "m2", "sonnet": "m1", "haiku": "m1"},
        "codex": {"model": "m1", "model_reasoning_effort": ""},
        "gemini": {"model": "m1"},
    }


def test_a_chosen_model_and_effort_stay_as_chosen():
    resolved = resolved_tool_configs(
        {
            "codex": {"model": "m3", "model_reasoning_effort": "high"},
            "gemini": {"model": "m4"},
        },
        "m1",
    )

    assert resolved["codex"] == {"model": "m3", "model_reasoning_effort": "high"}
    assert resolved["gemini"] == {"model": "m4"}
