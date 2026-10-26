"""Joining and leaving: the link, the join, the binding file, the leave.

The link is compact JSON compressed with zlib in unpadded base64url, so it
holds no character a shell splits or a URL escapes; it carries the hub's
key, and a link made for a client is refused here. The join goes through a
transport the test plays: one ``join`` command with the link's key, a
fresh static key of this agent's, the addresses in order and the seven
fields, its answer's ``binding_id`` and ``token`` stored with every address
the link carried. A file missing any field but the address list, or
holding a key that is not 64 hex characters, is an unbound agent. The
addresses of a round, the hub's name on a stored address's port, and the
two notes a running agent writes onto the file are pinned here too.
Leaving sends ``leave`` with the binding's keys and psk and deletes the
file whether or not the hub answered.
"""

import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import zlib

import pytest

import neutrino_agent.core.enrollment as enrollment
from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import AGENT_ROLE, AGENT_SOFTWARE_PREFIX, PROTOCOL
from neutrino_agent.core.enrollment import (
    default_source_address,
    parse_link,
    resolve_hub_address,
)
from neutrino_agent.exceptions import EnrollmentError
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.platforms.detect import platform_tuple
from tests.conftest import (
    BINDING_ID,
    BINDING_TOKEN,
    HUB_KEY,
    MACHINE_ID,
    PRIVATE_KEY,
    bind,
    link_for,
)
from tests.transport.fake_transport import FakeTransport, one_shot_for

GATEWAY_URL = "tcp://192.0.2.5:8443"
LINK = link_for(
    {"urls": [GATEWAY_URL], "token": "ticket", "key": HUB_KEY, "role": "agent"}
)


class _IdentifiedPlatform(AgentPlatform):
    """A platform that knows its machine id and nothing else."""

    os_name = "linux"

    def __init__(self, machine_id: str):
        self._machine_id = machine_id

    def read_machine_id(self) -> str:
        return self._machine_id


@pytest.fixture
def fake():
    transport = FakeTransport()
    yield transport
    transport.close()


def joined(fake, answer=None):
    """A transport that answers the join as the hub would."""
    fake.answers["join"] = (
        answer if answer is not None else {"binding_id": "3f9c", "token": "secret"}
    )
    return one_shot_for(fake)


# --- the link ---


def agent_link(**payload) -> str:
    return link_for(dict({"token": "t", "key": HUB_KEY, "role": "agent"}, **payload))


def test_a_link_round_trips():
    urls, token, key, role = parse_link(
        link_for(
            {
                "urls": ["tcp://192.168.100.1:8443"],
                "token": "abc123",
                "key": "AB" * 32,
                "role": "agent",
            }
        )
    )
    assert urls == ["tcp://192.168.100.1:8443"]
    assert token == "abc123"
    assert key == "ab" * 32
    assert role == "agent"


def test_every_address_the_hub_answers_on_is_carried():
    urls, _, _, _ = parse_link(
        agent_link(urls=["tcp://192.168.8.1:8443", "tcp://10.0.0.1:8443"])
    )

    assert urls == ["tcp://192.168.8.1:8443", "tcp://10.0.0.1:8443"]


def test_the_link_needs_no_quoting():
    link = agent_link(urls=["tcp://192.168.100.1:8443"], token="t" * 24)
    assert not any(character in link for character in "?&%#;|<> '\"")


def test_the_bare_payload_is_accepted_and_a_trailing_slash_trimmed():
    payload = agent_link(urls=["tcp://hub:8443/"]).split("/")[-1]

    urls, token, _, _ = parse_link(payload)

    assert urls == ["tcp://hub:8443"]
    assert token == "t"


@pytest.mark.parametrize("key", [None, "", "ab" * 31, "fp-not-hex" * 7])
def test_a_link_without_a_hub_key_is_refused(key):
    payload = {"urls": ["tcp://hub:8443"], "token": "t", "role": "agent"}
    if key is not None:
        payload["key"] = key

    with pytest.raises(EnrollmentError) as refused:
        parse_link(link_for(payload))

    assert "hub key" in str(refused.value)


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


def test_a_payload_that_does_not_inflate_or_parse_is_unreadable():
    body = json.dumps({"urls": ["tcp://hub:8443"], "token": "t", "role": "agent"})
    plain = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    garbled = base64.urlsafe_b64encode(zlib.compress(b"{not json", 9)).decode()

    for text in (plain, garbled.rstrip("=")):
        with pytest.raises(EnrollmentError) as refused:
            parse_link("neutrino://enroll/" + text)
        assert "not an enrollment link" in str(refused.value)
        assert refused.value.code == ""


def test_a_payload_missing_its_half_is_refused():
    with pytest.raises(EnrollmentError):
        parse_link(link_for({"urls": ["tcp://hub"], "key": HUB_KEY, "role": "agent"}))
    with pytest.raises(EnrollmentError):
        parse_link(link_for({"token": "t", "key": HUB_KEY, "role": "agent"}))


@pytest.mark.parametrize("payload_role", ["client", "hub", "", None])
def test_a_link_made_for_another_role_is_refused(payload_role):
    payload = {"urls": ["tcp://hub:8443"], "token": "t", "key": HUB_KEY}
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


def test_a_platform_without_a_machine_id_sends_an_empty_one():
    payload = enrollment.join_payload("ticket", platform=AgentPlatform())

    assert payload["machine_id"] == ""


def test_a_join_goes_through_the_transport_and_stores_the_binding(
    fake, config_path, monkeypatch
):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "10.9.9.9")
    link = link_for(
        {
            "urls": [GATEWAY_URL, "tcp://10.0.0.1:8443"],
            "token": "ticket",
            "key": HUB_KEY,
            "role": "agent",
        }
    )

    stored = enrollment.enroll(
        link, platform=_IdentifiedPlatform("abc123"), transport=joined(fake)
    )

    (join,) = fake.commands
    assert join["command"] == "join"
    assert join["hub_key"] == HUB_KEY
    assert join["private_key"] == stored["private_key"]
    assert join["addresses"] == [
        "tcp://10.9.9.9:8443",
        GATEWAY_URL,
        "tcp://10.0.0.1:8443",
    ]
    assert {key: join[key] for key in ("ticket", "role", "protocol", "machine_id")} == {
        "ticket": "ticket",
        "role": "agent",
        "protocol": PROTOCOL,
        "machine_id": "abc123",
    }
    assert set(join) >= {"name", "software", "platform"}
    assert stored == {
        "gateway_url": GATEWAY_URL,
        "gateway_urls": [GATEWAY_URL, "tcp://10.0.0.1:8443"],
        "id": "3f9c",
        "token": "secret",
        "hub_key": HUB_KEY,
        "private_key": stored["private_key"],
        "machine_id": "abc123",
    }
    assert enrollment.is_key(stored["private_key"])
    assert enrollment.load_binding() == stored
    assert stat.S_IMODE(os.stat(config_path).st_mode) == 0o600


def test_each_join_makes_a_new_static_key(fake, config_path):
    first = enrollment.enroll(
        LINK, platform=_IdentifiedPlatform(""), transport=joined(fake)
    )
    second = enrollment.enroll(
        LINK, platform=_IdentifiedPlatform(""), transport=joined(fake)
    )

    assert first["private_key"] != second["private_key"]


def test_a_join_replaces_whatever_the_file_held(fake, config_path):
    config_path.write_text(json.dumps({"device_id": "old", "gateway_url": "x"}))

    enrollment.enroll(LINK, platform=_IdentifiedPlatform(""), transport=joined(fake))

    assert set(json.loads(config_path.read_text())) == set(enrollment.BINDING_KEYS)


@pytest.mark.parametrize(
    "code, params",
    [
        ("ticket_spent", {}),
        ("protocol_too_new", {"peer": 5, "hub": 4, "min": 4}),
        ("protocol_too_old", {"peer": 3, "hub": 4, "min": 4}),
        ("role_mismatch", {}),
        ("hub_untrusted", {}),
        ("hub_unreachable", {"detail": "no route"}),
    ],
)
def test_a_refused_join_carries_its_code_and_stores_nothing(
    fake, config_path, code, params
):
    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(
            LINK,
            platform=_IdentifiedPlatform(""),
            transport=joined(fake, {"code": code, "params": params}),
        )

    assert refused.value.code == code
    assert refused.value.params == params
    assert not enrollment.is_bound()


@pytest.mark.parametrize(
    "answer",
    [{}, {"binding_id": "x"}, {"token": "t"}, {"binding_id": "", "token": "t"}],
)
def test_an_answer_naming_no_binding_is_refused(fake, config_path, answer):
    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(
            LINK, platform=_IdentifiedPlatform(""), transport=joined(fake, answer)
        )

    assert "no binding" in str(refused.value)
    assert not enrollment.is_bound()


def test_a_transport_that_cannot_start_is_the_joins_error(config_path):
    def refuse():
        raise OSError("no transport here")

    with pytest.raises(EnrollmentError) as refused:
        enrollment.enroll(LINK, platform=_IdentifiedPlatform(""), transport=refuse)

    assert "could not start" in str(refused.value)
    assert not enrollment.is_bound()


# --- the binding file ---


def test_a_complete_file_is_a_binding(config_path):
    bind(config_path, url=GATEWAY_URL, urls=[GATEWAY_URL])

    assert enrollment.is_bound()
    assert enrollment.load_binding() == {
        "gateway_url": GATEWAY_URL,
        "gateway_urls": [GATEWAY_URL],
        "id": BINDING_ID,
        "token": BINDING_TOKEN,
        "hub_key": HUB_KEY,
        "private_key": PRIVATE_KEY,
        "machine_id": MACHINE_ID,
    }


def test_a_file_without_the_address_list_is_a_binding_with_none(config_path):
    bind(config_path, url=GATEWAY_URL)

    binding = enrollment.load_binding()

    assert binding["gateway_urls"] == []
    assert enrollment.stored_urls(binding) == [GATEWAY_URL]


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


@pytest.mark.parametrize("key", ["hub_key", "private_key"])
def test_a_key_that_is_not_64_hex_is_unbound(config_path, key):
    bind(config_path)
    held = json.loads(config_path.read_text())
    held[key] = "not a key"
    config_path.write_text(json.dumps(held))

    assert enrollment.load_binding() == {}


def test_a_binding_of_0_5_is_no_binding_but_a_legacy_one(config_path):
    config_path.write_text(
        json.dumps(
            {
                "gateway_url": "https://hub.lan:8443",
                "gateway_urls": ["https://hub.lan:8443"],
                "id": "d",
                "token": "t",
                "fingerprint": "ff" * 32,
                "machine_id": "m",
            }
        )
    )

    assert enrollment.load_binding() == {}
    assert enrollment.load_legacy_binding()["fingerprint"] == "ff" * 32


@pytest.mark.parametrize("text", ["", "not json", "[]", "42"])
def test_an_unreadable_file_is_unbound(config_path, text):
    config_path.write_text(text)

    assert enrollment.load_binding() == {}
    assert enrollment.load_legacy_binding() == {}


def test_no_file_is_unbound_and_stamps_zero():
    assert enrollment.load_binding() == {}
    assert enrollment.config_stamp() == 0


def test_the_psk_is_the_tokens_sha256():
    assert enrollment.psk_of("tok") == hashlib.sha256(b"tok").hexdigest()


def test_the_dial_fields_carry_the_keys_the_psk_and_the_addresses(config_path):
    bind(config_path, url=GATEWAY_URL)

    assert enrollment.dial_fields(enrollment.load_binding()) == {
        "hub_key": HUB_KEY,
        "private_key": PRIVATE_KEY,
        "psk": hashlib.sha256(BINDING_TOKEN.encode()).hexdigest(),
        "role": "agent",
        "protocol": PROTOCOL,
        "addresses": [GATEWAY_URL],
    }


# --- the addresses, and the round's order ---

LAN_URL = "tcp://192.0.2.1:8443"
OVERLAY_URL = "tcp://100.64.0.1:8443"
NAME_URL = "tcp://192.0.2.9:8443"


def test_the_list_is_kept_clean_and_in_the_hubs_order():
    assert enrollment.clean_urls([LAN_URL + "/", " ", OVERLAY_URL, LAN_URL, 7, ""]) == [
        LAN_URL,
        OVERLAY_URL,
        "7",
    ]
    assert enrollment.clean_urls("not a list") == []


def test_every_round_is_the_name_then_the_list_from_the_top(monkeypatch):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "192.0.2.9")
    binding = {"gateway_url": OVERLAY_URL, "gateway_urls": [LAN_URL, OVERLAY_URL]}

    assert enrollment.dial_addresses(binding) == [NAME_URL, LAN_URL, OVERLAY_URL]


def test_the_name_takes_the_stored_addresss_port(monkeypatch):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "192.0.2.9")

    assert enrollment.hub_name_url(LAN_URL) == NAME_URL
    assert enrollment.hub_name_url("tcp://192.0.2.1:9") == "tcp://192.0.2.9:9"
    assert enrollment.hub_name_url("tcp://hub.lan") == ""


def test_a_name_that_does_not_resolve_is_no_address(monkeypatch):
    binding = {"gateway_url": LAN_URL, "gateway_urls": [LAN_URL]}

    assert enrollment.hub_name_url(LAN_URL) == ""
    assert enrollment.dial_addresses(binding) == [LAN_URL]


def test_an_address_of_another_scheme_is_not_dialled():
    binding = {"gateway_url": LAN_URL, "gateway_urls": ["https://x:1", "udp://y:2"]}

    assert enrollment.dial_addresses(binding) == [LAN_URL]


@pytest.mark.parametrize(
    "address, url",
    [
        ("tcp://192.0.2.1:8443", "tcp://192.0.2.1:8443"),
        ("192.0.2.1:8443", "tcp://192.0.2.1:8443"),
        ("[fd00::1]:8443", "tcp://[fd00::1]:8443"),
        ("", ""),
    ],
)
def test_a_session_open_address_is_kept_as_a_tcp_url(address, url):
    assert enrollment.address_url(address) == url


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
    assert default_source_address(["tcp://hub.lan:8443", "tcp://127.0.0.1:9"]) == (
        "127.0.0.1"
    )
    assert default_source_address(["tcp://hub.lan:8443"]) == ""
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


def test_unbind_sends_leave_with_the_binding_and_deletes_the_file(fake, config_path):
    bind(config_path, url=GATEWAY_URL)

    assert enrollment.unbind(transport=one_shot_for(fake)) == {}

    (leave,) = fake.commands
    assert leave["command"] == "leave"
    assert leave["hub_key"] == HUB_KEY
    assert leave["private_key"] == PRIVATE_KEY
    assert leave["psk"] == hashlib.sha256(BINDING_TOKEN.encode()).hexdigest()
    assert leave["addresses"] == [GATEWAY_URL]
    assert not config_path.exists()


@pytest.mark.parametrize(
    "code", ["hub_unreachable", "hub_untrusted", "binding_unknown"]
)
def test_unbind_deletes_the_file_and_says_when_the_hub_was_not_told(
    fake, config_path, code
):
    bind(config_path)
    fake.answers["leave"] = {"code": code, "params": {}}

    outcome = enrollment.unbind(transport=one_shot_for(fake))

    assert outcome["code"] == code
    assert not config_path.exists()


def test_unbind_with_no_transport_still_deletes_the_file(config_path):
    bind(config_path)

    def refuse():
        raise OSError("no transport")

    outcome = enrollment.unbind(transport=refuse)

    assert outcome["code"] == "hub_unreachable"
    assert not config_path.exists()


def test_unbind_with_no_binding_sends_nothing(fake, config_path):
    assert enrollment.unbind(transport=one_shot_for(fake)) == {}

    assert fake.commands == []


def test_removing_a_binding_that_is_not_there_is_no_error(config_path):
    enrollment.remove_binding()

    assert not config_path.exists()


def test_the_binding_file_is_agent_json_under_the_platforms_data_root():
    # Read in a fresh interpreter: the suite points the binding at tmp_path.
    probe = (
        "from neutrino_agent.core import enrollment\n"
        "from neutrino_agent.platforms.detect import detect_platform\n"
        "print(enrollment.AGENT_CONFIG_PATH)\n"
        "print(detect_platform().agent_data_dir())\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        capture_output=True,
        text=True,
        timeout=60,
    )

    path, data_dir = result.stdout.split()
    assert path == os.path.join(data_dir, "agent.json")
    assert path == "/etc/neutrino/agent/agent.json"
