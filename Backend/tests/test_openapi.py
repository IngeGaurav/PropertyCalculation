"""The generated API documentation (OpenAPI / Swagger) is part of the product shared with integrators."""
import pytest
from fastapi.testclient import TestClient

from app import api_docs
from main import app

client = TestClient(app, raise_server_exceptions=False)
SPEC = client.get("/openapi.json").json()

PROPERTY_PATHS = ["/cp_calc", "/density_calc", "/mw_calc", "/vf_calc",
                  "/triphase_cp_calc", "/triphase_mw_calc", "/triphase_vf_calc"]
EOS_PATHS = ["/eos_stream_calc"]
ENTHALPY_PATHS = ["/eos_enthalpy_calc"]
VENT_PATHS = ["/vent_flow_calc"]
ALL_CALC = PROPERTY_PATHS + EOS_PATHS + ENTHALPY_PATHS + VENT_PATHS


def op(path, method="post"):
    return SPEC["paths"][path][method]


def test_exact_set_of_endpoints():
    assert sorted(SPEC["paths"]) == sorted(ALL_CALC + ["/health"])


def test_retired_enthalpy_endpoints_are_gone():
    """The first-generation enthalpy endpoints were replaced by /eos_enthalpy_calc."""
    for path in ("/enthalpy_calc", "/std_enthalpy_calc"):
        assert path not in SPEC["paths"]
        assert client.post(path, json={}).status_code == 404


def test_page_metadata():
    info = SPEC["info"]
    assert info["title"] == "Thermo Property API"
    assert info["version"] == client.get("/health").json()["version"]
    assert all(g in info["description"] for g in ("Property APIs", "EOS Stream API", "Enthalpy API", "Vent API"))
    assert [t["name"] for t in SPEC["tags"]] == [api_docs.TAG_PROPERTY, api_docs.TAG_EOS, api_docs.TAG_ENTHALPY, api_docs.TAG_VENT, api_docs.TAG_SYSTEM]
    assert all(t["description"] for t in SPEC["tags"])


@pytest.mark.parametrize("path", ALL_CALC)
def test_every_calculation_endpoint_is_fully_documented(path):
    o = op(path)
    assert o["tags"] == [api_docs.ENDPOINT_DOCS[path].tag]
    assert o["summary"] and len(o["description"]) > 150
    assert o["operationId"] and " " not in o["operationId"]
    # a real request example and a real success example
    example = o["requestBody"]["content"]["application/json"]["example"]
    assert example and (path == "/vent_flow_calc" or example["components"])
    ok = o["responses"]["200"]["content"]["application/json"]
    assert ok["example"]["status"] == "success" and ok["example"]["units"] and ok["example"]["meta"]["request_id"]
    # documented error responses
    assert {"401", "422", "500", "504"} <= set(o["responses"])
    assert o["responses"]["422"]["content"]["application/json"]["example"]["status"] == "error"


def test_operation_ids_are_unique():
    ids = [m["operationId"] for p in SPEC["paths"].values() for m in p.values()]
    assert len(ids) == len(set(ids))


def test_groups():
    assert {op(p)["tags"][0] for p in PROPERTY_PATHS} == {"Property APIs"}
    assert op("/eos_stream_calc")["tags"] == ["EOS Stream API"]
    assert op("/eos_enthalpy_calc")["tags"] == ["Enthalpy API"]
    assert op("/vent_flow_calc")["tags"] == ["Vent API"]
    assert op("/health", "get")["tags"] == ["System"]


def _same(real, doc, where):
    """Documented example (rounded to 7 significant digits) must equal the real response."""
    if isinstance(doc, dict):
        assert isinstance(real, dict) and real.keys() == doc.keys(), where
        for k in doc:
            _same(real[k], doc[k], f"{where}.{k}")
    elif isinstance(doc, list):
        assert isinstance(real, list) and len(real) == len(doc), where
        for i, (r, d) in enumerate(zip(real, doc)):
            _same(r, d, f"{where}[{i}]")
    elif isinstance(doc, bool) or doc is None or isinstance(doc, str):
        assert real == doc, where
    else:
        assert real == pytest.approx(doc, rel=1e-5, abs=1e-9), where


def test_documented_examples_are_real_responses():
    """The examples in the docs must match what the API really returns for the documented request."""
    for path in ALL_CALC:
        d = api_docs.ENDPOINT_DOCS[path]
        real = client.post(path, json=d.request).json()["data"]
        _same(real, d.data, path)


def test_documented_meta_matches_the_real_meta():
    for path in ALL_CALC:
        d = api_docs.ENDPOINT_DOCS[path]
        real_meta = client.post(path, json=d.request).json()["meta"]
        example_meta = api_docs.success_example(d, {})["meta"]
        assert real_meta.keys() == example_meta.keys(), path


def test_swagger_page_loads():
    r = client.get("/docs")
    assert r.status_code == 200 and "swagger" in r.text.lower()
