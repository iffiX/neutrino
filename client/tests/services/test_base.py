"""The handler contract: typed entries by hub and id, the service key, the
honest default answers, and the code a hub that did not answer reads as."""

import pytest

from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)
from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
    hub_of_key,
    service_key,
)
from tests.conftest import SERVICES


def test_an_entry_is_found_by_type_hub_and_id():
    assert find_entry(SERVICES, "web", "h1", "svc_wiki")["title"] == "Wiki"
    assert find_entry(SERVICES, "web", "h2", "svc_wiki") is None
    assert find_entry(SERVICES, "port", "h1", "svc_wiki") is None
    assert find_entry(SERVICES, "web", "h1", "nothing") is None
    assert find_entry(None, "web", "h1", "svc_wiki") is None
    assert find_entry(["not an entry"], "web", "h1", "svc_wiki") is None


def test_the_same_id_on_two_hubs_is_two_entries():
    assert find_entry(SERVICES, "port", "h1", "svc_tcp")["payload"]["host"] == "h"
    assert find_entry(SERVICES, "port", "h2", "svc_tcp")["payload"]["host"] == "office"


def test_the_service_key_is_the_hub_then_the_id():
    assert service_key("h1", "svc_tcp") == "h1/svc_tcp"
    assert service_key("h2", "svc_tcp") != service_key("h1", "svc_tcp")
    assert hub_of_key("h1/svc_tcp") == "h1"
    assert hub_of_key("h1/") == "h1"


def test_the_base_handler_refuses_and_holds_nothing():
    handler = ServiceTypeHandler()

    assert handler.act(entries=[], body={}) == {"code": "unknown_request", "params": {}}
    assert handler.state() == {}
    assert handler.start() is None
    assert handler.release() is None
    assert handler.release_hub("h1") is None


@pytest.mark.parametrize(
    "error, refusal",
    [
        (
            GatewayRefusedDetail(code="rdp_not_shared", params={"id": "x"}),
            {"code": "rdp_not_shared", "params": {"id": "x"}},
        ),
        (GatewayUntrusted("pin"), {"code": "hub_untrusted", "params": {}}),
        (
            GatewayUnreachable("down"),
            {"code": "hub_unreachable", "params": {"detail": "down"}},
        ),
        (
            RuntimeError("no hub"),
            {"code": "hub_refused", "params": {"detail": "RuntimeError"}},
        ),
    ],
)
def test_a_hub_that_did_not_answer_reads_as_its_code(error, refusal):
    assert channel_refusal(error) == refusal
