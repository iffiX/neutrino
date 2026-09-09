"""The web service: a published link opens in the platform's browser."""

from neutrino_client.services.web import WebServiceHandler
from tests.conftest import SERVICES, FakeClientPlatform


def test_open_hands_the_url_to_the_platform():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform)

    assert handler.act(entries=SERVICES, body={"id": "svc_wiki"}) == {}

    assert platform.opened_urls == ["http://w/"]
    assert handler.state() == {}


def test_an_unknown_or_bare_entry_opens_nothing():
    platform = FakeClientPlatform()
    handler = WebServiceHandler(platform=platform)
    bare = [{"id": "svc_bare", "type": "web", "payload": {}}]

    assert handler.act(entries=SERVICES, body={"id": "nothing"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert handler.act(entries=bare, body={"id": "svc_bare"}) == {
        "code": "unknown_request",
        "params": {},
    }
    assert platform.opened_urls == []
