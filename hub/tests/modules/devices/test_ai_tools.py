"""The tool configuration a managed machine's AI tools setting holds.

Every model nobody chose is the default model it is given. Codex and
Gemini given no model wrote cc-switch's own defaults, names the gateway did
not serve, and OpenCode's provider names its one model. The section holds
the length of each model its accounts' tool configurations name.
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


def test_the_section_holds_the_length_of_each_model_its_accounts_name(
    monkeypatch, tmp_path
):
    from neutrino_hub.modules.devices.accounts import DeviceAccount
    from neutrino_hub.modules.devices.desired_state import ai_tools_agent_config

    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    wide = {"context_length": 400000, "input_limit": 272000, "output_limit": 128000}
    ollama = {"context_length": 16384, "input_limit": 0, "output_limit": 0}
    accounts = [
        DeviceAccount(
            account="dan",
            is_ai_tools_enabled=True,
            tool_configs={"codex": {"model": "lab-mini"}},
        ),
        DeviceAccount(
            account="eve",
            is_ai_tools_enabled=True,
            tool_configs={"claude": {"default": "qwen", "haiku": "lab-mini"}},
        ),
    ]

    section = ai_tools_agent_config(
        accounts,
        {"os": "linux"},
        {"gateway_url": "http://127.0.0.1:8317", "gateway_key": "k"},
        ["lab-mini", "qwen", "unused"],
        context_lengths={"lab-mini": wide, "qwen": ollama, "unused": ollama},
    )
    off = ai_tools_agent_config(
        accounts,
        {"os": "linux"},
        {"gateway_url": "", "gateway_key": ""},
        ["qwen"],
        context_lengths={"qwen": ollama},
    )

    assert section["context_lengths"] == {"lab-mini": wide, "qwen": ollama}
    assert "context_lengths" not in off
