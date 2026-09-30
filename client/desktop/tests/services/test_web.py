"""The web service: a published link of one hub opens in the platform's browser."""

from neutrino_client.services.web import WebServiceHandler
from tests.conftest import SERVICES, FakeClientPlatform


def test_open_hands_the_url_to_the_platform():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform)

    assert handler.act(entries=SERVICES, body={"hub_id": "h1", "id": "svc_wiki"}) == {}
    assert handler.act(entries=SERVICES, body={"hub_id": "h2", "id": "svc_docs"}) == {}

    assert platform.opened_urls == ["http://w/", "http://docs/"]
    assert handler.state() == {}


def test_an_unknown_or_bare_entry_opens_nothing():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform)
    bare = [{"id": "svc_bare", "type": "web", "hub_id": "h1", "payload": {}}]

    assert handler.act(entries=SERVICES, body={"hub_id": "h1", "id": "nothing"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=SERVICES, body={"hub_id": "h2", "id": "svc_wiki"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=SERVICES, body={"id": "svc_wiki"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=bare, body={"hub_id": "h1", "id": "svc_bare"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert platform.opened_urls == []
