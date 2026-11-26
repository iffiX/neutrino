"""The vendor presets: the shipped table, and the vendor a provider's base URL names."""

import pytest

from neutrino_hub.modules.ai.vendors import endpoint_of, load_vendors, vendor_endpoints

KIMI_MODELS = ["kimi-k3.1-pro", "kimi-k3.1-pro-highspeed", "kimi-k3"]
GLM_MODELS = ["glm-5.3", "glm-5.3-flash", "glm-5.3-flashx"]
QWEN_MODELS = ["qwen4-max", "qwen3.7-plus", "qwen3.8-flash"]
MINIMAX_MODELS = ["MiniMax-M3.1-Flash", "MiniMax-M3"]
SILICONFLOW_MODELS = [
    "deepseek-ai/DeepSeek-V4.1-Flash",
    "deepseek-ai/DeepSeek-V4-Pro",
    "zai-org/GLM-5.3",
]

# The preset table of hub_components/ai.md, "Vendor presets", row by row:
# vendor, endpoint, base URL, prices from, plan, models.
PRESET_TABLE = [
    (
        "deepseek",
        "api",
        "https://api.deepseek.com",
        "deepseek",
        False,
        ["deepseek-flash", "deepseek-v4-pro"],
    ),
    (
        "kimi",
        "api_cn",
        "https://api.moonshot.cn/v1",
        "moonshotai-cn",
        False,
        KIMI_MODELS,
    ),
    (
        "kimi",
        "api_global",
        "https://api.moonshot.ai/v1",
        "moonshotai",
        False,
        KIMI_MODELS,
    ),
    (
        "zhipu",
        "api_cn",
        "https://open.bigmodel.cn/api/paas/v4",
        "zhipuai",
        False,
        GLM_MODELS,
    ),
    (
        "zhipu",
        "plan_cn",
        "https://open.bigmodel.cn/api/coding/paas/v4",
        "zhipuai",
        True,
        GLM_MODELS,
    ),
    ("zhipu", "api_global", "https://api.z.ai/api/paas/v4", "zai", False, GLM_MODELS),
    (
        "zhipu",
        "plan_global",
        "https://api.z.ai/api/coding/paas/v4",
        "zai",
        True,
        GLM_MODELS,
    ),
    (
        "qwen",
        "api_cn",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "alibaba-cn",
        False,
        QWEN_MODELS,
    ),
    (
        "qwen",
        "api_global",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "alibaba",
        False,
        QWEN_MODELS,
    ),
    (
        "qwen",
        "plan_cn",
        "https://coding.dashscope.aliyuncs.com/v1",
        "alibaba-cn",
        True,
        QWEN_MODELS,
    ),
    (
        "qwen",
        "plan_global",
        "https://coding-intl.dashscope.aliyuncs.com/v1",
        "alibaba",
        True,
        QWEN_MODELS,
    ),
    (
        "doubao",
        "api",
        "https://ark.cn-beijing.volces.com/api/v3",
        "volcengine",
        False,
        [
            "doubao-seed-2-1-pro-260915",
            "doubao-seed-2-1-lite-260915",
            "doubao-seed-2-1-turbo-260628",
        ],
    ),
    (
        "doubao",
        "plan",
        "https://ark.cn-beijing.volces.com/api/coding/v3",
        "volcengine",
        True,
        ["ark-code-latest"],
    ),
    (
        "minimax",
        "api_cn",
        "https://api.minimax.cn/v1",
        "minimax-cn",
        False,
        MINIMAX_MODELS,
    ),
    (
        "minimax",
        "api_global",
        "https://api.minimax.io/v1",
        "minimax",
        False,
        MINIMAX_MODELS,
    ),
    (
        "openrouter",
        "api",
        "https://openrouter.ai/api/v1",
        "openrouter",
        False,
        ["openai/gpt-6.2-sol", "anthropic/claude-fable-5.2"],
    ),
    (
        "siliconflow",
        "api_cn",
        "https://api.siliconflow.cn/v1",
        "siliconflow-cn",
        False,
        SILICONFLOW_MODELS,
    ),
    (
        "siliconflow",
        "api_global",
        "https://api.siliconflow.com/v1",
        "siliconflow",
        False,
        SILICONFLOW_MODELS,
    ),
    (
        "mistral",
        "api",
        "https://api.mistral.ai/v1",
        "mistral",
        False,
        ["mistral-large-latest", "mistral-small-2603"],
    ),
    (
        "xai",
        "api",
        "https://api.x.ai/v1",
        "xai",
        False,
        ["grok-4.7", "grok-4.6", "grok-4.3"],
    ),
]


def endpoints() -> list:
    return vendor_endpoints(load_vendors())


def test_the_shipped_table_holds_exactly_the_preset_rows_in_order():
    rows = [
        (
            vendor["id"],
            endpoint["id"],
            endpoint["base_url"],
            endpoint["price_provider"],
            endpoint["is_plan"],
            endpoint["models"],
        )
        for vendor in load_vendors()
        for endpoint in vendor["endpoints"]
    ]

    assert rows == PRESET_TABLE


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.moonshot.cn/v1",
        "https://api.moonshot.cn/v1/",
        "HTTPS://API.Moonshot.CN/v1",
    ],
)
def test_a_base_url_names_its_endpoint_with_or_without_a_slash_and_in_any_case(
    base_url,
):
    endpoint = endpoint_of("custom", base_url, endpoints())

    assert (endpoint.vendor, endpoint.id, endpoint.price_provider) == (
        "kimi",
        "api_cn",
        "moonshotai-cn",
    )
    assert endpoint.is_preset is True


def test_a_path_in_another_case_is_another_address():
    assert endpoint_of("custom", "https://api.moonshot.cn/V1", endpoints()) is None


@pytest.mark.parametrize(
    "kind, price_provider",
    [("anthropic", "anthropic"), ("openai", "openai"), ("gemini", "google")],
)
def test_a_kinds_provider_with_no_base_url_takes_its_kinds_vendor(kind, price_provider):
    endpoint = endpoint_of(kind, "", endpoints())

    assert (endpoint.vendor, endpoint.price_provider) == (kind, price_provider)
    assert endpoint.is_preset is False


def test_any_other_base_url_is_custom():
    assert endpoint_of("custom", "", endpoints()) is None
    assert endpoint_of("custom", "https://relay.example/v1", endpoints()) is None
    assert endpoint_of("openai", "https://relay.example/v1", endpoints()) is None


def test_a_plan_endpoint_is_marked():
    plan = endpoint_of("custom", "https://api.z.ai/api/coding/paas/v4", endpoints())
    api = endpoint_of("custom", "https://api.z.ai/api/paas/v4", endpoints())

    assert (plan.is_plan, api.is_plan) == (True, False)
