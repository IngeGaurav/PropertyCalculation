"""Export the real requests and FULL responses of the vendor-facing endpoints, taken from the live application.

Usage:  python export_examples.py examples.json

Every example in the integration guide comes from here, so it is a real response of this version of the API.
"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Backend"))
logging.disable(logging.CRITICAL)
from app import api_docs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

REQUEST_ID = "a1b2c3d4e5f6"


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
    if all(not isinstance(x, (dict, list)) for x in v):  # plain values: wrap several to a line
        lines, cur = [], ""
        for x in v:
            piece = json.dumps(x)
            if cur and len(pad) + len(cur) + 2 + len(piece) > width:
                lines.append(cur + ",")
                cur = piece
            else:
                cur = f"{cur}, {piece}" if cur else piece
        lines.append(cur)
        return "[\n" + "\n".join(pad + line for line in lines) + "\n" + "  " * ind + "]"
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


def real_response(path, request):
    client.post(path, json=request)  # warm-up: the first request for a new set of components builds the model
    r = client.post(path, json=request)
    assert r.status_code == 200, (path, r.text)  # every documented request must really work
    j = r.json()
    j["meta"]["request_id"] = REQUEST_ID
    j["meta"]["elapsed_ms"] = round(j["meta"]["elapsed_ms"], 1)  # a normal (warm) response time
    return rnd(j)


def real_error(path, request, status):
    r = client.post(path, json=request)
    assert r.status_code == status, (path, r.status_code, r.text)
    j = r.json()
    j["request_id"] = REQUEST_ID
    return j


out = {}

# ---- the three vendor-facing APIs: request and full response
requests = {
    "/eos_stream_calc": api_docs.WATER_HEXANE,
    "/eos_enthalpy_calc": api_docs.LEAD_STREAM_REQUEST,
    "/vent_flow_calc": dict(api_docs.VENT_REQUEST, estimate_at=[5, 50, 110]),
}
for path, req in requests.items():
    out[path] = {"request": pretty(req), "response": pretty(real_response(path, req))}

# a second, single-phase example for the stream API (shown in the notes of the guide)
out["_gas"] = pretty(rnd(client.post("/eos_stream_calc", json={"T": 423.15, "P": 29411.81, "components": ["74-82-8", "74-84-0"], "zs": [0.5, 0.5]}).json()["data"]))

# ---- real error responses
bad_names = dict(api_docs.WATER_HEXANE, components=["water", "hexane"])
out["_err_names"] = pretty(real_error("/eos_stream_calc", bad_names, 422))
out["_err_unknown"] = pretty(real_error("/eos_stream_calc", dict(api_docs.WATER_HEXANE, components=["7732-18-5", "9999-99-9"]), 422))
out["_err_zs_length"] = pretty(real_error("/eos_stream_calc", dict(api_docs.WATER_HEXANE, zs=[1.0]), 422))
out["_err_fit"] = pretty(real_error("/vent_flow_calc", {"opening_values": [50, 50, 50, 50], "flow_values": [1, 2, 3, 4], "degree": 2}, 422))
out["_err_typo"] = pretty(real_error("/eos_stream_calc", dict(api_docs.WATER_HEXANE, components=["7732-18-4", "110-54-3"]), 422))

out["_health"] = pretty({"status": "ok", "version": app.version})
out["_version"] = app.version

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print("exported", [k for k in out if k.startswith("/")], "version", app.version,)
