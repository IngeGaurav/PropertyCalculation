"""Tests for the Vent API, POST /vent_flow_calc (polynomial fit of flow versus valve opening, flow estimates).

Expected values come from running the lead's reference module unchanged on the same data (see docs).
"""
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app, raise_server_exceptions=False)
URL = "/vent_flow_calc"

DEMO = dict(opening_values=[19.7, 49.6, 89.7], flow_values=[48601, 122050, 220698])
QUAD = dict(opening_values=[10, 20, 40, 60, 80, 100], flow_values=[350, 700, 1980, 4000, 6600, 9900])


def call(**body):
    return client.post(URL, json=body)


def data(**body):
    r = call(**body)
    assert r.status_code == 200, r.json()
    return r.json()["data"]


def terms(d):
    return [t["coefficient"] for t in d["fit"]["terms"]]


# -------------------------------------------------- agreement with the reference module
def test_demo_data_matches_the_reference_including_the_degree_cap():
    d = data(**DEMO, degree=3, estimate_at=[5, 10, 25, 50, 75, 95, 110])
    fit = d["fit"]
    assert (fit["degree_requested"], fit["degree_used"], fit["degree_capped"]) == (3, 1, True)
    assert fit["n_points"] == 3 and fit["df_residual"] == 1
    assert terms(d) == pytest.approx([2458.61301, 143.19700], rel=1e-5)  # highest power first
    assert fit["r_squared"] == pytest.approx(0.9999998348200886, rel=1e-12)
    assert fit["standard_error_y"] == pytest.approx(49.63445520262793, rel=1e-9)
    assert fit["f_statistic"] == pytest.approx(6054003.940519365, rel=1e-9)
    assert fit["ss_residual"] == pytest.approx(2463.5788, rel=1e-6)
    assert fit["opening_range"] == {"min": 19.7, "max": 89.7}
    assert fit["equation"].startswith("Flow(Opening) = +2458.61*Opening +143.197")
    flows = [e["flow"] for e in d["estimates"]]
    assert flows == pytest.approx([48577.866, 48577.866, 61608.513, 123073.829, 184539.145, 220680.75, 220680.75], rel=1e-8)
    assert [e["extrapolated"] for e in d["estimates"]] == [True, True, False, False, False, True, True]


def test_quadratic_fit_matches_the_reference():
    d = data(**QUAD, degree=2, estimate_at=[5, 30, 55, 100, 120])
    fit = d["fit"]
    assert fit["degree_used"] == 2 and fit["degree_capped"] is False and fit["df_residual"] == 3
    assert fit["r_squared"] == pytest.approx(0.999961338493968, rel=1e-12)
    assert fit["standard_error_y"] == pytest.approx(29.99767514319017, rel=1e-9)
    assert fit["f_statistic"] == pytest.approx(38796.78164880178, rel=1e-9)
    assert [e["flow"] for e in d["estimates"]] == pytest.approx([328.653, 1279.395, 3414.173, 9906.557, 9906.557], rel=1e-5)


def test_cubic_fit_matches_the_reference():
    d = data(opening_values=[5, 15, 25, 35, 50, 65, 80, 95], flow_values=[110, 420, 980, 1900, 4200, 7900, 13100, 19800],
             degree=3, estimate_at=[0, 45, 99])
    assert d["fit"]["degree_used"] == 3 and len(d["fit"]["terms"]) == 4
    assert d["fit"]["r_squared"] == pytest.approx(0.9999480483490708, rel=1e-12)
    assert d["fit"]["standard_error_y"] == pytest.approx(67.95171298515658, rel=1e-9)
    assert [e["flow"] for e in d["estimates"]] == pytest.approx([150.183, 3356.074, 19833.921], rel=1e-5)


def test_coefficients_are_highest_power_first_and_match_numpy():
    rng = np.random.default_rng(7)
    x = np.sort(rng.uniform(5, 95, 15))
    y = 0.4 * x ** 2 + 30 * x + 200 + rng.normal(0, 25, x.size)
    d = data(opening_values=x.tolist(), flow_values=y.tolist(), degree=2)
    assert [t["power"] for t in d["fit"]["terms"]] == [2, 1, 0]
    assert terms(d) == pytest.approx(list(np.polyfit(x, y, 2)), rel=1e-7)


def test_standard_errors_match_the_textbook_formula():
    x = np.array([10.0, 20, 40, 60, 80, 100])
    y = np.array([350.0, 700, 1980, 4000, 6600, 9900])
    X = np.vander(x, 3)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    mse = np.sum((y - X @ beta) ** 2) / (len(x) - 3)
    expected = np.sqrt(np.diag(mse * np.linalg.inv(X.T @ X)))
    d = data(opening_values=x.tolist(), flow_values=y.tolist(), degree=2)
    assert [t["standard_error"] for t in d["fit"]["terms"]] == pytest.approx(list(expected), rel=1e-9)


# -------------------------------------------------- estimates
def test_clip_to_fit_range_flags_extrapolation_but_evaluates_at_the_range_end():
    d = data(**DEMO, degree=1, estimate_at=[5, 110])
    low, high = d["estimates"]
    assert low["extrapolated"] and low["opening_used"] == 19.7 and high["opening_used"] == 89.7


def test_without_clipping_the_polynomial_is_extrapolated():
    d = data(**DEMO, degree=1, estimate_at=[5, 110], clip_to_fit_range=False)
    assert [e["opening_used"] for e in d["estimates"]] == [5, 110]
    assert [e["flow"] for e in d["estimates"]] == pytest.approx([12436.26, 270590.587], rel=1e-6)
    assert all(e["extrapolated"] for e in d["estimates"])


def test_minimum_flow_floor():
    d = data(opening_values=[10, 20, 30], flow_values=[5, 100, 400], degree=1, estimate_at=[0, 25], clip_to_fit_range=False)
    assert d["estimates"][0]["flow"] == 0.0 and d["estimates"][0]["floor_applied"] is True  # polynomial is negative at 0
    assert d["estimates"][1]["floor_applied"] is False
    d = data(opening_values=[10, 20, 30], flow_values=[5, 100, 400], degree=1, estimate_at=[0], clip_to_fit_range=False, min_flow=50)
    assert d["estimates"][0]["flow"] == 50.0


def test_no_estimates_requested_returns_only_the_fit():
    d = data(**DEMO, degree=1)
    assert d["estimates"] == [] and d["fit"]["terms"]


# -------------------------------------------------- undefined statistics are null, never NaN
def strict_json(text):
    def reject(name):
        raise AssertionError(f"response contains {name}")
    return json.loads(text, parse_constant=reject)


def test_constant_flow_gives_null_r_squared_and_f_with_a_warning():
    r = call(opening_values=[10, 20, 30, 40], flow_values=[500, 500, 500, 500], degree=2, estimate_at=[25])
    j = strict_json(r.text)
    fit = j["data"]["fit"]
    assert r.status_code == 200 and fit["r_squared"] is None and fit["f_statistic"] is None
    assert any("flow values are equal" in w for w in j["data"]["warnings"])
    assert j["data"]["estimates"][0]["flow"] == pytest.approx(500.0, abs=1e-6)


def test_exact_fit_gives_null_f_with_a_warning():
    r = call(opening_values=[10, 20, 30, 40], flow_values=[100, 200, 300, 400], degree=1)
    j = strict_json(r.text)
    assert j["data"]["fit"]["f_statistic"] is None and j["data"]["fit"]["r_squared"] == pytest.approx(1.0)
    assert any("exactly" in w for w in j["data"]["warnings"])


def test_every_response_is_strict_json():
    for body in (dict(**DEMO, degree=3), dict(**QUAD, degree=2), dict(**QUAD, degree=10)):
        strict_json(call(**body).text)


# -------------------------------------------------- warnings and flags
def test_warnings_report_the_degree_cap_and_the_extrapolation():
    d = data(**DEMO, degree=3, estimate_at=[5, 50])
    assert any("reduced to 1" in w for w in d["warnings"])
    assert any("1 of 2 estimate openings lie outside" in w for w in d["warnings"])
    assert data(**QUAD, degree=2, estimate_at=[50])["warnings"] == []


# -------------------------------------------------- envelope
def test_envelope_follows_the_standard_shape_without_composition_fields():
    j = call(**DEMO, degree=1, estimate_at=[50]).json()
    assert set(j) == {"status", "data", "units", "meta"} and j["status"] == "success"
    assert set(j["meta"]) == {"request_id", "elapsed_ms"}  # no zs_normalized: there is no composition
    assert j["units"]["opening"] == "%" and "flow_values" in j["units"]["flow"]


def test_composition_endpoints_still_report_zs_normalized():
    r = client.post("/cp_calc", json={"T": 300, "P": 101325, "components": ["7732-18-5", "110-54-3"], "zs": [0.5, 0.5]})
    assert r.json()["meta"]["zs_normalized"] is False


# -------------------------------------------------- validation and errors
@pytest.mark.parametrize("patch", [
    {"flow_values": [1, 2]},                                   # different length
    {"opening_values": [10, 20], "flow_values": [1, 2]},        # fewer than 3 points
    {"degree": 0}, {"degree": 11}, {"degree": 2.5}, {"degree": "two"},
    {"opening_values": [10, "x", 30]},
    {"opening_values": "10,20,30"},
    {"min_flow": "low"},
])
def test_validation_errors_use_the_standard_envelope(patch):
    r = call(**{**DEMO, "degree": 1, **patch})
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "validation_error" and j["request_id"]


def test_validation_message_names_the_length_problem():
    j = call(**{**DEMO, "flow_values": [1, 2, 3, 4]}).json()
    assert "same length" in j["error"]["details"][0]["message"]


@pytest.mark.parametrize("raw", [
    '{"opening_values": [10, 20, 1e999], "flow_values": [1, 2, 3], "degree": 1}',   # 1e999 parses as infinity
    '{"opening_values": [10, 20, 30], "flow_values": [1, 2, 3], "degree": 1, "estimate_at": [1e999]}',
    '{"opening_values": [10, 20, 30], "flow_values": [1, 2, 3], "degree": 1, "min_flow": 1e999}',
])
def test_infinite_numbers_are_rejected(raw):
    r = client.post(URL, content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_too_few_distinct_openings_is_a_fit_failure_not_a_crash():
    r = call(opening_values=[10, 10, 10, 20], flow_values=[1, 2, 3, 4], degree=2)
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "fit_failed"
    assert j["error"]["details"] == {"distinct_opening_values": 2, "required": 3, "degree_used": 2}


def test_all_openings_identical_is_a_fit_failure():
    r = call(opening_values=[50, 50, 50], flow_values=[1, 2, 3], degree=1)
    assert r.status_code == 422 and r.json()["error"]["code"] == "fit_failed"


def test_defaults_are_used_when_fields_are_missing_and_unknown_fields_are_ignored():
    r = client.post(URL, json={"unknown": 1})
    assert r.status_code == 200 and r.json()["data"]["fit"]["n_points"] == 3


def test_a_large_data_set_is_fast():
    x = np.linspace(1, 100, 5000)
    y = 3 * x ** 2 + 50 * x + 1000
    started = time.time()
    d = data(opening_values=x.tolist(), flow_values=y.tolist(), degree=2, estimate_at=[10, 50, 90])
    assert time.time() - started < 5
    assert terms(d) == pytest.approx([3, 50, 1000], rel=1e-6)


def test_other_endpoints_are_unaffected():
    r = client.post("/eos_enthalpy_calc", json={"T_in": 300, "P_in": 101325, "T_out": 400, "P_out": 101325, "components": ["7732-18-5"], "zs": [1]})
    assert r.status_code == 200 and r.json()["data"]["duty"]["sp_duty"] == pytest.approx(2717.5448875208085, rel=1e-6)
