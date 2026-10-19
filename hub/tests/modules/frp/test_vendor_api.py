"""The vendors' clients against recorded answers.

Every request names the hub in its User-Agent; SakuraFrp's refused key is
HTTP 500 with ``{"code": 401}``; OpenFrp's 401 is a login that expired, and
a new ``Authorization`` in any answer's header is handed on.
"""

import json
import urllib.parse

import pytest

from neutrino_hub.exceptions import FrpVendorError
from neutrino_hub.modules.frp.constants import (
    FRP_OPENFRP_API,
    FRP_SAKURAFRP_API,
    FRP_USER_AGENT,
    FRP_VERSION,
)
from neutrino_hub.modules.frp.vendor_api import OpenFrpApi, SakuraFrpApi
from tests.modules.frp.fake_vendors import (
    OPENFRP_AUTHORIZATION,
    SAKURAFRP_CONFIG,
    SAKURAFRP_KEY,
    FakeVendors,
    answer,
    openfrp_answer,
)


@pytest.fixture
def vendors():
    return FakeVendors()


def test_every_request_names_the_hub(vendors):
    sakura = SakuraFrpApi(SAKURAFRP_KEY, transport=vendors)
    openfrp = OpenFrpApi(OPENFRP_AUTHORIZATION, transport=vendors)

    sakura.user_info()
    sakura.tunnels()
    sakura.nodes()
    sakura.tunnel_config("114514")
    openfrp.user_proxies()
    openfrp.node_list()
    openfrp.node_conf("41")
    openfrp.request_login("key")
    openfrp.poll_login("uuid")

    assert len(vendors.requests) == 9
    assert all(
        headers["User-Agent"] == FRP_USER_AGENT for _, _, headers, _ in vendors.requests
    )
    assert FRP_USER_AGENT.startswith("Neutrino/")


def test_sakurafrp_takes_the_key_as_a_bearer_token(vendors):
    SakuraFrpApi(SAKURAFRP_KEY, transport=vendors).tunnels()

    _, url, headers, _ = vendors.requests[0]
    assert url == f"{FRP_SAKURAFRP_API}/tunnels"
    assert headers["Authorization"] == f"Bearer {SAKURAFRP_KEY}"


def test_sakurafrp_asks_a_tunnels_config_for_the_carried_frpc(vendors):
    text = SakuraFrpApi(SAKURAFRP_KEY, transport=vendors).tunnel_config("114514")

    method, url, _, body = vendors.requests[0]
    assert (method, url) == ("POST", f"{FRP_SAKURAFRP_API}/tunnel/config")
    assert urllib.parse.parse_qs(body.decode()) == {
        "query": ["114514"],
        "frpc": [FRP_VERSION],
    }
    assert text == SAKURAFRP_CONFIG


def test_a_key_sakurafrp_refuses_is_frp_credential_refused(vendors):
    vendors.answers[("GET", f"{FRP_SAKURAFRP_API}/user/info")] = answer(
        {"code": 401, "msg": "访问密钥无效"}, status=500
    )

    with pytest.raises(FrpVendorError) as refused:
        SakuraFrpApi("wrong", transport=vendors).user_info()

    assert refused.value.code == "frp_credential_refused"
    assert refused.value.params == {"title": "SakuraFrp"}


def test_another_sakurafrp_error_names_its_status_and_message(vendors):
    vendors.answers[("GET", f"{FRP_SAKURAFRP_API}/tunnels")] = answer(
        {"code": 403, "msg": "无权访问"}, status=403
    )

    with pytest.raises(FrpVendorError) as refused:
        SakuraFrpApi(SAKURAFRP_KEY, transport=vendors).tunnels()

    assert refused.value.code == "frp_vendor_unreachable"
    assert refused.value.params == {
        "title": "SakuraFrp",
        "detail": "HTTP 403: 无权访问",
    }


def test_a_vendor_not_reached_is_frp_vendor_unreachable(vendors):
    vendors.answers.clear()

    with pytest.raises(FrpVendorError) as refused:
        OpenFrpApi(OPENFRP_AUTHORIZATION, transport=vendors).node_list()

    assert refused.value.code == "frp_vendor_unreachable"
    assert refused.value.params["title"] == "OpenFrp"


def test_openfrp_takes_the_authorization_as_the_header_itself(vendors):
    OpenFrpApi(OPENFRP_AUTHORIZATION, transport=vendors).user_proxies()

    method, url, headers, body = vendors.requests[0]
    assert (method, url) == ("POST", f"{FRP_OPENFRP_API}/getUserProxies")
    assert headers["Authorization"] == OPENFRP_AUTHORIZATION
    assert json.loads(body) == {}


def test_openfrp_asks_a_nodes_config_by_its_number(vendors):
    OpenFrpApi(OPENFRP_AUTHORIZATION, transport=vendors).node_conf("41")

    assert json.loads(vendors.requests[0][3]) == {"node_id": 41}


def test_openfrps_401_is_frp_not_signed_in(vendors):
    vendors.answers[("POST", f"{FRP_OPENFRP_API}/getUserProxies")] = answer(
        {"flag": False, "msg": "未登录"}, status=401
    )

    with pytest.raises(FrpVendorError) as refused:
        OpenFrpApi(OPENFRP_AUTHORIZATION, transport=vendors).user_proxies()

    assert refused.value.code == "frp_not_signed_in"


def test_a_rotated_authorization_is_handed_on_and_used_from_then(vendors):
    rotated = []
    vendors.answers[("POST", f"{FRP_OPENFRP_API}/getUserProxies")] = openfrp_answer(
        {"total": 0, "list": []}, headers={"authorization": "OPENFRPsecond"}
    )
    api = OpenFrpApi(
        OPENFRP_AUTHORIZATION, on_rotated=rotated.append, transport=vendors
    )

    api.user_proxies()
    api.user_proxies()
    api.node_list()

    assert rotated == ["OPENFRPsecond"]
    assert [headers["Authorization"] for _, _, headers, _ in vendors.requests] == [
        OPENFRP_AUTHORIZATION,
        "OPENFRPsecond",
        "OPENFRPsecond",
    ]


def test_an_answer_whose_flag_is_off_is_frp_vendor_unreachable(vendors):
    vendors.answers[("POST", f"{FRP_OPENFRP_API}/getNodeList")] = answer(
        {"data": None, "flag": False, "msg": "节点列表获取失败"}
    )

    with pytest.raises(FrpVendorError) as refused:
        OpenFrpApi(OPENFRP_AUTHORIZATION, transport=vendors).node_list()

    assert refused.value.params["detail"] == "节点列表获取失败"


def test_the_login_asks_with_the_public_key_and_reads_the_url(vendors):
    url, request_uuid = OpenFrpApi(transport=vendors).request_login("v6rrxUpQ3-M1=")

    assert json.loads(vendors.requests[0][3]) == {"public_key": "v6rrxUpQ3-M1="}
    assert url.startswith("https://console.openfrp.net/usercenter?argoaccess=")
    assert request_uuid == "9a23ed00-07e6-4f11-bcfd-b0216e3bcacf"


def test_the_poll_is_pending_on_204_and_answers_the_sealed_data_on_200(vendors):
    api = OpenFrpApi(transport=vendors)
    pending = api.poll_login("9a23")
    vendors.answers[("GET", "https://access.openfrp.net/argoAccess/pollLogin")] = (
        answer(
            {
                "code": 200,
                "data": {"authorization_data": "CqWR", "request_uuid": "9a23"},
            },
            headers={"x-request-public-key": "I9E_WWIG="},
        )
    )

    assert pending is None
    assert api.poll_login("9a23") == ("CqWR", "I9E_WWIG=")
    assert vendors.requests[0][1].endswith("pollLogin?request_uuid=9a23")
