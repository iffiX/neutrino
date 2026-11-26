"""The daily read of the models.dev price list: when it reads, and what it asks to keep."""

from neutrino_hub.modules.ai.model_prices import PRICES_FAILED, kept_providers
from neutrino_hub.modules.ai.vendors import load_vendors
from neutrino_hub.web.model_price_sampler import PanelModelPriceSampler


def test_a_read_keeps_the_providers_the_hub_prices_with():
    asked = {}

    def refresh(*, providers):
        asked["providers"] = providers
        return "written"

    sampler = PanelModelPriceSampler(refresh=refresh, fetched_at=lambda: "")

    assert sampler.read_once() == "written"
    assert asked["providers"] == kept_providers(load_vendors())


def test_a_read_that_raises_is_a_failed_read_the_loop_outlives():
    def refresh(*, providers):
        raise RuntimeError("boom")

    assert PanelModelPriceSampler(refresh=refresh).read_once() == PRICES_FAILED


def test_the_first_read_waits_out_what_is_left_of_the_day():
    stale = PanelModelPriceSampler(fetched_at=lambda: "2000-01-01T00:00:00Z")
    unknown = PanelModelPriceSampler(fetched_at=lambda: "")

    assert stale.first_wait_s() == 0
    assert unknown.first_wait_s() == 0
