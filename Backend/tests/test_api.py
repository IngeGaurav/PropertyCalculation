import pytest
from fastapi.testclient import TestClient

from app.config import settings
from main import app

client = TestClient(app, raise_server_exceptions=False)

GOOD = {"T": 423.15, "P": 29411.81, "components": ["74-82-8", "74-84-0"], "zs": [0.5, 0.5]}
WET = {"T": 350, "P": 101325, "components": ["7732-18-5", "110-54-3"], "zs": [0.5, 0.5]}
STEAM = {"T": 500, "P": 101325, "components": ["7732-18-5", "110-54-3"], "zs": [0.5, 0.5]}
ALL = ["cp_calc", "density_calc", "mw_calc", "vf_calc"]


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


@pytest.mark.parametrize("name", ALL)
def test_basic_endpoints_succeed(name):
    r = client.post(f"/{name}", json=GOOD)
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "success" and body["units"] and body["meta"]["request_id"]


def test_cp_single_phase_has_null_other_phase():
    d = client.post("/cp_calc", json=GOOD).json()["data"]
    assert d["Vapor_fraction"] == 1 and d["Cp_liquid"] is None
    assert d["Cp_mix"] == pytest.approx(d["Cp_vapor"])


def test_mw_in_g_per_mol():
    d = client.post("/mw_calc", json=GOOD).json()["data"]
    assert d["MW_avg"] == pytest.approx(23.056, rel=1e-3)






def test_zs_are_normalised_and_flagged():
    r = client.post("/vf_calc", json={**GOOD, "zs": [1, 1]})
    assert r.status_code == 200 and r.json()["meta"]["zs_normalized"] is True


def test_triphase_endpoints_liquid_state():
    cp = client.post("/triphase_cp_calc", json=WET).json()["data"]
    assert cp["Cp_vapor"] is None and cp["Cp_aqueous"] > 0 and cp["Cp_organic"] > 0
    vf = client.post("/triphase_vf_calc", json=WET).json()["data"]
    assert vf["vapor_fraction"] + vf["aqueous_fraction"] + vf["organic_fraction"] == pytest.approx(1)
    mw = client.post("/triphase_mw_calc", json=WET).json()["data"]
    assert mw["MW_aqueous"] == pytest.approx(18.015, rel=1e-3)


def test_triphase_vapor_state_no_crash():
    # Used to raise UnboundLocalError when there was no liquid.
    for ep in ("triphase_cp_calc", "triphase_mw_calc", "triphase_vf_calc"):
        r = client.post(f"/{ep}", json=STEAM)
        assert r.status_code == 200, (ep, r.json())




def test_triphase_requires_water():
    r = client.post("/triphase_vf_calc", json=GOOD)
    assert r.status_code == 422 and r.json()["error"]["code"] == "water_required"


@pytest.mark.parametrize("patch,field", [
    ({"zs": [0.5]}, "body"),
    ({"zs": [-1, 2]}, "body"),
    ({"zs": [0, 0]}, "body"),
    ({"T": -5}, "T"),
    ({"P": 0}, "P"),
    ({"components": []}, "components"),
    ({"components": ["74-82-8", "74-82-8"]}, "components"),
    ({"T": "hot"}, "T"),
])
def test_validation_errors(patch, field):
    r = client.post("/cp_calc", json={**GOOD, **patch})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "validation_error"
    assert body["error"]["details"] and body["request_id"]


def test_unknown_component():
    r = client.post("/cp_calc", json={**GOOD, "components": ["74-82-8", "9999-99-9"]})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "unknown_component"
    assert body["error"]["details"] == {"component": "9999-99-9"}


def test_404_and_405_use_error_envelope():
    assert client.get("/nope").json()["error"]["code"] == "not_found"
    assert client.get("/cp_calc").json()["error"]["code"] == "method_not_allowed"


def test_malformed_json():
    r = client.post("/cp_calc", content="{bad", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["status"] == "error"


def test_request_id_echoed():
    r = client.post("/vf_calc", json=GOOD, headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123" and r.json()["meta"]["request_id"] == "abc123"


def test_api_key_enforced(monkeypatch):
    monkeypatch.setattr(settings.__class__, "api_key", "secret", raising=False)
    object.__setattr__(settings, "api_key", "secret")
    try:
        assert client.post("/vf_calc", json=GOOD).status_code == 401
        assert client.post("/vf_calc", json=GOOD, headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.post("/vf_calc", json=GOOD, headers={"X-API-Key": "secret"}).status_code == 200
        assert client.get("/health").status_code == 200  # health stays open
    finally:
        object.__setattr__(settings, "api_key", None)


def test_unexpected_error_is_masked(monkeypatch):
    from app import thermo_service
    def boom(_): raise RuntimeError("secret internals")
    monkeypatch.setattr(thermo_service, "flash", boom)
    r = client.post("/vf_calc", json=GOOD)
    assert r.status_code == 500 and "secret internals" not in r.text
    assert r.json()["error"]["code"] == "internal_error"




def test_many_components_accepted():
    comps = ["74-82-8", "74-84-0", "74-98-6", "106-97-8", "109-66-0", "110-54-3", "7732-18-5", "71-43-2",
             "108-88-3", "74-85-1", "115-07-1", "1333-74-0", "124-38-9"] * 1
    r = client.post("/vf_calc", json={"T": 400, "P": 200000, "components": comps, "zs": [1] * len(comps)})
    assert r.status_code == 200, r.json()
