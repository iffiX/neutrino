"""The Origin belt: a foreign Origin on a write is refused before its route."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.web.origin_guard import OriginGuardMiddleware


@pytest.fixture()
def client():
    app = FastAPI()
    app.add_middleware(OriginGuardMiddleware)

    @app.post("/api/thing")
    def write():
        return {"written": True}

    @app.get("/api/thing")
    def read():
        return {"read": True}

    return TestClient(app)


def test_a_write_without_an_origin_passes(client):
    assert client.post("/api/thing").json() == {"written": True}


def test_a_same_origin_write_passes(client):
    response = client.post("/api/thing", headers={"origin": "http://testserver"})
    assert response.status_code == 200


def test_a_foreign_origin_write_is_refused_with_the_code(client):
    response = client.post("/api/thing", headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "origin_refused", "params": {}}}


def test_a_null_origin_write_is_refused(client):
    assert client.post("/api/thing", headers={"origin": "null"}).status_code == 403


def test_the_same_host_on_another_port_is_foreign(client):
    response = client.post("/api/thing", headers={"origin": "http://testserver:8081"})
    assert response.status_code == 403


def test_the_default_port_spelled_out_still_matches(client):
    response = client.post("/api/thing", headers={"origin": "http://testserver:80"})
    assert response.status_code == 200


def test_a_read_with_a_foreign_origin_is_left_alone(client):
    response = client.get("/api/thing", headers={"origin": "http://evil.example"})
    assert response.json() == {"read": True}


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_every_write_method_is_guarded(client, method):
    response = getattr(client, method)(
        "/api/thing", headers={"origin": "http://evil.example"}
    )
    assert response.status_code == 403
