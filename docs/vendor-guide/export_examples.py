"""Export the documented request/response examples of every endpoint, taken from the code and the live API.

Usage:  python export_examples.py examples.json
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Backend"))
logging.disable(logging.CRITICAL)
from app import api_docs, schemas  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


def compact(v):
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{json.dumps(k)}: {compact(x)}" for k, x in v.items()) + " }" if v else "{}"
    if isinstance(v, list):
        return "[" + ", ".join(compact(x) for x in v) + "]"
    return json.dumps(v)


def pretty(v, ind=0, width=100):
    """JSON text: short objects and lists on one line, long ones expanded. Floats keep their .0."""
    one = compact(v)
    if not isinstance(v, (dict, list)) or len(one) + ind * 2 <= width:
        return one
    pad = "  " * (ind + 1)
    if isinstance(v, dict):
        return "{\n" + ",\n".join(f"{pad}{json.dumps(k)}: {pretty(x, ind + 1, width)}" for k, x in v.items()) + "\n" + "  " * ind + "}"
    return "[\n" + ",\n".join(pad + pretty(x, ind + 1, width) for x in v) + "\n" + "  " * ind + "]"


def rnd(o):
    """Round floats to 7 significant digits, as the documentation examples are."""
    if isinstance(o, float):
        return float(f"{o:.7g}")
    if isinstance(o, dict):
        return {k: rnd(x) for k, x in o.items()}
    if isinstance(o, list):
        return [rnd(x) for x in o]
    return o


client = TestClient(app, raise_server_exceptions=False)
out = {}
for path, doc in api_docs.ENDPOINT_DOCS.items():
    real = client.post(path, json=doc.request)
    assert real.status_code == 200, (path, real.text)  # every documented request must really work
    out[path] = {"request": pretty(doc.request), "data": pretty(doc.data)}

# Vent API: a shorter example (three estimates) taken from the live API
vent_req = dict(api_docs.VENT_REQUEST, estimate_at=[5, 50, 110])
vent_real = client.post("/vent_flow_calc", json=vent_req)
assert vent_real.status_code == 200
out["/vent_flow_calc"] = {"request": pretty(vent_req), "data": pretty(rnd(vent_real.json()["data"]))}

cp = api_docs.ENDPOINT_DOCS["/cp_calc"]
out["_envelope"] = pretty(api_docs.success_example(cp, schemas.CP_UNITS))
out["_health"] = pretty({"status": "ok", "version": app.version})
out["_version"] = app.version

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print("exported", [k for k in out if k.startswith("/")], "version", app.version)
