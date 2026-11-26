"""The forwarder's rule: a ``?tkn=`` that verifies setting the login cookie under ``cookie_name`` and redirecting to the same path without the token; a token that does not verify, a request with neither and a forged cookie answering 401; a good cookie passed on."""

import time

from neutrino_agent.modules.comfyui.config import cookie_key
from neutrino_agent.modules.comfyui.forwarder import (
    ComfyuiForwarderHooks,
    without_token,
)
from neutrino_agent.modules.shared.http_forward import (
    ForwardRequest,
    is_login_valid,
    mint_login,
)


def _request(*, target_query=None, token="", cookies=(), taken=True, path="/"):
    headers = tuple(("cookie", cookie) for cookie in cookies)
    return ForwardRequest(
        method="GET",
        path=path,
        query=target_query or {},
        headers=headers,
        token=token,
        take_token=lambda **_kwargs: taken,
    )


RECORD = {
    "secret": "s" * 32,
    "cookie_name": "neutrino_0123456789ab",
    "upstream_port": 1,
}


def test_a_token_that_verifies_sets_the_cookie_and_redirects_without_it():
    now = 1_800_000_000
    hooks = ComfyuiForwarderHooks(clock=lambda: now)
    decision = hooks.admit(
        _request(
            path="/view",
            target_query={"tkn": ["t"], "filename": ["a.png"]},
            token="t",
        ),
        RECORD,
    )
    assert decision.status == 302
    headers = dict(decision.headers)
    assert headers["Location"] == "/view?filename=a.png"
    name, _, rest = headers["Set-Cookie"].partition("=")
    value = rest.split(";", 1)[0]
    assert name == "neutrino_0123456789ab"
    assert "HttpOnly" in rest and "SameSite=Lax" in rest
    assert f"Max-Age={7 * 24 * 3600}" in rest
    key = cookie_key("s" * 32)
    assert is_login_valid(value, key, now + 7 * 24 * 3600 - 1)
    assert not is_login_valid(value, key, now + 7 * 24 * 3600 + 1)


def test_a_bad_token_neither_and_a_forged_cookie_answer_401_and_a_good_cookie_passes():
    now = time.time()
    hooks = ComfyuiForwarderHooks(clock=lambda: now)
    assert hooks.admit(_request(token="t", taken=False), RECORD).status == 401
    assert hooks.admit(_request(), RECORD).status == 401
    forged = mint_login(b"k" * 32, int(now) + 60)
    assert (
        hooks.admit(
            _request(cookies=(f"neutrino_0123456789ab={forged}",)), RECORD
        ).status
        == 401
    )
    good = mint_login(cookie_key("s" * 32), int(now) + 60)
    assert (
        hooks.admit(_request(cookies=(f"neutrino_0123456789ab={good}",)), RECORD).status
        == 0
    )
    assert without_token("", {"tkn": ["x"]}) == "/"
