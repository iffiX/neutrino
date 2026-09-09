"""The handler contract: typed entries by id, the honest default answers."""

from neutrino_client.services.base import ServiceTypeHandler, find_entry
from tests.conftest import SERVICES


def test_an_entry_is_found_by_type_and_id():
    assert find_entry(SERVICES, "web", "svc_wiki")["title"] == "Wiki"
    assert find_entry(SERVICES, "port", "svc_wiki") is None
    assert find_entry(SERVICES, "web", "nothing") is None
    assert find_entry(None, "web", "svc_wiki") is None
    assert find_entry(["not an entry"], "web", "svc_wiki") is None


def test_the_base_handler_refuses_and_holds_nothing():
    handler = ServiceTypeHandler()

    assert handler.act(entries=[], body={}) == {"code": "unknown_request", "params": {}}
    assert handler.state() == {}
    assert handler.start() is None
    assert handler.release() is None
