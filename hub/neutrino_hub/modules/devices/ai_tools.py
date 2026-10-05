"""The tool configuration a managed machine's AI tools setting holds.

The shape is the desktop client's own, the one its Configure dialog saves:
Claude Code's four role slots, Codex's model and reasoning effort, and
Gemini's model. The hub cleans what the panel sends the way the client
cleans what its page sends, and fills the slots nobody chose the way the
client does before it hands the configuration to cc-switch.
"""

from neutrino_hub.modules.devices.constants import (
    DEVICE_AI_CLAUDE_SLOTS,
    DEVICE_AI_REASONING_EFFORT_KEY,
    DEVICE_AI_REASONING_EFFORTS,
    DEVICE_AI_TOOL_CONFIG_KEYS,
)


def clean_tool_configs(raw: dict) -> dict:
    """The tool choices with unknown tools and knobs dropped.

    Args:
        raw: What the panel sent, or what the file holds.

    Returns:
        ``{tool: {knob: value}}`` for every tool, holding only the knobs
        that exist and have a value; an effort outside its scale is
        dropped.
    """
    raw = raw if isinstance(raw, dict) else {}
    configs = {}
    for tool, knobs in DEVICE_AI_TOOL_CONFIG_KEYS.items():
        values = raw.get(tool)
        values = values if isinstance(values, dict) else {}
        kept = {}
        for knob in knobs:
            value = str(values.get(knob, "") or "")
            if (
                knob == DEVICE_AI_REASONING_EFFORT_KEY
                and value not in DEVICE_AI_REASONING_EFFORTS
            ):
                value = ""
            if value:
                kept[knob] = value
        configs[tool] = kept
    return configs


def resolved_tool_configs(tool_configs: dict, default_model: str) -> dict:
    """The choices with the gateway's first model filling the unchosen slots.

    Args:
        tool_configs: The cleaned choices.
        default_model: The first model the gateway serves.

    Returns:
        ``{claude: {default, opus, sonnet, haiku}, codex: {model,
        model_reasoning_effort}, gemini: {model}}``: every Claude slot
        carries a model; Codex's and Gemini's knobs are the chosen ones or
        empty, as the client leaves them.
    """
    claude = tool_configs.get("claude") or {}
    codex = tool_configs.get("codex") or {}
    gemini = tool_configs.get("gemini") or {}
    return {
        "claude": {
            slot: str(claude.get(slot, "") or "") or default_model
            for slot in DEVICE_AI_CLAUDE_SLOTS
        },
        "codex": {
            "model": str(codex.get("model", "") or ""),
            DEVICE_AI_REASONING_EFFORT_KEY: str(
                codex.get(DEVICE_AI_REASONING_EFFORT_KEY, "") or ""
            ),
        },
        "gemini": {"model": str(gemini.get("model", "") or "")},
    }
