# Thermo Property API – v2.0 documentation

FastAPI service that computes thermodynamic properties of mixtures with the
[`thermo`](https://github.com/CalebBell/thermo) library (tested with thermo 0.6.1,
FastAPI 0.142, Pydantic 2.13, Python 3.14).

This document explains **what changed from the original single-file `main.py`, why, and how to use the new API.**
The original file is the baseline; every change below is listed against it.

---

## 1. Project layout

```
main.py                 App entry point: middleware, error handlers, /health
app/
  config.py             Settings read from environment variables
  errors.py             Domain exceptions (each has an HTTP status + stable code)
  schemas.py            Request models, response models, unit tables
  thermo_service.py     All thermodynamic calculations (no FastAPI code)
  routes.py             The 9 endpoints + API-key check + timeout wrapper
tests/test_api.py       29 tests (pytest)
```

Original: one 770-line file where the same ~20 lines of validation were pasted into all 9 endpoints.
New: validation exists **once** (`schemas.Composition`), maths **once per property** (`thermo_service.py`),
HTTP concerns **once** (`routes.py` / `main.py`).

Run: `uvicorn main:app --host 0.0.0.0 --port 8000` — interactive docs at `/docs`.
Tests: `pip install pytest httpx`, then `python -m pytest tests`.

---

## 2. Request / response cycle

```
client --POST JSON--> middleware (request id, timing, log)
                         |
                         v
                 API-key check (only if API_KEY is set)
                         |
                         v
          Pydantic validation (schemas.py)  --invalid--> 422 validation_error
                         |
                         v
     thread pool + timeout (routes._execute)  --too slow--> 504 calculation_timeout
                         |
                         v
        thermo_service: resolve names -> Mixture -> flash -> property
                         |            \-- known failures --> 422 / 500 with a code
                         v
            ApiResponse{status, data, units, meta}  --> 200
```

### Success response (all endpoints share this envelope)

```json
{
  "status": "success",
  "data":  { "...endpoint specific..." },
  "units": { "Cp_mix": "J/mol/K" },
  "meta":  { "request_id": "50a31c36a159", "elapsed_ms": 24.5, "zs_normalized": false }
}
```

### Error response (every error, including 401/404/405/500, has this shape)

```json
{
  "status": "error",
  "error": { "code": "validation_error", "message": "Request body is invalid.",
             "details": [ { "field": "body", "message": "components (2) and zs (1) must have the same length" } ] },
  "request_id": "0f6d3e325f7d"
}
```

| HTTP | `error.code` | When |
|---|---|---|
| 401 | `unauthorized` | `API_KEY` is set and the `X-API-Key` header is missing or wrong |
| 404 / 405 | `not_found` / `method_not_allowed` | Wrong path / method |
| 422 | `validation_error` | Bad input (see §3). `details` lists each field |
| 422 | `unknown_component` | thermo does not know a name/CAS. `details.component` names it |
| 422 | `flash_failed` | Phase equilibrium calculation failed or returned nothing |
| 422 | `property_unavailable` | thermo has no data (e.g. no formation enthalpy for a component) |
| 422 | `water_required` | A `triphase_*` endpoint was called without water |
| 500 | `calculation_failed` | thermo could not build the mixture |
| 500 | `internal_error` | Any unexpected bug. The traceback is **logged, not returned**; the client gets only `request_id` |
| 504 | `calculation_timeout` | Calculation exceeded `CALC_TIMEOUT_SECONDS` |

Every response carries an `X-Request-ID` header. Send your own `X-Request-ID` to propagate a trace id; otherwise one is generated.
Use it to find the matching log line.

---

## 3. Input

All endpoints except `/std_enthalpy_calc` take:

| Field | Type | Rules |
|---|---|---|
| `T` | number | Kelvin, `> 0`, finite. Default 423.15 |
| `P` | number | Pascal, `> 0`, finite. Default 29411.81 |
| `components` | list of strings | 1 to `MAX_COMPONENTS` (20) entries; names or CAS numbers; trimmed; not empty; **no duplicates** (case-insensitive) |
| `zs` | list of numbers | Same length as `components`; finite; none negative; sum `> 0`. Rescaled to sum 1 – `meta.zs_normalized` tells you if that happened |

`/std_enthalpy_calc` takes only `components` and `zs` (it is defined at fixed 298.15 K / 101325 Pa).
Extra fields such as `T`/`P` sent to it are ignored, so old clients keep working.

Example:
```bash
curl -X POST http://SERVER:8000/cp_calc -H "Content-Type: application/json" \
  -d '{"T": 350, "P": 101325, "components": ["water","hexane"], "zs": [0.5,0.5]}'
```

---

## 4. Endpoints and output

Fractions are mole fractions. Values are **not rounded** any more (clients can round for display).

| Endpoint | `data` fields | Units |
|---|---|---|
| `POST /cp_calc` | `Cp_liquid`, `Cp_vapor`, `Cp_mix`, `Vapor_fraction`, `Liquid_fraction` | J/mol/K |
| `POST /density_calc` | `rho_mix`, `phase` | kg/m³ |
| `POST /enthalpy_calc` | `H_mix_molar`, `H_mix_mass` | J/mol, J/kg |
| `POST /mw_calc` | `MW_liquid`, `MW_vapor`, `MW_avg` | g/mol |
| `POST /vf_calc` | `Vapor_fraction`, `Liquid_fraction` | – |
| `POST /std_enthalpy_calc` | `H_mix_std_molar`, `H_mix_std_mass` | J/mol, J/kg |
| `POST /triphase_cp_calc` | `Cp_aqueous`, `Cp_organic`, `Cp_vapor`, `Cp_mix` | J/mol/K |
| `POST /triphase_mw_calc` | `MW_aqueous`, `MW_organic`, `MW_vapor`, `MW_mix` | g/mol |
| `POST /triphase_vf_calc` | `vapor_fraction`, `aqueous_fraction`, `organic_fraction`, `liquid_fraction`, `water_in_liquid`, `organic_in_liquid` | – |
| `GET /health` | `status`, `version` | – |

A phase that is not present returns `null` (e.g. `Cp_liquid: null` for a pure vapor) rather than an invented number or an error.
The `units` object in each response is the authoritative unit list.

### How the triphase endpoints work (important limitation)
`thermo.Mixture` performs a **vapor–liquid** flash only. The liquid is then split by an approximation:
*aqueous phase = pure water, organic phase = all other components (renormalised)*. This is the same
approximation the original code made; it is now documented. It is only valid for essentially immiscible water/organic systems.
For a rigorous VLLE result you would need `thermo.FlashVLN` with an activity-coefficient or EOS model – a possible future upgrade.

---

## 5. Changes versus the original code

### 5.1 Bugs fixed

| # | Original problem | Fix |
|---|---|---|
| 1 | **Wrong unit labels.** `"MW ... kg/mol"` returned g/mol; `"H_mix J/kg"` returned J/mol. | Units corrected and returned in `units`. Enthalpy is given both molar (J/mol) and mass (J/kg, `Hm / MW * 1000`). |
| 2 | **`/std_enthalpy_calc` used the wrong quantity.** `Chemical.Hf` in thermo 0.6.1 is *mass-based* (J/kg; water = −1.59e7), but it was mixed with mole fractions and labelled J/kg. | Uses `Chemical.Hfm` (J/mol). A 50/50 methane/ethane mixture now gives −79.45 kJ/mol (checked by a test). |
| 3 | **A missing formation enthalpy silently became 0**, producing a wrong answer with no warning (`missing_Hf` was collected and never used). | Returns `422 property_unavailable` naming the components. |
| 4 | **`/triphase_cp_calc` crashed (`UnboundLocalError`)** whenever there was no liquid, or no organic part. | Every phase value is explicitly `null` when its phase is absent. |
| 5 | **`/triphase_vf_calc` crashed** the same way (`x_organic_sum` undefined). | Same fix; the response is always complete. |
| 6 | **Triphase Cp mixed units**: mass-based Cp (J/kg/K) was averaged with mole fractions, then multiplied by the mixture MW – dimensionally wrong. | Each component Cp is converted to molar (`Cp × MW / 1000`) *before* mole-fraction averaging. Cross-check: for water/hexane liquid at 350 K, `Cp_mix` = 146.03, identical to thermo's own `Cplm`. |
| 7 | **`/triphase_vf_calc` "aqueous fraction" was not a phase fraction** (it was water's mole fraction within the liquid). | `aqueous_fraction` / `organic_fraction` are now fractions of the *total* mixture and sum with `vapor_fraction` to 1. The old values remain available as `water_in_liquid` / `organic_in_liquid`. |
| 8 | **Water hard-coded as CAS `7732-18-5`**; passing `"water"` gave a cryptic "is not in list" error. | Components are resolved to CAS first, so `"water"`, `"Water"` and `"7732-18-5"` all work. No water gives a clear `water_required` error. |
| 9 | **`/cp_calc` failed for single-phase states** because thermo returns `None` for the absent phase's Cp. | Only present phases are used; the absent one is `null`. |
| 10 | **`/mw_calc` reported 0.0 as the liquid MW when no liquid exists**, and had an `is None` check that could never trigger. | Absent phase gives `null`. Dead code removed. |
| 11 | **Every error returned HTTP 200** with `{"status":"error"}`. Clients and monitoring could not detect failures. | Proper status codes (401/404/405/422/500/504) and one error envelope. |
| 12 | **Internal errors leaked raw exception text** (`str(e)`) to callers. | Unexpected errors give a generic message plus `request_id`; details go only to the server log. |
| 13 | **Unneeded flash for density/enthalpy**, and an unused `Mixture` in `/std_enthalpy_calc`. | Flash only when a phase split is needed; unused objects removed. |
| 14 | **Results rounded to 2 decimals** (e.g. MW in kg/mol rounded to 0.02). | No rounding. |

### 5.2 Added (production standards)

- **Input validation** (§3): positive/finite T and P, component-count limit, duplicate detection, composition checks – all returning field-level messages.
- **Consistent response envelope** with `units` and `meta`; typed Pydantic `response_model`s so `/docs` shows exact schemas.
- **Error handling**: domain exceptions (`app/errors.py`) plus global handlers for validation, HTTP, domain and unexpected errors.
- **Request ID and request logging** middleware (one log line per request: method, path, status, ms, id).
- **Timeout** per calculation (default 30 s, then 504). Calculations run in a worker thread so slow flashes do not block the event loop.
- **Caching** of component lookups (`identify`, `lru_cache`) – repeated names no longer re-query thermo's databases.
- **Optional API-key auth** (`X-API-Key`), **CORS** control, **`/health`** endpoint.
- **Tests**: 29 tests covering every endpoint, single-phase and liquid states, all validation rules, error codes, auth, request-id echo, and masking of unexpected errors.
- **Separation of concerns**: the calculation module can be imported and tested without FastAPI.

### 5.3 Breaking changes for existing clients

The success body is restructured, so **clients that parse the old responses must be updated**:

| Old | New |
|---|---|
| `"rho_mix kg/m^3": 0.19` | `data.rho_mix` (units in `units`) |
| `"H_mix J/kg": 6185.96` (really J/mol) | `data.H_mix_molar` (J/mol) and `data.H_mix_mass` (J/kg) |
| `"MW_avg kg/mol": 23.06` (really g/mol) | `data.MW_avg` (g/mol) |
| `"Cp_aqueous J/mol-K"` etc. | `data.Cp_aqueous` etc. |
| `"vapor fraction"`, `"aqueous fraction"` … | `data.vapor_fraction`, `data.aqueous_fraction` … (meaning changed, see fix 7) |
| HTTP 200 + `{"status":"error","message":...}` | HTTP 4xx/5xx + `{"status":"error","error":{code,message,details}}` |
| Values rounded to 2 dp | Full precision |
| `/cp_calc` had `"status": "success"` at top level only | Every endpoint has it |

Endpoint paths, and the `T`, `P`, `components`, `zs` request fields (with their defaults), are unchanged.
Duplicate components and empty strings are now rejected (previously they were passed to thermo).

---

## 6. Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | *(unset)* | If set, all calculation endpoints require header `X-API-Key: <value>`. `/health` and `/docs` stay open. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins, e.g. `https://app.example.com`. Restrict this in production. |
| `CALC_TIMEOUT_SECONDS` | `30` | Per-calculation limit. |
| `MAX_COMPONENTS` | `20` | Max components per request. |
| `LOG_LEVEL` | `INFO` | Python log level. |

No deployment files (Dockerfile, process-manager config, etc.) were created, as requested.

---

## 7. Known limitations / next steps

- **A timeout does not kill the thread.** A timed-out thermo calculation keeps running in its worker thread until it finishes; the client just gets its 504 sooner. If you expect pathological inputs, run several uvicorn workers (`--workers N`) or move to a process pool.
- **Triphase is an approximation** (see §4).
- **No `requirements.txt`** was added (you asked for no deployment files). Tested with thermo 0.6.1, fastapi 0.142.2, pydantic 2.13.5, numpy 2.5.3, uvicorn, plus pytest and httpx for the tests. Pin these on your server.
- The enthalpy reference state is thermo's, so absolute `H` values are only meaningful as differences.
- Names thermo cannot find are rejected with `unknown_component`; try your real component list once through `/docs`.
