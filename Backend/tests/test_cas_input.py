"""Components are CAS numbers only: a name (or anything that is not a valid CAS number) is rejected with a clear error.

The rule lives in the shared request model, so it must hold for every endpoint that takes components.
"""
import pytest
from fastapi.testclient import TestClient

from app.schemas import cas_problem
from main import app

client = TestClient(app, raise_server_exceptions=False)

WATER, HEXANE, METHANE, ETHANE = "7732-18-5", "110-54-3", "74-82-8", "74-84-0"

STATE = {"T": 300, "P": 101325}
CONDITIONS = {"T_in": 300, "P_in": 101325, "T_out": 350, "P_out": 101325}
ENDPOINTS = {
    "/cp_calc": STATE, "/density_calc": STATE, "/mw_calc": STATE, "/vf_calc": STATE,
    "/triphase_cp_calc": STATE, "/triphase_mw_calc": STATE, "/triphase_vf_calc": STATE,
    "/eos_stream_calc": STATE, "/eos_enthalpy_calc": CONDITIONS,
}
ALL = list(ENDPOINTS)


def post(path, components, zs=None):
    body = {**ENDPOINTS[path], "components": components, "zs": zs or [1 / len(components)] * len(components)}
    return client.post(path, json=body)


def message(response):
    return response.json()["error"]["details"][0]["message"]


# ------------------------------------------------------------------------- names are rejected, everywhere
@pytest.mark.parametrize("path", ALL)
def test_a_name_is_rejected_on_every_endpoint(path):
    r = post(path, ["water", HEXANE])
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "validation_error"
    assert j["error"]["details"][0]["field"] == "components"
    assert "CAS" in message(r) and "'water'" in message(r) and "a name, not a CAS number" in message(r)


@pytest.mark.parametrize("path", ALL)
def test_valid_cas_numbers_are_accepted_on_every_endpoint(path):
    r = post(path, [WATER, HEXANE])
    assert r.status_code == 200, r.json()


def test_every_offending_entry_is_listed_and_valid_ones_are_not():
    msg = message(post("/cp_calc", [WATER, "hexane", "ethanol"]))
    assert "'hexane'" in msg and "'ethanol'" in msg and "'7732-18-5'" not in msg


@pytest.mark.parametrize("bad", ["Water", "WATER", "H2O", "n-hexane", "carbon dioxide"])
def test_names_in_any_spelling_are_rejected(bad):
    assert post("/vf_calc", [bad, HEXANE]).status_code == 422


@pytest.mark.parametrize("bad", ["7732185", "7732-18", "77-32-18-5", "7732-1-85", "-18-5", "1-18-5", "12345678-18-5", "7732-18-55",
                                 "7732–18–5", "7732 18 5", "ABC-12-3", "7732-18-x"])
def test_malformed_cas_numbers_are_rejected(bad):
    r = post("/vf_calc", [bad, HEXANE])
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert "not in CAS format" in message(r) or "a name" in message(r)


def test_a_mistyped_cas_number_is_caught_by_the_check_digit():
    r = post("/vf_calc", ["7732-18-4", HEXANE])  # water is 7732-18-5
    assert r.status_code == 422 and "invalid CAS check digit" in message(r)


def test_an_empty_component_is_rejected():
    assert post("/vf_calc", ["", HEXANE]).status_code == 422
    assert post("/vf_calc", ["   ", HEXANE]).status_code == 422


def test_surrounding_spaces_are_ignored():
    assert post("/vf_calc", [f" {WATER} ", f"{HEXANE}\t"]).status_code == 200


@pytest.mark.parametrize("path", ALL)
def test_the_same_cas_number_twice_is_rejected(path):
    r = post(path, [WATER, WATER])
    assert r.status_code == 422 and "duplicate" in message(r)


# ------------------------------------------------------------------------- valid format but not in the database
@pytest.mark.parametrize("path", ALL)
def test_a_valid_but_unknown_cas_number_is_unknown_component(path):
    assert cas_problem("9999-99-9") is None  # well formed and with a correct check digit
    r = post(path, [WATER, "9999-99-9"])
    j = r.json()
    assert r.status_code == 422 and j["error"]["code"] == "unknown_component"
    assert j["error"]["details"] == {"component": "9999-99-9"}
    assert "CAS number '9999-99-9'" in j["error"]["message"]


# ------------------------------------------------------------------------- the validator itself
LEAD_COMPONENTS = ["7732-18-5", "7783-06-4", "630-08-0", "124-38-9", "1333-74-0", "74-82-8", "74-86-2", "74-85-1", "74-84-0", "74-99-7", "115-07-1", "74-98-6", "689-97-4", "106-99-0", "115-11-7", "106-98-9", "624-64-6", "106-97-8", "75-28-5", "591-93-5", "78-79-5", "542-92-7", "142-29-0", "563-46-2", "109-66-0", "109-67-1", "78-78-4", "287-92-3", "71-43-2", "693-89-0", "513-81-5", "592-41-6", "96-37-7", "110-54-3", "110-82-7", "26519-91-5", "762-62-9", "592-76-7", "108-88-3", "28823-41-8", "628-92-2", "142-82-5", "100-42-5", "106-42-3", "100-41-4", "91-20-3", "124-11-8", "111-84-2"]


@pytest.mark.parametrize("cas", LEAD_COMPONENTS)
def test_every_cas_number_of_the_plant_list_is_valid(cas):
    assert cas_problem(cas) is None


def test_cas_problem_reasons():
    assert cas_problem("water") == "a name, not a CAS number"
    assert cas_problem("7732185").startswith("not in CAS format")
    assert cas_problem("7732-18-4") == "invalid CAS check digit (typing error?)"
    assert cas_problem("7732-18-5") is None


# ------------------------------------------------------------------------- documentation wording
SPEC = client.get("/openapi.json").json()


def test_the_documentation_says_cas_only_and_mole_fractions():
    text = str(SPEC)
    assert "CAS numbers only" in text
    assert "not mole percent" in text
    assert text.count("mole percent") == text.count("not mole percent")  # never offered as an option
    assert "names or CAS" not in text.lower() and "name or cas" not in text.lower()


def test_the_documentation_has_no_vague_unit_wording():
    text = str(SPEC)
    assert "any one consistent unit" not in text and "any one unit" not in text
    flow = SPEC["components"]["schemas"]["VentFlowInput"]["properties"]["flow_values"]["description"]
    assert "unit of your data" in flow and "same unit" in flow and "nothing is converted" in flow


def test_the_request_example_components_are_cas_numbers():
    for path in ALL:
        example = SPEC["paths"][path]["post"]["requestBody"]["content"]["application/json"]["example"]
        assert all(cas_problem(c) is None for c in example["components"]), path
