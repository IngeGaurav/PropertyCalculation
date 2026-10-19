import pytest
from fastapi.testclient import TestClient

from app.config import settings
from main import app

client = TestClient(app, raise_server_exceptions=False)

GOOD = {"T": 423.15, "P": 29411.81, "components": ["methane", "ethane"], "zs": [0.5, 0.5]}
WET = {"T": 350, "P": 101325, "components": ["7732-18-5", "hexane"], "zs": [0.5, 0.5]}
STEAM = {"T": 500, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5]}
ALL = ["cp_calc", "density_calc", "enthalpy_calc", "mw_calc", "vf_calc"]


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


def test_enthalpy_mass_matches_molar():
    d = client.post("/enthalpy_calc", json=GOOD).json()["data"]
    assert d["H_mix_mass"] == pytest.approx(d["H_mix_molar"] / 23.05575 * 1000, rel=1e-3)


def test_std_enthalpy():
    r = client.post("/std_enthalpy_calc", json={"components": ["methane", "ethane"], "zs": [0.5, 0.5]})
    assert r.status_code == 200
    assert r.json()["data"]["H_mix_std_molar"] == pytest.approx(-79450, rel=0.01)


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


def test_triphase_accepts_water_by_name_or_cas():
    a = client.post("/triphase_vf_calc", json=WET).json()["data"]
    b = client.post("/triphase_vf_calc", json={**WET, "components": ["water", "hexane"]}).json()["data"]
    assert a == b


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
    ({"components": ["methane", "METHANE"]}, "components"),
    ({"T": "hot"}, "T"),
])
def test_validation_errors(patch, field):
    r = client.post("/cp_calc", json={**GOOD, **patch})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "validation_error"
    assert body["error"]["details"] and body["request_id"]


def test_unknown_component():
    r = client.post("/cp_calc", json={**GOOD, "components": ["methane", "notachemical"]})
    body = r.json()
    assert r.status_code == 422 and body["error"]["code"] == "unknown_component"
    assert body["error"]["details"] == {"component": "notachemical"}


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
