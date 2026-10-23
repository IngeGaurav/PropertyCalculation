"""Tests for the new EOS (Peng-Robinson, three-phase flash) endpoint /eos_stream_calc."""
import time

import pytest
from fastapi.testclient import TestClient

from app import eos_service
from main import app

client = TestClient(app, raise_server_exceptions=False)
URL = "/eos_stream_calc"

WH = {"components": ["water", "hexane"], "zs": [0.5, 0.5]}  # water / hexane


def post(T, P, **body):
    return client.post(URL, json={"T": T, "P": P, **body})


def data(T, P, **body):
    r = post(T, P, **body)
    assert r.status_code == 200, r.json()
    return r.json()["data"]


def test_envelope_matches_the_existing_endpoints():
    j = post(300, 101325, **WH).json()
    assert j["status"] == "success"
    assert set(j) == {"status", "data", "units", "meta"}
    assert j["meta"]["request_id"] and j["meta"]["zs_normalized"] is False
    assert j["units"]["MW"] == "g/mol" and j["units"]["rho_mass"] == "kg/m^3"


def test_vapor_only_gas():
    d = data(423.15, 29411.81, components=["methane", "ethane"], zs=[0.5, 0.5])
    assert d["case"] == "vapor-only" and d["V"] == pytest.approx(1.0)
    assert d["vapor"] and d["aqueous"] is None and d["organic"] is None
    assert d["mixture"]["MW"] == pytest.approx(23.056, rel=1e-3)
    assert d["mixture"]["Cp"] == pytest.approx(55.19, rel=5e-3)  # real-gas value, close to the ideal-gas 55.17
    assert d["mixture"]["rho_mass"] == pytest.approx(0.1928, rel=1e-2)


def test_two_liquid_phases_water_hexane_300K():
    d = data(300, 101325, **WH)
    assert d["case"].startswith("two-phase liquid-liquid") and d["vapor"] is None
    assert d["aqueous"]["MW"] == pytest.approx(18.015, rel=1e-3)
    assert d["organic"]["MW"] > 60  # hexane-rich
    assert d["aqueous"]["beta"] + d["organic"]["beta"] == pytest.approx(1.0)
    assert d["aqueous"]["rho_mass"] > d["organic"]["rho_mass"]


def test_vapor_plus_aqueous_water_hexane_351K():
    # Hexane boils at 342 K, so at 351 K most of the mixture is vapor (the existing VLE endpoint reports all liquid here).
    d = data(351, 101325, **WH)
    assert d["case"].startswith("two-phase vapor-liquid")
    assert 0.7 < d["V"] < 0.95 and d["aqueous"] is not None and d["organic"] is None
    assert d["V"] + d["L"] == pytest.approx(1.0)


def test_all_vapor_water_hexane_357K():
    d = data(357, 101325, **WH)
    assert d["case"] == "vapor-only"


def test_phase_fractions_sum_to_one():
    for T in (300, 340, 351, 400):
        d = data(T, 101325, **WH)
        total = sum(d[k]["beta"] for k in ("vapor", "aqueous", "organic") if d[k])
        assert total == pytest.approx(1.0, abs=1e-6)


def test_names_and_cas_give_identical_results():
    a = data(300, 101325, **WH)
    b = data(300, 101325, components=["7732-18-5", "110-54-3"], zs=[0.5, 0.5])
    assert a == b


def test_component_order_does_not_matter():
    a = data(300, 101325, **WH)
    b = data(300, 101325, components=["hexane", "water"], zs=[0.5, 0.5])
    assert a["aqueous"]["MW"] == pytest.approx(b["aqueous"]["MW"])
    assert a["organic"]["beta"] == pytest.approx(b["organic"]["beta"])


def test_zero_fraction_components_are_skipped_with_identical_result():
    base = data(300, 101325, **WH)
    padded = data(300, 101325, components=["water", "propane", "hexane", "ethane"], zs=[0.5, 0, 0.5, 0])
    assert base["n_components_used"] == 2 and padded["n_components_used"] == 2
    assert padded["mixture"] == pytest.approx(base["mixture"])


def test_unnormalised_fractions_are_rescaled_and_flagged():
    r = post(300, 101325, components=["water", "hexane"], zs=[1, 1])
    assert r.status_code == 200 and r.json()["meta"]["zs_normalized"] is True


def test_same_chemical_given_twice_is_merged():
    a = data(300, 101325, **WH)
    b = data(300, 101325, components=["water", "7732-18-5", "hexane"], zs=[0.25, 0.25, 0.5])
    assert b["aqueous"]["beta"] == pytest.approx(a["aqueous"]["beta"])


def test_single_component():
    d = data(300, 101325, components=["water"], zs=[1])
    assert d["case"].startswith("liquid-only") and d["aqueous"] is not None


def test_water_not_required():
    d = data(300, 101325, components=["benzene", "toluene"], zs=[0.5, 0.5])
    assert d["aqueous"] is None and d["organic"] is not None


@pytest.mark.parametrize("patch", [
    {"zs": [0.5]},
    {"zs": [-1, 2]},
    {"T": -5},
    {"P": 0},
    {"components": ["water", "Water"]},
])
def test_validation_errors_use_the_standard_envelope(patch):
    body = {"T": 300, "P": 101325, **WH, **patch}
    r = client.post(URL, json=body)
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "validation_error" and j["request_id"]


def test_unknown_component():
    r = post(300, 101325, components=["water", "notachemical"], zs=[0.5, 0.5])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unknown_component"
    assert r.json()["error"]["details"] == {"component": "notachemical"}


def test_zero_fraction_unknown_component_is_still_rejected():
    r = post(300, 101325, components=["water", "notachemical"], zs=[1, 0])
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_component"


def test_cache_is_reused_and_bounded():
    data(300, 101325, **WH)
    size = eos_service.cache_size()
    t = time.time()
    data(320, 101325, **WH)  # same component set, different T: no rebuild
    assert time.time() - t < 2.0
    assert eos_service.cache_size() == size <= eos_service.CACHE_MAX_ENTRIES


def test_flash_failure_is_a_422_not_a_500(monkeypatch):
    class Boom:
        def flash(self, **kw):
            raise RuntimeError("did not converge")

    entry = eos_service._get_entry(tuple(sorted(["7732-18-5", "110-54-3"])))
    monkeypatch.setattr(entry, "flasher", Boom())
    r = post(300, 101325, **WH)
    assert r.status_code == 422 and r.json()["error"]["code"] == "flash_failed"
    assert "did not converge" in r.json()["error"]["message"]


def test_existing_endpoints_are_unchanged():
    r = client.post("/cp_calc", json={"T": 357, "P": 101325, **WH})
    d = r.json()["data"]
    assert r.status_code == 200 and d["Vapor_fraction"] == pytest.approx(0.2262146, rel=1e-5)


# --- the lead's own 48-component stream (24 of the mole fractions are 0) -------------------------
LEAD_COMPONENTS = ["7732-18-5", "7783-06-4", "630-08-0", "124-38-9", "1333-74-0", "74-82-8", "74-86-2", "74-85-1", "74-84-0", "74-99-7", "115-07-1", "74-98-6", "689-97-4", "106-99-0", "115-11-7", "106-98-9", "624-64-6", "106-97-8", "75-28-5", "591-93-5", "78-79-5", "542-92-7", "142-29-0", "563-46-2", "109-66-0", "109-67-1", "78-78-4", "287-92-3", "71-43-2", "693-89-0", "513-81-5", "592-41-6", "96-37-7", "110-54-3", "110-82-7", "26519-91-5", "762-62-9", "592-76-7", "108-88-3", "28823-41-8", "628-92-2", "142-82-5", "100-42-5", "106-42-3", "100-41-4", "91-20-3", "124-11-8", "111-84-2"]
LEAD_ZS = [0.269748141292868, 0, 6.03528399403273E-04, 1.00736830732534E-04, 0.258141212597959, 4.00793391652614E-02, 1.75879627063473E-03, 0.24503640666357, 0.171763402033696, 1.0092770950848E-04, 4.22577374255925E-03, 5.02687004252303E-04, 1.0010170263719E-04, 3.31625297005193E-03, 0, 3.0130220697407E-04, 2.0057870262539E-04, 9.0440145713386E-04, 0, 1.00843087685205E-04, 0, 5.02652336375593E-04, 3.01816734349797E-04, 0, 0, 1.00722963353751E-04, 0, 0, 1.60794644088582E-03, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2.00921736353394E-04, 0, 0, 0, 1.00569467602784E-04, 0, 0, 0, 0, 2.00938483526172E-04]


def test_lead_48_component_stream_matches_the_reference_script():
    """Reference values come from running the lead's script unchanged (vapor-only, MW 18.846, Cp 45.539)."""
    started = time.time()
    r = post(425, 169612.911830353, components=LEAD_COMPONENTS, zs=LEAD_ZS)
    elapsed = time.time() - started
    assert r.status_code == 200, r.json()
    d = r.json()["data"]
    assert d["case"] == "vapor-only" and d["n_components_used"] == 24
    assert d["mixture"]["MW"] == pytest.approx(18.8463, rel=1e-4)
    assert d["mixture"]["Cp"] == pytest.approx(45.5393, rel=1e-4)
    assert d["mixture"]["rho_mass"] == pytest.approx(0.90771, rel=1e-4)
    assert elapsed < 25, f"too slow: {elapsed:.1f}s (the script itself needs 17-34 s without skipping zero fractions)"
