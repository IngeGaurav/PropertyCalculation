"""Tests for the Enthalpy API, POST /eos_enthalpy_calc (enthalpy at an inlet and an outlet condition, heat duty).

Expected values come from running the lead's reference script unchanged (see docs): the API must reproduce them.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import eos_service
from main import app

client = TestClient(app, raise_server_exceptions=False)
URL = "/eos_enthalpy_calc"

LEAD_COMPONENTS = ["7732-18-5", "7783-06-4", "630-08-0", "124-38-9", "1333-74-0", "74-82-8", "74-86-2", "74-85-1", "74-84-0", "74-99-7", "115-07-1", "74-98-6", "689-97-4", "106-99-0", "115-11-7", "106-98-9", "624-64-6", "106-97-8", "75-28-5", "591-93-5", "78-79-5", "542-92-7", "142-29-0", "563-46-2", "109-66-0", "109-67-1", "78-78-4", "287-92-3", "71-43-2", "693-89-0", "513-81-5", "592-41-6", "96-37-7", "110-54-3", "110-82-7", "26519-91-5", "762-62-9", "592-76-7", "108-88-3", "28823-41-8", "628-92-2", "142-82-5", "100-42-5", "106-42-3", "100-41-4", "91-20-3", "124-11-8", "111-84-2"]
LEAD_MOL_PERCENT = [0, 0, 0, 0, 0, 0.02, 0.43, 60.6, 37.94, 0.01, 0.72, 0.14, 0, 0.05, 0, 0.05, 0, 0.04, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

LEAD = dict(T_in=300, P_in=254920, T_out=368, P_out=254720, components=LEAD_COMPONENTS, zs=LEAD_MOL_PERCENT)
WATER = dict(T_in=300, P_in=101325, T_out=400, P_out=101325, components=["water"], zs=[1])
WATER_HEXANE = dict(T_in=300, P_in=101325, T_out=380, P_out=101325, components=["water", "hexane"], zs=[0.5, 0.5])


def call(**body):
    return client.post(URL, json=body)


def data(**body):
    r = call(**body)
    assert r.status_code == 200, r.json()
    return r.json()["data"]


# ------------------------------------------------ agreement with the reference script
def test_lead_stream_matches_reference_script():
    d = data(**LEAD)
    assert d["n_components_used"] == 10 and d["ethylene_ethane_kij_override"] is True
    assert d["inlet"]["vapor_fraction"] == pytest.approx(1.0) and d["outlet"]["vapor_fraction"] == pytest.approx(1.0)
    assert d["inlet"]["molecular_weight"] == pytest.approx(28.970639174, rel=1e-9)
    assert d["inlet"]["enthalpy_molar"] == pytest.approx(-0.042410868756199, rel=1e-6)
    assert d["inlet"]["enthalpy_mass"] == pytest.approx(-1.463925890674206, rel=1e-6)
    assert d["outlet"]["enthalpy_molar"] == pytest.approx(3.439141539211891, rel=1e-6)
    assert d["outlet"]["enthalpy_mass"] == pytest.approx(118.71127587334642, rel=1e-6)
    assert d["duty"]["heat_duty_molar"] == pytest.approx(3.4815524079680897, rel=1e-6)
    assert d["duty"]["sp_duty"] == pytest.approx(120.17520176402063, rel=1e-6)


def test_pure_component_uses_the_pure_flash_and_matches_reference():
    d = data(T_in=300, P_in=254920, T_out=368, P_out=254720, components=["ethylene"], zs=[1])
    assert d["n_components_used"] == 1 and d["ethylene_ethane_kij_override"] is False
    assert d["duty"]["heat_duty_molar"] == pytest.approx(3.1855849913372896, rel=1e-6)
    assert d["duty"]["sp_duty"] == pytest.approx(113.55529970018671, rel=1e-6)
    assert d["inlet"]["molecular_weight"] == pytest.approx(28.05316)


def test_water_heating_through_vaporisation_includes_the_phase_change():
    d = data(**WATER)
    assert d["inlet"]["vapor_fraction"] == pytest.approx(0.0) and d["outlet"]["vapor_fraction"] == pytest.approx(1.0)
    assert d["duty"]["heat_duty_molar"] == pytest.approx(48.957332061255876, rel=1e-6)
    assert d["duty"]["sp_duty"] == pytest.approx(2717.5448875208085, rel=1e-6)


def test_water_hexane_mixture_matches_reference():
    d = data(**WATER_HEXANE)
    assert d["duty"]["heat_duty_molar"] == pytest.approx(45.829038187266256, rel=1e-6)
    assert d["duty"]["sp_duty"] == pytest.approx(879.7150720499701, rel=1e-6)
    assert d["ethylene_ethane_kij_override"] is False


def test_no_change_gives_zero_duty():
    d = data(T_in=350, P_in=101325, T_out=350, P_out=101325, components=["methane", "ethane"], zs=[0.5, 0.5])
    assert d["duty"]["heat_duty_molar"] == 0.0 and d["duty"]["sp_duty"] == 0.0


# ------------------------------------------------ internal consistency
def test_duty_is_outlet_minus_inlet():
    d = data(**WATER_HEXANE)
    assert d["duty"]["heat_duty_molar"] == pytest.approx(d["outlet"]["enthalpy_molar"] - d["inlet"]["enthalpy_molar"], rel=1e-9)
    assert d["duty"]["sp_duty"] == pytest.approx(d["outlet"]["enthalpy_mass"] - d["inlet"]["enthalpy_mass"], rel=1e-9)


def test_molar_and_mass_basis_agree():
    d = data(**LEAD)
    assert d["duty"]["sp_duty"] == pytest.approx(d["duty"]["heat_duty_molar"] / d["inlet"]["molecular_weight"] * 1000, rel=1e-9)


def test_swapping_inlet_and_outlet_reverses_the_sign():
    fwd = data(**WATER_HEXANE)
    back = data(**{**WATER_HEXANE, "T_in": 380, "T_out": 300})
    assert back["duty"]["sp_duty"] == pytest.approx(-fwd["duty"]["sp_duty"], rel=1e-9)
    assert back["duty"]["sp_duty"] < 0  # cooling releases heat


# ------------------------------------------------ input handling
def test_zero_entries_are_skipped_and_do_not_change_the_result():
    full = data(**LEAD)
    active_only = data(T_in=300, P_in=254920, T_out=368, P_out=254720,
                       components=[c for c, z in zip(LEAD_COMPONENTS, LEAD_MOL_PERCENT) if z > 0],
                       zs=[z for z in LEAD_MOL_PERCENT if z > 0])
    assert full == active_only


def test_mol_percent_and_fractions_are_equivalent():
    pct = data(**WATER_HEXANE)
    frac = data(**{**WATER_HEXANE, "zs": [50, 50]})
    assert frac == pct


def test_unnormalised_input_is_flagged():
    r = call(**{**WATER_HEXANE, "zs": [1, 1]})
    assert r.status_code == 200 and r.json()["meta"]["zs_normalized"] is True


def test_names_cas_and_order_give_the_same_result():
    a = data(**WATER_HEXANE)
    b = data(**{**WATER_HEXANE, "components": ["110-54-3", "7732-18-5"], "zs": [0.5, 0.5]})
    assert a == b


def test_same_chemical_given_twice_is_merged():
    a = data(**WATER_HEXANE)
    b = data(**{**WATER_HEXANE, "components": ["water", "7732-18-5", "hexane"], "zs": [0.25, 0.25, 0.5]})
    assert b["duty"]["sp_duty"] == pytest.approx(a["duty"]["sp_duty"], rel=1e-9)


def test_envelope_matches_the_other_endpoints():
    j = call(**WATER_HEXANE).json()
    assert set(j) == {"status", "data", "units", "meta"} and j["status"] == "success"
    assert j["units"]["enthalpy_molar"] == "kJ/mol" and j["units"]["enthalpy_mass"] == "kJ/kg"
    assert j["units"]["sp_duty"] == "kJ/kg" and j["units"]["heat_duty_molar"] == "kJ/mol"
    assert j["meta"]["request_id"]


@pytest.mark.parametrize("patch", [
    {"T_in": 0}, {"T_out": -5}, {"P_in": 0}, {"P_out": -1}, {"T_in": "hot"},
    {"zs": [0.5]}, {"zs": [-1, 2]}, {"zs": [0, 0]}, {"components": ["water", "Water"]}, {"components": []},
])
def test_validation_errors_use_the_standard_envelope(patch):
    r = call(**{**WATER_HEXANE, **patch})
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "validation_error" and j["request_id"]


def test_unknown_component():
    r = call(**{**WATER_HEXANE, "components": ["water", "notachemical"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_component"
    assert r.json()["error"]["details"] == {"component": "notachemical"}


def test_missing_field_uses_the_documented_default():
    r = client.post(URL, json={"components": ["water"], "zs": [1]})
    assert r.status_code == 200  # T_in / P_in / T_out / P_out fall back to their defaults


# ------------------------------------------------ robustness
def test_flash_failure_at_one_condition_is_a_422_that_names_the_condition(monkeypatch):
    class Boom:
        def flash(self, **kw):
            raise RuntimeError("did not converge")

    data(**WATER_HEXANE)  # builds and caches the model
    entry = eos_service.get_or_build(("enthalpy", tuple(sorted(["7732-18-5", "110-54-3"]))), lambda: None)
    monkeypatch.setattr(entry, "flasher", Boom())
    r = call(**WATER_HEXANE)
    assert r.status_code == 422 and r.json()["error"]["code"] == "flash_failed"
    assert "inlet" in r.json()["error"]["message"] and "did not converge" in r.json()["error"]["message"]


def test_model_is_cached_between_requests():
    data(**WATER_HEXANE)
    size = eos_service.cache_size()
    t = time.time()
    data(**{**WATER_HEXANE, "T_out": 390})
    assert time.time() - t < 2.0
    assert eos_service.cache_size() == size <= eos_service.CACHE_MAX_ENTRIES


def test_other_endpoints_are_unaffected():
    r = client.post("/eos_stream_calc", json={"T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5]})
    assert r.status_code == 200 and r.json()["data"]["case"].startswith("two-phase liquid-liquid")
    r = client.post("/cp_calc", json={"T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5]})
    assert r.status_code == 200


def test_the_48_component_list_is_fast_enough():
    started = time.time()
    d = data(**LEAD)
    assert d["n_components_used"] == 10
    assert time.time() - started < 25
