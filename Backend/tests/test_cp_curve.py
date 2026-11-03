"""Cp versus temperature: the EOS stream calculation repeated over a temperature range."""
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app, raise_server_exceptions=False)
PATH = "/eos_cp_curve_calc"
METHANE, ETHANE, WATER, HEXANE = "74-82-8", "74-84-0", "7732-18-5", "110-54-3"
BASE = {"P": 101325, "components": [METHANE, ETHANE], "zs": [0.5, 0.5], "T_start": 300, "T_end": 400, "interval": 10}


def post(**changes):
    return client.post(PATH, json={**BASE, **changes})


def test_table_has_one_row_per_interval():
    r = post()
    j = r.json()
    assert r.status_code == 200 and j["status"] == "success"
    pts = j["data"]["points"]
    assert [p["T"] for p in pts] == [300 + 10 * i for i in range(11)]
    assert j["data"]["n_points"] == 11 and j["data"]["n_failed"] == 0
    assert j["data"]["T_start"] == 300 and j["data"]["T_end"] == 400 and j["data"]["interval"] == 10
    assert j["units"]["Cp"] == "J/mol/K" and j["meta"]["zs_normalized"] is False
    assert all(p["Cp"] > 0 and p["error"] is None for p in pts)
    assert pts[0]["Cp"] < pts[-1]["Cp"]  # an ideal-gas mixture heats up with temperature


def test_every_row_equals_the_stream_api_at_that_temperature():
    pts = post(T_end=320).json()["data"]["points"]
    for p in pts:
        one = client.post("/eos_stream_calc", json={"T": p["T"], "P": 101325, "components": BASE["components"], "zs": BASE["zs"]}).json()["data"]
        assert p["Cp"] == pytest.approx(one["mixture"]["Cp"], rel=1e-12)
        assert p["Cp_mass_kJ_kgK"] == pytest.approx(one["mixture"]["Cp_mass_kJ_kgK"], rel=1e-12)
        assert p["case"] == one["case"] and p["V"] == pytest.approx(one["V"])


def test_default_end_is_2273_k_and_the_last_row_is_not_above_it():
    j = client.post(PATH, json={**BASE, "T_end": None} if False else {k: v for k, v in BASE.items() if k != "T_end"}).json()
    d = j["data"]
    assert d["T_end"] == 2270 and d["points"][-1]["T"] == 2270 and d["n_points"] == 198
    assert all(p["Cp"] > 0 for p in d["points"])


def test_hot_single_phase_is_vapor_not_liquid():
    """Above the critical region thermo calls a single phase 'liquid'; a gas-type root must be reported as vapor."""
    hot = post(T_start=1500, T_end=2273).json()["data"]["points"]
    assert all(p["case"] == "vapor-only" and p["V"] == 1.0 for p in hot)


def test_phase_change_is_followed_along_the_range():
    pts = post(components=[WATER, HEXANE], T_start=280, T_end=420, interval=20).json()["data"]["points"]
    cases = [p["case"] for p in pts]
    assert "two-phase liquid-liquid (LL, aqueous+organic)" in cases and "vapor-only" in cases
    assert cases.index("two-phase vapor-liquid (VL)") < cases.index("vapor-only")


def test_step_that_does_not_divide_the_range():
    d = post(T_start=300, T_end=335, interval=10).json()["data"]
    assert [p["T"] for p in d["points"]] == [300, 310, 320, 330] and d["T_end"] == 330


def test_single_temperature():
    d = post(T_start=350, T_end=350).json()["data"]
    assert d["n_points"] == 1 and d["points"][0]["T"] == 350


def test_decimal_interval_has_no_float_noise():
    d = post(T_start=300, T_end=301, interval=0.1).json()["data"]
    assert [p["T"] for p in d["points"]] == [300 + i / 10 for i in range(11)]


def test_zero_fraction_components_are_skipped_and_fractions_rescaled():
    j = post(components=[METHANE, ETHANE, WATER], zs=[1, 1, 0]).json()
    assert j["data"]["n_components_used"] == 2 and j["meta"]["zs_normalized"] is True


# ------------------------------------------------------------------------- validation
@pytest.mark.parametrize("changes,text", [
    ({"T_end": 200}, "must not be below T_start"),
    ({"interval": 0}, None), ({"interval": -10}, None), ({"T_start": 0}, None), ({"P": 0}, None), ({"P": -1}, None),
    ({"T_start": 0.0, "T_end": 5}, None),
    ({"components": ["water", HEXANE]}, "CAS"),
    ({"components": [METHANE, METHANE], "zs": [0.5, 0.5]}, "duplicate"),
    ({"zs": [1.0]}, "same length"),
    ({"interval": 0.1, "T_end": 2273}, "maximum is 1000"),
])
def test_bad_input_is_a_validation_error(changes, text):
    r = post(**changes)
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "validation_error"
    if text:
        assert text in str(j["error"]["details"])


def test_exactly_the_maximum_number_of_points_is_accepted():
    r = post(T_start=300, T_end=1299, interval=1)
    assert r.status_code == 200 and r.json()["data"]["n_points"] == 1000


def test_unknown_cas_is_unknown_component():
    r = post(components=[METHANE, "9999-99-9"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_component"


def test_missing_field_uses_the_defaults():
    r = client.post(PATH, json={"components": [METHANE], "zs": [1]})
    assert r.status_code == 200 and r.json()["data"]["T_start"] == 300 and r.json()["data"]["T_end"] == 2270


def test_documented_example_is_a_working_request():
    from app import api_docs
    r = client.post(PATH, json=api_docs.ENDPOINT_DOCS[PATH].request)
    assert r.status_code == 200


def test_kcal_columns_are_the_si_values_divided_by_4_184():
    for p in post(T_end=330).json()["data"]["points"]:
        assert p["Cp_kcal_kmolK"] == pytest.approx(p["Cp"] / 4.184, rel=1e-12)
        assert p["Cp_mass_kcal_kgK"] == pytest.approx(p["Cp_mass_kJ_kgK"] / 4.184, rel=1e-12)
    assert post().json()["units"]["Cp_kcal_kmolK"] == "kcal/kmol/K"
    assert post().json()["units"]["Cp_mass_kcal_kgK"] == "kcal/kg/K"


def test_kcal_per_kmol_equals_kcal_per_kg_times_molecular_weight():
    for p in post(T_end=330).json()["data"]["points"]:
        assert p["Cp_kcal_kmolK"] == pytest.approx(p["Cp_mass_kcal_kgK"] * p["MW"], rel=1e-9)
