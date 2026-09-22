"""Joining and leaving: the link, the join body, the binding file, the leave.

The link rides base64url so it holds no character a shell splits or a URL
escapes; a link made for a client is refused here. The join posts the seven
fields and stores the binding with every address the link carried; a file
missing any field but the address list is an unbound agent, so a 0.2.x
file expires by itself and a 0.3.0 file reads as a binding with no list.
The candidates of a connection round, the hub's name in a stored address's
scheme and port, and the two notes a running agent writes onto the file
are pinned here too. Leaving posts the binding back and deletes the file
whether or not the hub answered. The one HTTP call each way is answered by
the test; nothing here reaches a network.
"""

import json
import os
import stat

import pytest

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import AGENT_ROLE, AGENT_SOFTWARE_PREFIX, PROTOCOL
from neutrino_agent.core.enrollment import (
    default_source_address,
    parse_link,
    resolve_hub_address,
)
from neutrino_agent.exceptions import (
    EnrollmentError,
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
)
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.detect import platform_tuple
from tests.conftest import BINDING_ID, BINDING_TOKEN, MACHINE_ID, bind, link_for

GATEWAY_URL = "https://hub.lan:8443"
FINGERPRINT = "ab" * 32
LINK = link_for(
    {"urls": [GATEWAY_URL], "token": "ticket", "fp": FINGERPRINT, "role": "agent"}
)


class _IdentifiedPlatform(AgentPlatform):
    """A platform that knows its machine id and nothing else."""

    os_name = "linux"

    def __init__(self, machine_id: str):
        self._machine_id = machine_id

    def read_machine_id(self) -> str:
        return self._machine_id


def answer_join(monkeypatch, *, reply=None, error=None, errors=None):
    """What the hub says to the join posts this walk makes.

    Args:
        monkeypatch: The test's patcher.
        reply: The JSON the hub answers with.
        error: Raised instead of answering.
        errors: Raised in turn, one per post, before ``reply`` answers.

    Returns:
        The list the posts land in, as ``(gateway_url, payload)``.
    """
    posted = []
    pending = list(errors or [])

    def join(self, payload):
        posted.append((self._gateway_url, dict(payload)))
        if pending:
            raise pending.pop(0)
        if error is not None:
            raise error
        if reply is None:
            return {"id": BINDING_ID, "token": BINDING_TOKEN}
        return dict(reply)

    monkeypatch.setattr(enrollment.BindingHttpClient, "join", join)
    return posted


def answer_leave(monkeypatch, *, error=None):
    """What the hub says to the leave post.

    Args:
        monkeypatch: The test's patcher.
        error: Raised instead of answering.

    Returns:
        The list the posts land in, as ``(gateway_url, id, token)``.
    """
    posted = []

    def leave(self, binding_id, token):
        posted.append((self._gateway_url, binding_id, token))
        if error is not None:
            raise error

    monkeypatch.setattr(enrollment.BindingHttpClient, "leave", leave)
    return posted


# --- the link ---


def test_a_link_round_trips():
    urls, token, fingerprint, role = parse_link(
        link_for(
            {
                "urls": ["https://192.168.100.1:8443"],
                "token": "abc123",
                "fp": "AB" * 32,
                "role": "agent",
            }
        )
    )
    assert urls == ["https://192.168.100.1:8443"]
    assert token == "abc123"
    assert fingerprint == "ab" * 32
    assert role == "agent"


def test_every_address_the_hub_answers_on_is_carried():
    """A hub serves more than one network, and only one of its addresses is
    on the network of the machine being enrolled, which the hub cannot know
    and the person pasting the link should not have to."""
    urls, token, _, _ = parse_link(
        link_for(
            {
                "urls": ["https://192.168.8.1:8443", "https://10.0.0.1:8443"],
                "token": "abc123",
                "role": "agent",
            }
        )
    )

    assert urls == ["https://192.168.8.1:8443", "https://10.0.0.1:8443"]
    assert token == "abc123"


def test_the_link_needs_no_quoting():
    """The whole point of the format: nothing a shell splits."""
    link = link_for(
        {"urls": ["https://192.168.100.1:8443"], "token": "t" * 24, "role": "agent"}
    )
    assert not any(character in link for character in "?&%#;|<> '\"")


def test_the_bare_payload_is_accepted():
    link = link_for({"urls": ["https://hub:8443"], "token": "t", "role": "agent"})
    payload = link.split("/")[-1]
    urls, token, _, _ = parse_link(payload)
    assert urls == ["https://hub:8443"]
    assert token == "t"


def test_a_trailing_slash_is_trimmed():
    urls, _, _, _ = parse_link(
        link_for({"urls": ["https://hub:8443/"], "token": "t", "role": "agent"})
    )
    assert urls == ["https://hub:8443"]


def test_a_link_without_a_fingerprint_carries_an_empty_one():
    _, _, fingerprint, _ = parse_link(
        link_for({"urls": ["http://hub:8080"], "token": "t", "role": "agent"})
    )
    assert fingerprint == ""


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not a link at all",
        "neutrino://enroll/not-base64!!",
        "neutrino://enroll?url=http%3A%2F%2Fold&token=style",
    ],
)
def test_what_is_not_a_link_is_refused(text):
    with pytest.raises(EnrollmentError):
        parse_link(text)


def test_a_payload_missing_its_half_is_refused():
    with pytest.raises(EnrollmentError):
        parse_link(link_for({"urls": ["https://hub"], "role": "agent"}))
    with pytest.raises(EnrollmentError):
        parse_link(link_for({"token": "t", "role": "agent"}))


@pytest.mark.parametrize("payload_role", ["client", "hub", "", None])
def test_a_link_made_for_another_role_is_refused(payload_role):
    payload = {"urls": ["https://hub:8443"], "token": "t"}
    if payload_role is not None:
        payload["role"] = payload_role

    with pytest.raises(EnrollmentError) as refused:
        parse_link(link_for(payload))

    assert refused.value.code == "link_not_for_agent"
    assert refused.value.params == {"role": payload_role or ""}


# --- the join ---


def test_the_join_body_carries_the_seven_fields(monkeypatch):
    monkeypatch.setattr(enrollment.socket, "gethostname", lambda: "box")

    payload = enrollment.join_payload("ticket", platform=_IdentifiedPlatform("abc123"))

    assert payload == {
        "ticket": "ticket",
        "role": AGENT_ROLE,
        "protocol": PROTOCOL,
        "machine_id": "abc123",
        "name": "box",
        "software": f"{AGENT_SOFTWARE_PREFIX}{AGENT_VERSION}",
        "platform": platform_tuple(),
    }
    assert payload["role"] == "agent"
    assert payload["software"].startswith("neutrino_agent/")


def test_a_platform_without_a_machine_id_sends_an_empty_one():
    payload = enrollment.join_payload("ticket", platform=AgentPlatform())

    assert payload["machine_id"] == ""


def test_a_join_posts_the_body_and_stores_the_binding(config_path, monkeypatch):
    posted = answer_join(monkeypatch, reply={"id": "3f9c", "token": "secret"})

    stored = enrollment.enroll(LINK, platform=_IdentifiedPlatform("abc123"))

    ((url, payload),) = posted
    assert url == GATEWAY_URL
    assert set(payload) == {
        "ticket",
        "role",
        "protocol",
        "machine_id",
        "name",
        "software",
        "platform",
    }
    assert payload["ticket"] == "ticket"
    assert stored == {
        "gateway_url": GATEWAY_URL,
        "gateway_urls": [GATEWAY_URL],
        "id": "3f9c",
        "token": "secret",
        "fingerprint": FINGERPRINT,
        "machine_id": "abc123",
    }
    assert json.loads(config_path.read_text()) == stored
    assert enrollment.load_binding() == stored
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600


def test_a_join_replaces_whatever_the_file_held(config_path, monkeypatch):
    """A 0.2.x file is not merged into: the binding is the five fields."""
    config_path.write_text(json.dumps({"device_id": "old", "gateway_url": "x"}))
    answer_join(monkeypatch)

    enrollment.enroll(LINK, platform=_IdentifiedPlatform(""))

    assert set(json.loads(config_path.read_text())) == set(enrollment.BINDING_KEYS)


def test_the_next_address_is_tried_when_one_is_unreachable(monkeypatch):
    link = link_for(
        {
            "urls": ["https://10.0.0.1:8443", GATEWAY_URL],
            "token": "ticket",
            "fp": FINGERPRINT,
            "role": "agent",
        }
    )
    posted = answer_join(monkeypatch, errors=[GatewayUnreachable("no route")])

    stored = enrollment.enroll(link, platform=_IdentifiedPlatform(""))

    assert [url for url, _ in posted] == ["https://10.0.0.1:8443", GATEWAY_URL]
    assert stored["gateway_url"] == GATEWAY_URL


def test_no_address_answering_is_refused_naming_them_all(monkeypatch):
    answer_join(monkeypatch, error=GatewayUnreachable("no route"))

    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(LINK, platform=_IdentifiedPlatform(""))

    assert GATEWAY_URL in str(refused.value)
    assert "no route" in str(refused.value)
    assert not enrollment.is_bound()


@pytest.mark.parametrize(
    "code, params",
    [
        ("ticket_spent", {}),
        ("protocol_too_new", {"peer": 2, "hub": 1, "min": 1}),
        ("protocol_too_old", {"peer": 1, "hub": 3, "min": 2}),
        ("role_mismatch", {}),
    ],
)
def test_a_hubs_refusal_carries_its_code_and_params(monkeypatch, code, params):
    """The hub said no with a code; the other addresses reach the same hub,
    so none is tried, and nothing is stored."""
    link = link_for(
        {
            "urls": [GATEWAY_URL, "https://10.0.0.1:8443"],
            "token": "ticket",
            "fp": FINGERPRINT,
            "role": "agent",
        }
    )
    posted = answer_join(
        monkeypatch, error=GatewayRefusedDetail(code=code, params=params)
    )

    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(link, platform=_IdentifiedPlatform(""))

    assert refused.value.code == code
    assert refused.value.params == params
    assert len(posted) == 1
    assert not enrollment.is_bound()


def test_a_certificate_off_the_pin_aborts_the_join(monkeypatch):
    answer_join(monkeypatch, error=GatewayUntrusted("off the pin"))

    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(LINK, platform=_IdentifiedPlatform(""))

    assert f"{GATEWAY_URL} presented a certificate this link does not pin" in str(
        refused.value
    )
    assert refused.value.code == ""
    assert not enrollment.is_bound()


@pytest.mark.parametrize(
    "reply", [{}, {"id": "x"}, {"token": "t"}, {"id": "", "token": "t"}]
)
def test_a_reply_naming_no_binding_is_refused(monkeypatch, reply):
    answer_join(monkeypatch, reply=reply)

    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(LINK, platform=_IdentifiedPlatform(""))

    assert "no binding" in str(refused.value)
    assert not enrollment.is_bound()


# --- the binding file ---


def test_a_complete_file_is_a_binding(config_path):
    bind(config_path, url=GATEWAY_URL, fingerprint=FINGERPRINT, urls=[GATEWAY_URL])

    assert enrollment.is_bound()
    assert enrollment.load_binding() == {
        "gateway_url": GATEWAY_URL,
        "gateway_urls": [GATEWAY_URL],
        "id": BINDING_ID,
        "token": BINDING_TOKEN,
        "fingerprint": FINGERPRINT,
        "machine_id": MACHINE_ID,
    }


def test_a_file_without_the_address_list_is_a_binding_with_none(config_path):
    """A 0.3.0 file names the one address that answered its join."""
    bind(config_path, url=GATEWAY_URL)

    binding = enrollment.load_binding()

    assert binding["gateway_url"] == GATEWAY_URL
    assert binding["gateway_urls"] == []
    assert enrollment.stored_urls(binding) == [GATEWAY_URL]
    assert enrollment.candidate_urls(binding) == [GATEWAY_URL]


@pytest.mark.parametrize(
    "missing",
    sorted(key for key in enrollment.BINDING_KEYS if key != "gateway_urls"),
)
def test_a_file_missing_any_field_is_unbound(config_path, missing):
    bind(config_path)
    held = json.loads(config_path.read_text())
    del held[missing]
    config_path.write_text(json.dumps(held))

    assert enrollment.load_binding() == {}
    assert not enrollment.is_bound()


@pytest.mark.parametrize("blank", ["gateway_url", "id", "token"])
def test_a_file_naming_no_hub_id_or_token_is_unbound(config_path, blank):
    bind(config_path)
    held = json.loads(config_path.read_text())
    held[blank] = ""
    config_path.write_text(json.dumps(held))

    assert enrollment.load_binding() == {}


def test_an_empty_fingerprint_and_machine_id_still_bind(config_path):
    bind(config_path, fingerprint="")
    held = json.loads(config_path.read_text())
    held["machine_id"] = ""
    config_path.write_text(json.dumps(held))

    assert enrollment.load_binding()["machine_id"] == ""
    assert enrollment.is_bound()


def test_a_0_2_file_reads_as_unbound(config_path):
    config_path.write_text(
        json.dumps(
            {
                "gateway_url": GATEWAY_URL,
                "token": "tok",
                "fingerprint": FINGERPRINT,
                "device_id": "abc",
            }
        )
    )

    assert enrollment.load_binding() == {}


@pytest.mark.parametrize("text", ["", "not json", "[]", "42"])
def test_an_unreadable_file_is_unbound(config_path, text):
    config_path.write_text(text)

    assert enrollment.load_binding() == {}


def test_no_file_is_unbound_and_stamps_zero():
    assert enrollment.load_binding() == {}
    assert enrollment.config_stamp() == 0


# --- the addresses, and the round's order ---

LAN_URL = "https://192.0.2.1:8443"
OVERLAY_URL = "https://100.64.0.1:8443"
NAME_URL = "https://192.0.2.9:8443"


def test_the_list_is_kept_clean_and_in_the_hubs_order():
    assert enrollment.clean_urls([LAN_URL + "/", " ", OVERLAY_URL, LAN_URL, 7, ""]) == [
        LAN_URL,
        OVERLAY_URL,
        "7",
    ]
    assert enrollment.clean_urls("not a list") == []
    assert enrollment.clean_urls(None) == []


def test_a_round_is_the_name_then_the_last_answer_then_the_rest():
    binding = {"gateway_url": OVERLAY_URL, "gateway_urls": [LAN_URL, OVERLAY_URL]}

    assert enrollment.candidate_urls(binding, NAME_URL) == [
        NAME_URL,
        OVERLAY_URL,
        LAN_URL,
    ]
    assert enrollment.candidate_urls(binding) == [OVERLAY_URL, LAN_URL]
    assert enrollment.candidate_urls(binding, LAN_URL) == [LAN_URL, OVERLAY_URL]
    assert enrollment.stored_urls(binding) == [LAN_URL, OVERLAY_URL]


def test_the_name_takes_the_stored_addresss_scheme_and_port(monkeypatch):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "192.0.2.9")

    assert enrollment.hub_name_url(LAN_URL) == NAME_URL
    assert enrollment.hub_name_url("http://192.0.2.1:9") == "http://192.0.2.9:9"
    assert enrollment.hub_name_url("https://hub.lan") == "https://192.0.2.9:443"


def test_a_name_that_does_not_resolve_is_no_candidate(monkeypatch):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "")

    assert enrollment.hub_name_url(LAN_URL) == ""


def test_the_name_is_looked_up_as_ipv4_only(monkeypatch):
    asked = []

    def getaddrinfo(host, port, family=0, kind=0, *rest):
        asked.append((host, family, kind))
        return [(family, kind, 6, "", ("192.0.2.9", 0))]

    monkeypatch.setattr(enrollment.socket, "getaddrinfo", getaddrinfo)

    assert resolve_hub_address() == "192.0.2.9"
    assert asked == [
        (
            "hub.neutrino.internal",
            enrollment.socket.AF_INET,
            enrollment.socket.SOCK_STREAM,
        )
    ]


def test_a_lookup_that_fails_resolves_to_nothing(monkeypatch):
    def getaddrinfo(*args):
        raise enrollment.socket.gaierror("no such name")

    monkeypatch.setattr(enrollment.socket, "getaddrinfo", getaddrinfo)

    assert resolve_hub_address() == ""


def test_the_route_to_the_hub_is_read_off_the_first_literal():
    """A loopback address is routed on every machine; a name is skipped."""
    assert default_source_address(["https://hub.lan:8443", "http://127.0.0.1:9"]) == (
        "127.0.0.1"
    )
    assert default_source_address(["https://hub.lan:8443"]) == ""
    assert default_source_address([]) == ""


def test_the_notes_write_onto_a_stored_binding(config_path):
    bind(config_path, url=LAN_URL)

    enrollment.note_urls([LAN_URL, OVERLAY_URL + "/", OVERLAY_URL])
    enrollment.note_url(OVERLAY_URL)

    binding = enrollment.load_binding()
    assert binding["gateway_url"] == OVERLAY_URL
    assert binding["gateway_urls"] == [LAN_URL, OVERLAY_URL]
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600


def test_a_note_on_no_binding_writes_nothing(config_path):
    enrollment.note_url(OVERLAY_URL)
    assert not config_path.exists()

    config_path.write_text(json.dumps({"device_id": "old", "gateway_url": "x"}))
    enrollment.note_urls([LAN_URL])

    assert json.loads(config_path.read_text()) == {
        "device_id": "old",
        "gateway_url": "x",
    }


# --- leaving ---


def test_unbind_posts_the_binding_back_and_deletes_the_file(config_path, monkeypatch):
    bind(config_path, url=GATEWAY_URL, fingerprint=FINGERPRINT)
    posted = answer_leave(monkeypatch)

    assert enrollment.unbind() == {}

    assert posted == [(GATEWAY_URL, BINDING_ID, BINDING_TOKEN)]
    assert not config_path.exists()
    assert not enrollment.is_bound()


@pytest.mark.parametrize(
    "error, code",
    [
        (GatewayUnreachable("no route"), "hub_unreachable"),
        (GatewayUntrusted("off the pin"), "hub_untrusted"),
        (GatewayRefusedDetail(code="binding_unknown", params={}), "binding_unknown"),
    ],
)
def test_unbind_deletes_the_file_and_says_when_the_hub_was_not_told(
    config_path, monkeypatch, error, code
):
    bind(config_path)
    answer_leave(monkeypatch, error=error)

    outcome = enrollment.unbind()

    assert outcome["code"] == code
    assert not config_path.exists()


def test_unbind_with_no_binding_posts_nothing(config_path, monkeypatch):
    posted = answer_leave(monkeypatch)

    assert enrollment.unbind() == {}

    assert posted == []
    assert not config_path.exists()


def test_removing_a_binding_that_is_not_there_is_no_error(config_path):
    enrollment.remove_binding()

    assert not config_path.exists()
