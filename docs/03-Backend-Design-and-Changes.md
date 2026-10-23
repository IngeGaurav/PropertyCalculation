# Thermo Property API — Backend Design & Change Record

| | |
|---|---|
| **Version** | 2.3.0 |
| **Audience** | Developers maintaining or extending the backend |
| **Related documents** | [01-Deployment-Guide.md](01-Deployment-Guide.md), [02-API-Reference.md](02-API-Reference.md) |

---

## Contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Technology stack](#2-technology-stack)
3. [Code structure](#3-code-structure)
4. [Design principles](#4-design-principles)
5. [Error handling design](#5-error-handling-design)
6. [Defects corrected in 2.0.0](#6-defects-corrected-in-200)
7. [Differences from the original (1.x) API](#7-differences-from-the-original-1x-api)
8. [Testing](#8-testing)
9. [Local development](#9-local-development)
10. [Extending the API](#10-extending-the-api)
11. [Known limitations](#11-known-limitations)
12. [Release 2.1.0: EOS Stream API and API documentation](#12-release-210-eos-stream-api-and-api-documentation)
13. [Release 2.2.0: Enthalpy API](#13-release-220-enthalpy-api)
14. [Release 2.3.0: Vent API](#14-release-230-vent-api)

---

## 1. Purpose and scope

The backend exposes thermodynamic property calculations for mixtures as a JSON HTTP API. Version 2.0.0 is a restructuring of the original single-file implementation (`main.py`, version 1.x) into a maintainable, testable service with consistent request/response handling, validation and error reporting. It also corrected several calculation and unit defects (§6).

---

## 2. Technology stack

| Layer | Technology | Version tested |
|---|---|---|
| Language | Python | 3.13 (server); also 3.14 (development) |
| Web framework | FastAPI | 0.142.2 |
| ASGI server | uvicorn | 0.54.0 |
| Data validation | Pydantic | 2.13.5 |
| Thermodynamics | thermo (with chemicals, fluids) | 0.6.1 (chemicals 1.5.2, fluids 1.3.1) |
| Numerics | numpy, scipy | 2.5.3, 1.18.1 |
| Tests | pytest, httpx | 9.1.1, 0.28.1 |

The `thermo` version matters: the code relies on 0.6.x behaviour (for example `Chemical.Hf` being mass-based while `Chemical.Hfm` is molar, and `Chemical.Cpl`/`Cpg` being mass-based). Re-run the test suite after any upgrade.

---

## 3. Code structure

```
Backend/
├── main.py                 Application entry point
├── requirements.txt        Pinned runtime dependencies
├── requirements-dev.txt    Runtime + test dependencies
├── app/
│   ├── __init__.py
│   ├── config.py           Settings from environment variables
│   ├── errors.py           Domain exceptions (HTTP status + stable error code)
│   ├── schemas.py          Request models, response models, unit tables
│   ├── thermo_service.py   Property API calculations: vapor-liquid model (no FastAPI imports)
│   ├── eos_service.py      EOS Stream API calculation, plus the shared model cache and parameter helpers (no FastAPI imports)
│   ├── enthalpy_service.py Enthalpy API calculation: inlet/outlet flash and heat duty (no FastAPI imports)
│   ├── vent_service.py     Vent API calculation: polynomial fit of flow versus opening (numpy only, no FastAPI imports)
│   ├── api_docs.py         Text and examples shown in the generated API documentation
│   └── routes.py           The ten calculation endpoints, API-key check, timeout wrapper
└── tests/
    ├── test_api.py         Property APIs and common behaviour
    ├── test_eos.py         EOS Stream API
    ├── test_enthalpy.py    Enthalpy API
    ├── test_vent.py        Vent API
    └── test_openapi.py     The generated API documentation (132 tests in total)
```

| Module | Responsibility | Depends on |
|---|---|---|
| `main.py` | Creates the app; request-id/timing/logging middleware; CORS; global exception handlers; `/health`; start-up warm-up | all `app` modules |
| `app/config.py` | Reads settings (`API_KEY`, `CORS_ORIGINS`, `CALC_TIMEOUT_SECONDS`, `MAX_COMPONENTS`, `LOG_LEVEL`) once at import | – |
| `app/errors.py` | `ApiError` base class and subclasses; each carries `status_code` and `code` | – |
| `app/schemas.py` | `Composition` (shared validation), `CPCalcInput`, one response model per endpoint, `ApiResponse`/`ErrorResponse`, unit dictionaries | `config`, pydantic |
| `app/thermo_service.py` | Component lookup and caching (`identify`), vapor-liquid flash, the Property API calculations | `errors`, `schemas`, thermo |
| `app/eos_service.py` | EOS model cache (shared), kij and critical-property helpers (shared), three-phase flash and phase extraction for `/eos_stream_calc` | `errors`, `schemas`, `thermo_service.identify`, thermo |
| `app/vent_service.py` | Polynomial least-squares fit of flow versus opening, LINEST-equivalent statistics, flow estimates for `/vent_flow_calc` | `errors`, `schemas`, numpy |
| `app/enthalpy_service.py` | Pure-component and multi-component flash at an inlet and an outlet condition; enthalpy and heat duty for `/eos_enthalpy_calc` | `eos_service`, `errors`, `schemas`, `thermo_service.identify`, thermo |
| `app/api_docs.py` | Titles, tag descriptions, endpoint descriptions and request/response examples for Swagger / OpenAPI | – |
| `app/routes.py` | Registers endpoints with their documentation; runs calculations in a thread pool with a timeout; builds the envelope | `schemas`, `thermo_service`, `eos_service`, `api_docs`, `config`, `errors` |

**Data flow for one request:** `routes._execute` → (thread) `thermo_service.<function>(request)` or `eos_service.eos_stream(request)` → returns a response-model instance → wrapped with `units` and `meta` → serialised by FastAPI.

**Start-up:** `main.py` defines a lifespan handler that performs one default calculation per worker, so the `thermo` databases are loaded before the first user request.

---

## 4. Design principles

| Principle | Implementation |
|---|---|
| **Validate once** | All composition rules live in `schemas.Composition`; endpoints cannot forget a check. |
| **Thermodynamics separate from HTTP** | `thermo_service.py` has no FastAPI imports and can be tested or reused on its own. |
| **One response shape** | Every calculation returns `{status, data, units, meta}`; every error returns `{status, error, request_id}`. |
| **Typed contracts** | Each endpoint has a Pydantic response model, so the OpenAPI/Swagger documentation shows exact fields. |
| **No silent assumptions** | Missing data raises `property_unavailable` instead of being replaced by 0. |
| **Explicit absence** | A phase that does not exist returns `null`, never a made-up number. |
| **Do not leak internals** | Unexpected exceptions are logged with a traceback and returned only as a generic message plus `request_id`. |
| **Do not block the event loop** | Calculations run in a worker thread with a time limit (`CALC_TIMEOUT_SECONDS`, default 30 s). |
| **Cache the expensive lookups** | Component identification (`identify`) is cached with `lru_cache`. |
| **Configurable without code changes** | Settings come from environment variables. |

---

## 5. Error handling design

| Mechanism | Behaviour |
|---|---|
| `ApiError` subclasses (`errors.py`) | Raised by the calculation code; the handler converts them to the error envelope with the proper HTTP status. |
| Validation handler | Converts FastAPI/Pydantic validation errors into `validation_error` with a `{field, message}` list. |
| HTTP handler | 401, 404 and 405 use the same envelope (`unauthorized`, `not_found`, `method_not_allowed`). |
| Catch-all handler | Any other exception → `500 internal_error`, traceback logged with the request id. |
| Timeout | `asyncio.wait_for` around the thread-pool call → `504 calculation_timeout`. |

Error codes and their causes are listed in the API Reference (§6).

---

## 6. Defects corrected in 2.0.0

| # | Original behaviour (1.x) | Correction |
|---|---|---|
| 1 | Unit labels were wrong: molecular weights labelled `kg/mol` were g/mol; enthalpy labelled `J/kg` was J/mol. | Units corrected and returned in `units`. Enthalpy is provided as molar (J/mol) and mass (J/kg). |
| 2 | **Standard enthalpy used the wrong quantity.** `Chemical.Hf` in thermo 0.6.1 is mass-based (J/kg) but was combined with mole fractions. | Corrected in 2.0.0. The endpoint was removed in 2.1.0 and will be re-added with the new enthalpy logic. |
| 3 | A missing formation enthalpy silently became 0, producing a wrong result with no warning. | Corrected in 2.0.0 (explicit error / option). Removed together with the endpoint in 2.1.0. |
| 4 | `/triphase_cp_calc` crashed (`UnboundLocalError`) when there was no liquid or no organic part. | Every phase value is explicitly `null` when its phase is absent. |
| 5 | `/triphase_vf_calc` crashed in the same situations. | Same fix; the response is always complete. |
| 6 | Triphase heat capacity mixed units: mass-based Cp averaged with mole fractions and then multiplied by the mixture molecular weight. | Each component's Cp is converted to molar (`Cp × MW / 1000`) before mole-fraction averaging. Result agrees with `/cp_calc`. |
| 7 | The triphase "aqueous fraction" was the water mole fraction in the liquid, not a phase fraction. | `aqueous_fraction` and `organic_fraction` are now shares of the total mixture and sum with `vapor_fraction` to 1; the old quantities remain as `water_in_liquid` / `organic_in_liquid`. |
| 8 | Water was hard-coded as CAS `7732-18-5`; sending `"water"` produced a cryptic error. | Components are resolved to CAS first; name or CAS both work; absence gives `water_required`. |
| 9 | `/cp_calc` failed for single-phase states (thermo returns no heat capacity for an absent phase). | Only present phases are used; the absent one is `null`. |
| 10 | `/mw_calc` reported `0.0` for a non-existent liquid and contained an unreachable `None` check. | Absent phase → `null`; dead code removed. |
| 11 | Every error returned HTTP 200. | Proper HTTP status codes and one error envelope. |
| 12 | Raw exception text was returned to clients. | Generic message plus `request_id`; details only in the log. |
| 13 | Unneeded flash calculations (density, enthalpy) and an unused `Mixture` object. | Flash only where a phase split is required. |
| 14 | Results rounded to two decimals (for example molecular weights in kg/mol rounded to 0.02). | No rounding. |
| 15 | Validation code (about 20 lines) duplicated in all nine endpoints. | Single shared validator (`Composition`). |

---

## 7. Differences from the original (1.x) API

The success body is restructured, so **clients written for 1.x must be updated**. Endpoint paths and the request fields `T`, `P`, `components`, `zs` (with their defaults) are unchanged.

| Original (1.x) | Current (2.0.0) |
|---|---|
| `{"rho_mix kg/m^3": 0.19}` | `{"status":"success","data":{"rho_mix":0.19,"phase":"g"},"units":{...},"meta":{...}}` |
| `"H_mix J/kg": 6185.96` (actually J/mol) | `data.H_mix_molar` (J/mol) and `data.H_mix_mass` (J/kg) |
| `"MW_avg kg/mol": 23.06` (actually g/mol) | `data.MW_avg` (g/mol) |
| `"Cp_aqueous J/mol-K"` and similar keys with units in the name | `data.Cp_aqueous`; units in `units` |
| `"vapor fraction"`, `"aqueous fraction"` (different meaning) | `data.vapor_fraction`, `data.aqueous_fraction` (share of total mixture) |
| HTTP 200 with `{"status":"error","message":...}` | HTTP 4xx/5xx with `{"status":"error","error":{code,message,details},"request_id":...}` |
| Values rounded to two decimals | Full precision |
| Duplicate or empty component names accepted | Rejected with `validation_error` |
| `/enthalpy_calc`, `/std_enthalpy_calc` | Removed in 2.1.0 |

---

## 8. Testing

The suite (`Backend/tests/`, 132 tests in five files) uses FastAPI's `TestClient` and covers:

| Area | Tests |
|---|---|
| Each Property API, success | Basic endpoints, single-phase and liquid states, triphase endpoints |
| Physical consistency | MW in g/mol, fractions sum to 1, phases `null` when absent |
| Water handling | By name or CAS; missing water error |
| Validation | Mismatched lengths, negative or zero fractions, `T`/`P` ≤ 0, empty list, duplicates, wrong types, malformed JSON |
| Normalisation | Fractions not summing to 1 are rescaled and flagged |
| Errors | Unknown component, 404, 405, response envelope, masking of unexpected errors |
| Request id | Echoed in header and `meta` |
| API key | Enforced when configured; `/health` stays open |
| Many components | Large component lists accepted |
| EOS Stream API | Vapor-only, liquid-liquid, vapor+aqueous and all-vapor cases; phase fractions sum to 1; names and CAS give identical results; component order and zero fractions do not change the result; duplicates merged; single component; flash failure becomes `422`; cache reuse and bound; the 48-component reference stream matches the reference script |
| Enthalpy API | Agreement with the reference script for five cases (the lead's C2 stream, pure ethylene, water vaporisation, water/hexane, no change); duty equals outlet minus inlet; molar and mass basis agree; swapping inlet and outlet reverses the sign; zero entries skipped; mol % equals fractions; names, CAS and order equivalent; duplicates merged; all validation rules; flash failure names the condition; cache reuse; the 48-component list |
| Vent API | Agreement with the reference module (the degree-capped reference data, a quadratic and a cubic fit); the exact-line, constant-flow, floor and unclipped cases; coefficient order and values against `numpy.polyfit`; standard errors against the textbook formula; clipping, extrapolation flags and the flow floor; undefined statistics are `null` and every response is strict JSON; degree-cap and extrapolation warnings; envelope without `zs_normalized`; all validation rules including infinite numbers; `fit_failed` for too few distinct openings; a 5000-point data set |
| Generated documentation | Exact set of endpoints; no enthalpy endpoint; every endpoint has tag, summary, description, operation id, request example, success example and documented errors; the documented examples equal the real responses |

Run: `cd Backend` then `python -m pytest -q tests` (expected `132 passed`). The tests read settings from the environment, so run them where `API_KEY` and `CORS_ORIGINS` are not set.

---

## 9. Local development

```bat
cd Backend
python -m venv ..\venv
..\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\venv\Scripts\python.exe -m pytest -q tests
..\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the interactive documentation. Open `Frontend\index.html` in a browser; when opened as a file it targets `http://localhost:8000` by default. (`--reload` restarts the server on file changes; it is for development only.)

---

## 10. Extending the API

To add a new calculation endpoint:

1. **Schema** — in `app/schemas.py` add a response model (fields, `null` where a phase may be absent) and a units dictionary.
2. **Calculation** — in `app/thermo_service.py` add a function taking `CPCalcInput` and returning the response model. Use `flash()` for phase information and `_need()` to turn missing data into `property_unavailable`.
3. **Documentation** — in `app/api_docs.py` add an `EndpointDoc` (tag, summary, description, request example, example `data`) to `ENDPOINT_DOCS`.
4. **Route** — in `app/routes.py` add one `_endpoint("/new_calc", svc.new_function, s.NewData, s.NEW_UNITS, C)` line.
5. **Tests** — add success and failure tests (`tests/test_api.py` or `tests/test_eos.py`); `tests/test_openapi.py` checks the documentation of every endpoint automatically.
6. **Reference and front end** — add a section to the API Reference and, if the web tester should expose it, an entry in the `ENDPOINTS` list in `Frontend/index.html`.
7. **Release** — increase `version` in `main.py` and follow the release procedure in the Deployment Guide (§9).

---

## 11. Known limitations

| Limitation | Detail |
|---|---|
| Triphase approximation | `thermo.Mixture` performs only a vapor–liquid flash; the liquid is split into pure-water and organic parts. Not valid where water and organics are mutually soluble. |
| Timed-out calculations | The client receives `504`, but the worker thread keeps running until the calculation ends. |
| Ideal-gas vapor heat capacity | No real-gas correction at high pressure. |
| Data coverage | Depends on `thermo`'s databases: some chemicals lack data needed by a model (reported as `property_unavailable`). |
| EOS model build time | The first `/eos_stream_calc` request for a new set of components builds the model (about 3 s for 24 components). Models are cached per worker process (32 sets, least recently used dropped). |
| Ethylene / ethane parameter | The Enthalpy API uses the calibrated interaction parameter 0.015 for ethylene/ethane; the EOS Stream API uses the database value (0.0078). The two EOS-based groups therefore differ slightly for streams that contain both. |
| Vent fit conditioning | The fit uses the Vandermonde matrix as Excel LINEST does. With large openings and a high degree it is poorly conditioned (coefficients and standard errors lose precision; fitted flows stay accurate). Degree is limited to 10. |
| EOS large streams | Calculation time grows steeply with the number of components that have a non-zero mole fraction. A 48-component stream takes 17 to 34 s if zero fractions are not removed; the API removes them. A stream with many non-zero components can still reach the 30 s limit. |

---

## 12. Release 2.1.0: EOS Stream API and API documentation

### 12.1 What was added

| Item | Detail |
| --- | --- |
| `POST /eos_stream_calc` | One call returns the phase situation (`case`), `V`, `L`, and for the vapor, aqueous and organic phases their `beta`, `MW`, `Cp`, `rho_mass` and `rho_molar_kmol_m3`, plus the `mixture` values. |
| Same API structure | Same request model, response envelope (`status`, `data`, `units`, `meta`), validation, error codes, request ids and 30 s limit as the Property APIs. |
| Documentation | Two groups (*Property APIs*, *EOS Stream API*) and *System*; every endpoint has a summary, a description, a request example and a response example; `/health` has a response model. |
| Web tester | Two tabs at the top. The EOS tab can also call the Property APIs with the same input and show a side-by-side comparison. |

### 12.2 What was removed

`POST /enthalpy_calc` and `POST /std_enthalpy_calc`, with their schemas, the `allow_missing_hf` option and the formation-enthalpy lookup. They return `404`. Enthalpy will be reintroduced with new logic.

### 12.3 The EOS calculation

The reference implementation (one flash with Peng-Robinson, binary interaction parameters from the ChemSep PR database and `FlashVLN` with two liquid phases) was adopted unchanged in its thermodynamics. Changes made for use behind an API:

| Reference behaviour | Change | Why |
| --- | --- | --- |
| Components with a mole fraction of 0 are flashed | They are removed before the flash | The 48-component reference stream took 17 to 34 s per call and 0.16 s once the 24 zero-fraction components were removed, with identical results |
| Water recognised only by CAS number | Every component is resolved to its CAS number first | Phase labelling no longer depends on how a component is spelled |
| Cache keyed by the component list in request order | Keyed by the sorted CAS tuple; bounded to 32 entries (least recently used); built under a lock | Order does not cause rebuilds; memory is bounded; no duplicate builds |
| Shared flasher used by concurrent calls | One flash at a time per flasher (lock) | The flasher objects are not documented as thread-safe |
| Raw Python exceptions | `unknown_component`, `property_unavailable`, `flash_failed`, `calculation_failed` | Same error contract as the other endpoints |
| No input validation | The shared request model | `T` and `P` above 0, equal list lengths, no negative fractions |
| The same chemical under two names | Merged | Avoids a singular model |

### 12.4 Comparison of the two approaches

For single-phase gases the Property APIs and the EOS Stream API agree closely (methane/ethane, 423.15 K, 29.4 kPa: Cp 55.17 and 55.19 J/mol/K; density 0.1927 and 0.1928 kg/m³). For water with hydrocarbons near boiling conditions they can differ greatly, and the EOS result is the physically consistent one. For water/hexane 50/50 at 1 atm:

| T | Property APIs | EOS Stream API |
| --- | --- | --- |
| 300 K | one liquid | two liquids (aqueous 49 %, organic 51 %) |
| 351 K | all liquid (V = 0) | vapor 83 % plus aqueous liquid. Hexane boils at 342 K, so most of the mixture is vapor. |
| 357 K | 22.6 % vapor | all vapor. Water would need a partial pressure of 0.5 atm, below its saturation pressure of about 0.57 atm, so it does not condense. |

---

## 13. Release 2.2.0: Enthalpy API

### 13.1 What was added

| Item | Detail |
| --- | --- |
| `POST /eos_enthalpy_calc` | Enthalpy of one stream at an inlet (`T_in`, `P_in`) and an outlet (`T_out`, `P_out`) condition and the heat duty between them. Per condition: `vapor_fraction`, `molecular_weight`, `enthalpy_molar` (kJ/mol), `enthalpy_mass` (kJ/kg). Duty: `heat_duty_molar` (kJ/mol) and `sp_duty` (kJ/kg), outlet minus inlet. |
| Same API structure | Same envelope, validation, error codes, request ids, time limit, documentation (tag *Enthalpy API*, description, request and response examples) and tests as the other groups. |
| Web tester | Third tab with the four inlet/outlet fields, five examples (including heating, vaporisation, cooling and the 48-component list) and a result view that highlights the duty. |

### 13.2 The calculation

The reference implementation (a script supplied by the project lead) was adopted with its thermodynamics unchanged:

| Case | Method |
| --- | --- |
| One active component | `FlashPureVLS` with a Peng-Robinson gas and liquid |
| Several active components | `FlashVLN` with two liquid templates (so an aqueous/organic split is found), kij from the ChemSep PR database, 0 for pairs without data |
| Ethylene and ethane both present | kij of that pair set to 0.015 (calibrated; the database value 0.0078 gave a duty about 42 % off against the plant reference, 0.015 about 9 %) |

Changes made for use behind an API:

| Reference behaviour | Change | Why |
| --- | --- | --- |
| Zero and negligible entries stay in the component list until they are filtered by index | Components with a normalised mole fraction below 1e-12 are removed before the model is built; the same chemical given twice is merged | Speed (the 48-component list becomes 10 components) and a stable cache key |
| Components must be CAS numbers | Every component is resolved to its CAS number first | Names work; water and ethylene/ethane are always recognised |
| Negative mole fractions are silently set to 0 | Rejected with `validation_error` | A negative fraction is an input error, not something to hide |
| Script, printed output | Structured response with units; errors as `ApiError` subclasses (`unknown_component`, `property_unavailable`, `flash_failed`, `calculation_failed`) | Same contract as the other endpoints |
| No limits | The common 30 s limit applies | Protects the service |
| A flash failure raises a Python exception | `flash_failed`, with the failing condition (inlet or outlet) named | Easier diagnosis |

Verification: for five cases the API values equal the values printed by the reference script to full precision (relative difference below 1e-6 is asserted in `tests/test_enthalpy.py`).

### 13.3 Shared infrastructure

The EOS model cache (64 entries, least recently used dropped, thread-safe, one flash at a time per model) and the helpers that build the Peng-Robinson parameters (`eos_kwargs_for`, `load_constants`) were moved to be shared by `eos_service` and `enthalpy_service`. The behaviour of the EOS Stream API is unchanged (all its tests pass unmodified).

---

## 14. Release 2.3.0: Vent API

### 14.1 What was added

| Item | Detail |
| --- | --- |
| `POST /vent_flow_calc` | Polynomial fit of flow versus valve opening (Excel `LINEST(Flow, Opening^{1..degree}, TRUE, TRUE)` equivalent) and flow estimates at further openings. Result: `fit` (equation, `terms` highest power first with standard errors, R², standard error of the estimate, F, residual degrees of freedom, sums of squares, fitted opening range), `estimates` (opening, opening used, flow, extrapolation flag, floor flag) and `warnings`. |
| Same API structure | Validation, standard error envelope and codes, request ids, time limit, documentation (tag *Vent API*) and tests as the other groups. The success envelope carries `meta.request_id` and `meta.elapsed_ms` only, because there is no composition (`zs_normalized` does not apply). |
| New error code | `fit_failed` (HTTP 422): fewer different opening values than the degree needs, a non-converging fit or non-finite coefficients. |
| Web tester | Fourth tab with a points table, paste-arrays panel, estimate openings, three examples, and result tables for the fit, coefficients and estimates, with warnings and extrapolation flags. |

### 14.2 The calculation

The reference module supplied by the project lead (`flow_vs_opening_estimator.py`: `fit_flow_vs_opening`, `estimate_flow`) was adopted with its numerics unchanged: Vandermonde design matrix, `numpy.linalg.lstsq`, coefficient standard errors from `(XᵀX)⁻¹`, degree capped at `n − 2`, opening clamped to the fitted range, flow floored at `min_flow`. For eight cases (degree capped, quadratic, cubic, exact line, constant flow, negative flow with floor, unclipped, floored) the API values equal the reference to full precision; the capped, quadratic and cubic cases are asserted in `tests/test_vent.py`.

Changes made for use behind an API:

| Reference behaviour | Change | Why |
| --- | --- | --- |
| Undefined statistics are NaN, an exact fit gives F = +inf | Returned as `null` | JSON can not carry NaN or infinity; a strict client would fail |
| F statistic from rounding noise (−0.5 for constant flow, 7.7e30 for an exact line) | `null`, with an explanatory warning | The value is meaningless |
| A rank-deficient fit (too few distinct openings) silently returns a minimum-norm solution | `fit_failed` with the numbers needed | A hidden non-unique fit is worse than an error |
| `degree` has no upper limit | 1 to 10 | Higher degrees are numerically meaningless and slow with many points |
| Plain function arguments | Request model: lengths equal, at least 3 finite points, at most 10 000 values per list | Same validation contract as the other endpoints |
| Capping the degree is silent | `degree_requested`, `degree_used`, `degree_capped` and a warning | The caller must know the fit differs from the request |
| Extrapolation is a returned boolean | Per estimate: `extrapolated`, `opening_used`, `floor_applied`, plus summary warnings | The caller sees exactly what was evaluated |
| Printed text | Structured response with units | Same contract as the other endpoints |
