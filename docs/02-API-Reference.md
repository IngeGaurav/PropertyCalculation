# Thermo Property API — API Reference

| | |
|---|---|
| **API version** | 2.3.0 |
| **Base URL** | `http://192.168.11.216:4300/api` |
| **Interactive documentation** | `http://192.168.11.216:4300/api/docs` (Swagger UI) · `http://192.168.11.216:4300/api/openapi.json` (machine-readable schema) |
| **Protocol / format** | HTTP, JSON (UTF-8) |
| **Access** | Company LAN or VPN |
| **Authentication** | None in the current deployment (an optional API key can be enabled; see §2.3) |

---

## Contents

1. [Overview](#1-overview)
2. [Conventions](#2-conventions)
3. [Request and response lifecycle](#3-request-and-response-lifecycle)
4. [Common request model](#4-common-request-model)
5. [Common response format](#5-common-response-format)
6. [Error reference](#6-error-reference)
7. [Property APIs](#7-property-apis)
   - [7.1 Heat capacity — `POST /cp_calc`](#71-heat-capacity--post-cp_calc)
   - [7.2 Density — `POST /density_calc`](#72-density--post-density_calc)
   - [7.3 Molecular weight — `POST /mw_calc`](#73-molecular-weight--post-mw_calc)
   - [7.4 Vapor fraction — `POST /vf_calc`](#74-vapor-fraction--post-vf_calc)
   - [7.5 Heat capacity: vapor / aqueous / organic — `POST /triphase_cp_calc`](#75-heat-capacity-vapor--aqueous--organic--post-triphase_cp_calc)
   - [7.6 Molecular weight: vapor / aqueous / organic — `POST /triphase_mw_calc`](#76-molecular-weight-vapor--aqueous--organic--post-triphase_mw_calc)
   - [7.7 Phase fractions: vapor / aqueous / organic — `POST /triphase_vf_calc`](#77-phase-fractions-vapor--aqueous--organic--post-triphase_vf_calc)
8. [EOS Stream API](#8-eos-stream-api)
   - [8.1 Stream properties — `POST /eos_stream_calc`](#81-stream-properties--post-eos_stream_calc)
9. [Enthalpy API](#9-enthalpy-api)
   - [9.1 Enthalpy and heat duty — `POST /eos_enthalpy_calc`](#91-enthalpy-and-heat-duty--post-eos_enthalpy_calc)
10. [Vent API](#10-vent-api)
    - [10.1 Flow versus opening — `POST /vent_flow_calc`](#101-flow-versus-opening--post-vent_flow_calc)
11. [System](#11-system)
    - [11.1 Health check — `GET /health`](#111-health-check--get-health)
12. [Choosing between the approaches](#12-choosing-between-the-approaches)
13. [Calculation notes](#13-calculation-notes)
14. [Client examples](#14-client-examples)
15. [Operational limits](#15-operational-limits)
16. [Version history](#16-version-history)

---

## 1. Overview

The API calculates thermodynamic properties of multi-component mixtures at a given temperature and pressure. It offers **four groups of calculations**. All use the same request conventions and return results in the same response format.

| Group | Endpoints | Approach | Use it when |
| --- | --- | --- | --- |
| **Property APIs** | 7 — one per property | Vapor–liquid equilibrium model | You need one specific property quickly. |
| **EOS Stream API** | 1 — all properties in one call | Peng-Robinson equation of state with a three-phase flash | You need the complete stream result, or the phase behaviour matters (for example water with hydrocarbons). |
| **Enthalpy API** | 1 — enthalpy and heat duty | Peng-Robinson equation of state, flashed at an inlet and an outlet condition | You need the enthalpy of a stream at two conditions and the heat duty between them. |
| **Vent API** | 1 — flow versus valve opening | Polynomial least-squares fit (Excel LINEST equivalent) of your own data points | You have measured the flow at several valve openings and need the flow at other openings. |

| # | Method and path | Group | Returns |
| --- | --- | --- | --- |
| 1 | `POST /cp_calc` | Property APIs | Liquid, vapor and mixture heat capacity; phase fractions |
| 2 | `POST /density_calc` | Property APIs | Mixture density |
| 3 | `POST /mw_calc` | Property APIs | Molecular weight of liquid, vapor and the whole mixture |
| 4 | `POST /vf_calc` | Property APIs | Vapor and liquid fractions |
| 5 | `POST /triphase_cp_calc` | Property APIs | Heat capacity of the vapor, aqueous and organic phases |
| 6 | `POST /triphase_mw_calc` | Property APIs | Molecular weight of the vapor, aqueous and organic phases |
| 7 | `POST /triphase_vf_calc` | Property APIs | Vapor, aqueous and organic fractions of the total mixture |
| 8 | `POST /eos_stream_calc` | EOS Stream API | Phase situation, and for every phase its fraction, molecular weight, heat capacity and density, plus the mixture values |
| 9 | `POST /eos_enthalpy_calc` | Enthalpy API | Vapor fraction, molecular weight and enthalpy at an inlet and an outlet condition, and the heat duty between them |
| 10 | `POST /vent_flow_calc` | Vent API | Polynomial fit of flow versus valve opening (coefficients and statistics) and the flow estimated at further openings |
| 11 | `GET /health` | System | Service status and version |

---

## 2. Conventions

### 2.1 General

| Topic | Rule |
| --- | --- |
| Methods | All calculation endpoints use **`POST`**; `/health` uses `GET`. |
| Content type | The request body is JSON. Send `Content-Type: application/json`. |
| Character encoding | UTF-8. |
| Field names | Case-sensitive (`T` and `P` are upper-case). |
| Unknown fields | Ignored; they do not cause an error. |
| Rounding | Values are returned at full precision. Format them in your client. |
| Absent phase | If a phase does not exist at the given T and P, its values are `null`. They are never `0`, and this is not an error. |

### 2.2 Units

| Quantity | Unit |
| --- | --- |
| Temperature `T` | K |
| Pressure `P` | Pa (1 atm = 101325 Pa) |
| Heat capacity | J/mol/K (and kJ/kg/K where stated) |
| Enthalpy and heat duty | kJ/mol and kJ/kg |
| Valve opening (Vent API) | % |
| Flow (Vent API) | the unit of the flow values you supply; nothing is converted |
| Molecular weight | g/mol |
| Density | kg/m³ (and kmol/m³ where stated) |
| Fractions | mole fraction, dimensionless, 0 to 1 |

Every success response contains a `units` object that states the unit of each returned field.

### 2.3 Authentication

No authentication is required in the current deployment. If an API key is enabled on the server, add the header `X-API-Key: <key>` to every calculation request. A missing or wrong key returns HTTP `401` with error code `unauthorized`. `/health` and the documentation pages stay open.

### 2.4 Request tracing

Every response carries an `X-Request-ID` header and a `request_id` value (in `meta` for successes, at the top level for errors). Quote it when you report a problem, so the request can be found in the server log. You may send your own `X-Request-ID` header; it is returned unchanged.

---

## 3. Request and response lifecycle

Every calculation request passes through the same stages.

| Stage | What happens | Failure result |
| --- | --- | --- |
| 1. Intake | A request id is created, or taken from your `X-Request-ID` header. | n/a |
| 2. Authentication | Checked only if an API key is enabled on the server. | `401 unauthorized` |
| 3. Validation | JSON syntax and field types are checked. T and P must be greater than 0. The two lists must have equal length. Mole fractions must be finite and not negative, and their sum must be greater than 0. Components must not be empty or duplicated. | `422 validation_error` |
| 4. Execution | The calculation runs in a worker thread with a 30 second limit. | `504 calculation_timeout` |
| 5. Component lookup | Each name or CAS number is resolved to a chemical (stream calculations; not used by the Vent API). | `422 unknown_component` |
| 6. Calculation | Property APIs: a vapor–liquid flash. EOS Stream API: a three-phase flash with the equation of state. Enthalpy API: that flash at the inlet and at the outlet condition. Vent API: a least-squares polynomial fit. | `422 flash_failed` |
| 7. Property | The endpoint-specific result is built (see sections 7 to 10). | `422 property_unavailable` or `422 water_required` |
| 8. Response | The result is returned in the standard success envelope (section 5). | n/a |

An unexpected server fault at any stage returns `500 internal_error`. The details are logged on the server, and only the `request_id` is returned to you.

---

## 4. Common request model

The seven Property APIs and the EOS Stream API (sections 7 and 8) take the same four fields. The Enthalpy API (section 9) takes inlet and outlet conditions instead of `T` and `P`. The Vent API (section 10) takes opening and flow data points and has no composition at all. Their fields are listed in their own sections. `components` and `zs` follow the same rules wherever they are used.

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `T` | number | `423.15` | Temperature in K. Must be greater than 0. |
| `P` | number | `29411.81` | Pressure in Pa. Must be greater than 0. |
| `components` | array of strings | `["methane", "ethane"]` | At least one entry. Each entry is a chemical name or a CAS number, for example `"water"` or `"7732-18-5"`. Spaces around a name are removed. Empty strings and duplicates (case-insensitive) are rejected. There is no upper limit on the number of components. |
| `zs` | array of numbers | `[0.5, 0.5]` | Mole fractions in the same order and of the same length as `components`. Each must be finite and at least 0. The sum must be greater than 0. |

Send all four fields explicitly. The defaults exist only for convenience.

**Normalisation.** If the mole fractions do not sum to 1, they are rescaled automatically and `meta` contains `"zs_normalized": true`. A component with a mole fraction of 0 is allowed.

**Minimal request body**

```json
{
  "T": 300,
  "P": 101325,
  "components": ["water", "hexane"],
  "zs": [0.5, 0.5]
}
```

---

## 5. Common response format

### 5.1 Success

HTTP `200`.

```json
{
  "status": "success",
  "data":  { "...endpoint specific fields..." },
  "units": { "...field name": "unit" },
  "meta":  { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 14.2, "zs_normalized": false }
}
```

| Field | Description |
| --- | --- |
| `status` | Always `"success"`. |
| `data` | The results. The fields are listed for each endpoint in sections 7 to 10. |
| `units` | The unit of each field in `data`. |
| `meta.request_id` | Identifier for tracing the request in the server log. |
| `meta.elapsed_ms` | Server-side processing time in milliseconds. |
| `meta.zs_normalized` | `true` if the mole fractions you sent were rescaled to sum to 1. Present only for endpoints that take a composition; the Vent API returns `request_id` and `elapsed_ms` only. |

### 5.2 Error

HTTP `4xx` or `5xx`.

```json
{
  "status": "error",
  "error": {
    "code": "validation_error",
    "message": "Request body is invalid.",
    "details": [ { "field": "T", "message": "Input should be greater than 0" } ]
  },
  "request_id": "a1b2c3d4e5f6"
}
```

| Field | Description |
| --- | --- |
| `status` | Always `"error"`. |
| `error.code` | Stable, machine-readable code (section 6). Use it in your client logic. |
| `error.message` | Human-readable text. Do not parse it. |
| `error.details` | Extra information. For `validation_error` it is a list of `{field, message}`. For other errors it is an object, for example the offending component, or `null`. |
| `request_id` | Identifier for tracing. |

---

## 6. Error reference

| HTTP | `error.code` | Cause | What to do |
| --- | --- | --- | --- |
| 401 | `unauthorized` | An API key is enabled and `X-API-Key` is missing or wrong. | Send the correct key. |
| 404 | `not_found` | Unknown URL. | Check the path, including the `/api` prefix. |
| 405 | `method_not_allowed` | Wrong HTTP method, for example `GET` on a calculation endpoint. | Use `POST`. |
| 422 | `validation_error` | Invalid body: bad JSON, wrong types, T or P not above 0, lists of different length, negative or non-finite fractions, sum of 0, empty or duplicate component. | Read `error.details` and fix the listed fields. |
| 422 | `unknown_component` | A name or CAS number is not known. `details.component` gives the value. | Use another spelling or the CAS number. |
| 422 | `flash_failed` | The phase-equilibrium calculation failed for this state. | Check T, P and composition; try other conditions. |
| 422 | `fit_failed` | The data cannot be fitted (Vent API): fewer different opening values than the degree needs. `details` gives the numbers. | Provide more different openings or lower the degree. |
| 422 | `property_unavailable` | Data needed for the calculation does not exist (for example critical properties of a rarely used chemical). `details.components` lists them. | Remove or replace the component. |
| 422 | `water_required` | A `triphase_*` endpoint was called without water in the mixture. | Include `"water"` or `"7732-18-5"`, or use the EOS Stream API. |
| 500 | `calculation_failed` | The model could not be built. | Report it with the `request_id`. |
| 500 | `internal_error` | Unexpected server error. | Report it with the `request_id`. |
| 504 | `calculation_timeout` | The calculation exceeded the 30 second limit. | Simplify the input or contact the administrator. |

### Real error examples

**Lists of different length** (HTTP 422)

```json
{
  "status": "error",
  "error": {
    "code": "validation_error",
    "message": "Request body is invalid.",
    "details": [ { "field": "body", "message": "components (2) and zs (1) must have the same length" } ]
  },
  "request_id": "a1b2c3d4e5f6"
}
```

**Duplicate component** (HTTP 422)

```json
{
  "status": "error",
  "error": {
    "code": "validation_error",
    "message": "Request body is invalid.",
    "details": [ { "field": "components", "message": "duplicate components are not allowed" } ]
  },
  "request_id": "a1b2c3d4e5f6"
}
```

**Unknown component** (HTTP 422)

```json
{
  "status": "error",
  "error": {
    "code": "unknown_component",
    "message": "Component 'notachemical' was not recognised.",
    "details": { "component": "notachemical" }
  },
  "request_id": "a1b2c3d4e5f6"
}
```

**Water missing for a triphase endpoint** (HTTP 422)

```json
{
  "status": "error",
  "error": {
    "code": "water_required",
    "message": "Triphase endpoints require water in the mixture (use 'water' or '7732-18-5').",
    "details": null
  },
  "request_id": "a1b2c3d4e5f6"
}
```

---

## 7. Property APIs

One endpoint per property, based on a vapor–liquid equilibrium (VLE) model. Each section lists the purpose, the processing, the response fields, and a real example.

Unless stated otherwise the examples use this mixture:

> **Example mixture:** water 50 mol % and hexane 50 mol % at T = 300 K and P = 101325 Pa. At these conditions the model finds a single liquid phase, so vapor values are `null`. Values are rounded to 7 significant digits for readability. The API returns full precision.

---

### 7.1 Heat capacity — `POST /cp_calc`

Returns the heat capacity of the liquid phase, the vapor phase and the whole mixture, together with the phase fractions.

**URL:** `http://192.168.11.216:4300/api/cp_calc`. **Request:** common request model (section 4).

**Processing**

1. The request is validated and the components are resolved.
2. A vapor–liquid flash at T and P gives the vapor fraction V and the liquid fraction L = 1 − V.
3. `Cp_vapor` and `Cp_liquid` are the molar heat capacities of the phases that exist. The vapor value is the ideal-gas value of the vapor composition.
4. `Cp_mix = L · Cp_liquid + V · Cp_vapor`.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `Cp_liquid` | number or `null` | J/mol/K | Liquid-phase heat capacity. `null` if there is no liquid. |
| `Cp_vapor` | number or `null` | J/mol/K | Vapor-phase heat capacity. `null` if there is no vapor. |
| `Cp_mix` | number | J/mol/K | Phase-fraction weighted heat capacity. |
| `Vapor_fraction` | number | mole fraction | V. |
| `Liquid_fraction` | number | mole fraction | L. |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": {
    "Cp_liquid": 135.909,
    "Cp_vapor": null,
    "Cp_mix": 135.909,
    "Vapor_fraction": 0.0,
    "Liquid_fraction": 1.0
  },
  "units": {
    "Cp_liquid": "J/mol/K", "Cp_vapor": "J/mol/K", "Cp_mix": "J/mol/K",
    "Vapor_fraction": "mole fraction", "Liquid_fraction": "mole fraction"
  },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 8.2, "zs_normalized": false }
}
```

**Gas example.** For methane/ethane 50/50 at 423.15 K and 29411.81 Pa no liquid exists, so `Cp_liquid` is `null` and `Cp_vapor` = `Cp_mix` = 55.16653.

---

### 7.2 Density — `POST /density_calc`

Returns the density of the mixture at T and P.

**URL:** `http://192.168.11.216:4300/api/density_calc`. **Request:** common request model (section 4).

**Processing:** the request is validated, the components are resolved, the mixture is built at T and P, and its density and phase state are read.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `rho_mix` | number | kg/m³ | Mixture density. |
| `phase` | string or `null` | n/a | Phase state: `"g"` (gas), `"l"` (liquid) or `"l/g"` (two-phase). |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": { "rho_mix": 694.6499, "phase": "l" },
  "units": { "rho_mix": "kg/m^3" },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 17.1, "zs_normalized": false }
}
```

**Gas example.** Methane/ethane 50/50 at 423.15 K and 29411.81 Pa returns `rho_mix` = 0.1927403 with `phase` = `"g"`.

---

### 7.3 Molecular weight — `POST /mw_calc`

Returns the molecular weight of the liquid phase, the vapor phase and the whole mixture.

**URL:** `http://192.168.11.216:4300/api/mw_calc`. **Request:** common request model (section 4).

**Processing**

1. The request is validated and the components are resolved.
2. A vapor–liquid flash gives the composition of each phase: `x` for the liquid and `y` for the vapor.
3. `MW_liquid = Σ xᵢ · MWᵢ` and `MW_vapor = Σ yᵢ · MWᵢ`. `MW_avg` is the molecular weight of the overall mixture.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `MW_liquid` | number or `null` | g/mol | Liquid phase. `null` if there is no liquid. |
| `MW_vapor` | number or `null` | g/mol | Vapor phase. `null` if there is no vapor. |
| `MW_avg` | number | g/mol | Overall mixture. |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": { "MW_liquid": 52.09532, "MW_vapor": null, "MW_avg": 52.09532 },
  "units": { "MW_liquid": "g/mol", "MW_vapor": "g/mol", "MW_avg": "g/mol" },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 13.3, "zs_normalized": false }
}
```

---

### 7.4 Vapor fraction — `POST /vf_calc`

Returns the fraction of the mixture that is vapor and the fraction that is liquid at T and P.

**URL:** `http://192.168.11.216:4300/api/vf_calc`. **Request:** common request model (section 4).

**Processing:** the request is validated, the components are resolved, and a vapor–liquid flash gives the vapor fraction V. The liquid fraction is L = 1 − V.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `Vapor_fraction` | number | mole fraction | V. 0 means all liquid, 1 means all vapor. |
| `Liquid_fraction` | number | mole fraction | L = 1 − V. |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": { "Vapor_fraction": 0.0, "Liquid_fraction": 1.0 },
  "units": { "Vapor_fraction": "mole fraction", "Liquid_fraction": "mole fraction" },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 35.8, "zs_normalized": false }
}
```

**Unnormalised input.** Sending `"zs": [1, 1]` is accepted. The fractions are rescaled to `[0.5, 0.5]` and `meta` contains `"zs_normalized": true`.

---

### 7.5 Heat capacity: vapor / aqueous / organic — `POST /triphase_cp_calc`

Returns the heat capacity of the vapor, aqueous (water) and organic phases of a mixture that contains water.

**URL:** `http://192.168.11.216:4300/api/triphase_cp_calc`. **Request:** common request model (section 4). **The mixture must contain water** (`"water"` or `"7732-18-5"`).

**Processing**

1. The request is validated, and the call is rejected with `water_required` if water is missing.
2. A vapor–liquid flash gives V, L, the liquid composition `x` and the vapor composition `y`.
3. The liquid is split by approximation into an aqueous phase (water) and an organic phase (all other components, renormalised). See section 13.2.
4. Each component's molar heat capacity comes from its pure-component value: gas for the vapor, liquid for the liquid phases.
5. `Cp_vapor = Σ yᵢ · Cpᵢ(gas)`, `Cp_aqueous = Cp(water, liquid)` and `Cp_organic = Σ x_org,ᵢ · Cpᵢ(liquid)`.
6. `Cp_mix = V · Cp_vapor + L · (x_water · Cp_aqueous + (1 − x_water) · Cp_organic)`.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `Cp_aqueous` | number or `null` | J/mol/K | `null` if there is no liquid water. |
| `Cp_organic` | number or `null` | J/mol/K | `null` if there is no organic liquid. |
| `Cp_vapor` | number or `null` | J/mol/K | `null` if there is no vapor. |
| `Cp_mix` | number | J/mol/K | Weighted mixture heat capacity. |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": { "Cp_aqueous": 75.31529, "Cp_organic": 196.5026, "Cp_vapor": null, "Cp_mix": 135.909 },
  "units": { "Cp_aqueous": "J/mol/K", "Cp_organic": "J/mol/K", "Cp_vapor": "J/mol/K", "Cp_mix": "J/mol/K" },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 20.3, "zs_normalized": false }
}
```

**Notes.** For a fully vapor state `Cp_aqueous` and `Cp_organic` are `null`. `Cp_mix` normally equals the `Cp_mix` returned by `/cp_calc` for the same input (135.909 in both examples). Without water the call returns HTTP 422 with code `water_required` (example in section 6).

---

### 7.6 Molecular weight: vapor / aqueous / organic — `POST /triphase_mw_calc`

Returns the molecular weight of the vapor, aqueous and organic phases.

**URL:** `http://192.168.11.216:4300/api/triphase_mw_calc`. **Request:** common request model (section 4). Water is required.

**Processing**

1. The request is validated, the flash is performed, and the liquid is split into aqueous and organic parts as in section 7.5.
2. `MW_aqueous` is the molecular weight of water. `MW_organic = Σ x_org,ᵢ · MWᵢ`. `MW_vapor = Σ yᵢ · MWᵢ`. `MW_mix` is the overall mixture.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `MW_aqueous` | number or `null` | g/mol | `null` if there is no liquid water. |
| `MW_organic` | number or `null` | g/mol | `null` if there is no organic liquid. |
| `MW_vapor` | number or `null` | g/mol | `null` if there is no vapor. |
| `MW_mix` | number | g/mol | Overall mixture. |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": { "MW_aqueous": 18.01528, "MW_organic": 86.17536, "MW_vapor": null, "MW_mix": 52.09532 },
  "units": { "MW_aqueous": "g/mol", "MW_organic": "g/mol", "MW_vapor": "g/mol", "MW_mix": "g/mol" },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 14.2, "zs_normalized": false }
}
```

---

### 7.7 Phase fractions: vapor / aqueous / organic — `POST /triphase_vf_calc`

Returns how the total mixture divides into vapor, aqueous and organic phases.

**URL:** `http://192.168.11.216:4300/api/triphase_vf_calc`. **Request:** common request model (section 4). Water is required.

**Processing**

1. The request is validated, the flash is performed, and V, L and the water mole fraction in the liquid `x_water` are obtained.
2. `aqueous_fraction = L · x_water` and `organic_fraction = L · (1 − x_water)`.
3. `vapor_fraction + aqueous_fraction + organic_fraction = 1`.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `vapor_fraction` | number | mole fraction | Share of the total mixture that is vapor. |
| `aqueous_fraction` | number | mole fraction | Share of the total mixture that is aqueous liquid. |
| `organic_fraction` | number | mole fraction | Share of the total mixture that is organic liquid. |
| `liquid_fraction` | number | mole fraction | Aqueous plus organic (total liquid). |
| `water_in_liquid` | number | mole fraction | Water mole fraction within the liquid. |
| `organic_in_liquid` | number | mole fraction | Non-water mole fraction within the liquid. |

**Example request**

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

**Example response** (HTTP 200)

```json
{
  "status": "success",
  "data": {
    "vapor_fraction": 0.0,
    "aqueous_fraction": 0.5,
    "organic_fraction": 0.5,
    "liquid_fraction": 1.0,
    "water_in_liquid": 0.5,
    "organic_in_liquid": 0.5
  },
  "units": {
    "vapor_fraction": "mole fraction", "aqueous_fraction": "mole fraction",
    "organic_fraction": "mole fraction", "liquid_fraction": "mole fraction",
    "water_in_liquid": "mole fraction", "organic_in_liquid": "mole fraction"
  },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 14.3, "zs_normalized": false }
}
```

---

## 8. EOS Stream API

### 8.1 Stream properties — `POST /eos_stream_calc`

Returns the complete result for a stream in one call: the phase situation, the vapor fraction, and for each phase that exists its fraction, molecular weight, heat capacity and density, plus the mixture values.

**URL:** `http://192.168.11.216:4300/api/eos_stream_calc`. **Request:** common request model (section 4). Water is optional.

**Processing**

1. The request is validated and every component is resolved to its CAS number.
2. Components with a mole fraction of 0 are removed, and the same chemical given twice is merged.
3. A Peng-Robinson equation of state with binary interaction parameters is set up for the remaining components. The first request for a new set of components builds this model (a few seconds for about 25 components); later requests for the same set take milliseconds.
4. A three-phase flash at T and P finds the vapor and up to two liquid phases.
5. The liquid with the highest water content is reported as **aqueous**, the other as **organic**. With a single liquid, it is aqueous if it is more than 50 mol % water.
6. Each phase and the mixture are described with their properties.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `case` | string | n/a | Phase situation: `vapor-only`, `liquid-only (single liquid phase)`, `two-phase vapor-liquid (VL)`, `two-phase liquid-liquid (LL, aqueous+organic)` or `three-phase vapor-liquid-liquid (VLLE)`. |
| `V` | number | mole fraction | Vapor fraction. |
| `L` | number | mole fraction | Total liquid fraction (aqueous plus organic). |
| `n_phases` | integer | count | Number of phases found. |
| `n_components_used` | integer | count | Components that took part in the calculation (mole fraction above 0). |
| `vapor` | object or `null` | n/a | The vapor phase. `null` if there is no vapor. |
| `aqueous` | object or `null` | n/a | The aqueous liquid phase. `null` if there is none. |
| `organic` | object or `null` | n/a | The organic liquid phase. `null` if there is none. |
| `mixture` | object | n/a | Overall mixture. |

Each phase object (`vapor`, `aqueous`, `organic`):

| Field | Unit | Description |
| --- | --- | --- |
| `beta` | mole fraction of the total mixture | Phase fraction. The values of the phases that exist sum to 1. |
| `MW` | g/mol | Molecular weight. |
| `Cp` | J/mol/K | Molar heat capacity. |
| `rho_mass` | kg/m³ | Mass density. |
| `rho_molar_kmol_m3` | kmol/m³ | Molar density. |

The `mixture` object has `MW` (g/mol), `Cp` (J/mol/K), `Cp_mass_kJ_kgK` (kJ/kg/K), `rho_mass` (kg/m³) and `rho_molar_kmol_m3` (kmol/m³).

**Example 1: two liquid phases** (water/hexane 50/50, 300 K, 101325 Pa)

```json
{ "T": 300, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }
```

Response (HTTP 200):

```json
{
  "status": "success",
  "data": {
    "case": "two-phase liquid-liquid (LL, aqueous+organic)",
    "V": 0.0,
    "L": 1.0,
    "n_phases": 2,
    "n_components_used": 2,
    "vapor": null,
    "aqueous": { "beta": 0.4904076, "MW": 18.01528, "Cp": 81.16374, "rho_mass": 847.61, "rho_molar_kmol_m3": 47.0495 },
    "organic": { "beta": 0.5095924, "MW": 84.89234, "Cp": 186.3908, "rho_mass": 663.8171, "rho_molar_kmol_m3": 7.819517 },
    "mixture": { "MW": 52.09532, "Cp": 134.7867, "Cp_mass_kJ_kgK": 2.587308, "rho_mass": 689.1598, "rho_molar_kmol_m3": 13.22882 }
  },
  "units": {
    "V": "mole fraction", "L": "mole fraction", "n_phases": "count", "n_components_used": "count",
    "beta": "mole fraction of the total mixture (per phase)",
    "MW": "g/mol", "Cp": "J/mol/K", "Cp_mass_kJ_kgK": "kJ/kg/K",
    "rho_mass": "kg/m^3", "rho_molar_kmol_m3": "kmol/m^3"
  },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 14.7, "zs_normalized": false }
}
```

**Example 2: vapor and aqueous liquid** (same mixture at 351 K)

Request `{ "T": 351, "P": 101325, "components": ["water", "hexane"], "zs": [0.5, 0.5] }` returns `case` = `two-phase vapor-liquid (VL)`, `V` = 0.8310612, `vapor` with `beta` 0.8310612, `MW` 59.02314, `Cp` 112.9 and `rho_mass` 2.101125, `aqueous` with `beta` 0.1689388, `MW` 18.01528, `Cp` 81.78329 and `rho_mass` 816.244, `organic` = `null`, and `mixture` with `MW` 52.09532, `Cp` 107.6432 and `rho_mass` 2.231136.

**Example 3: gas, no water** (methane/ethane 50/50, 423.15 K, 29411.81 Pa)

Returns `case` = `vapor-only`, `V` = 1.0, `vapor` with `beta` 1.0, `MW` 23.05575, `Cp` 55.19081 and `rho_mass` 0.1928272, `aqueous` and `organic` = `null`, and the `mixture` with the same values.

**Notes**

- Components with a mole fraction of 0 are not part of the calculation. This keeps large streams fast and does not change the result. `n_components_used` shows how many were used.
- Names and CAS numbers may be mixed in one request, and the order of the components does not matter.
- If the equation-of-state flash fails for a state, the error `flash_failed` is returned with the reason.

---

## 9. Enthalpy API

### 9.1 Enthalpy and heat duty — `POST /eos_enthalpy_calc`

Returns the enthalpy of one stream at an inlet condition and at an outlet condition, and the heat duty between them (outlet minus inlet). The composition is the same at both conditions.

**URL:** `http://192.168.11.216:4300/api/eos_enthalpy_calc`

**Request body**

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `T_in` | number | `300` | Inlet temperature in K. Must be greater than 0. |
| `P_in` | number | `254920` | Inlet pressure in Pa. Must be greater than 0. |
| `T_out` | number | `368` | Outlet temperature in K. Must be greater than 0. |
| `P_out` | number | `254720` | Outlet pressure in Pa. Must be greater than 0. |
| `components` | array of strings | `["methane", "ethane"]` | Names or CAS numbers, as in section 4. |
| `zs` | array of numbers | `[0.5, 0.5]` | Mole fractions **or mole percent**, same length and order as `components`. They are rescaled to sum to 1 (`meta.zs_normalized` is then `true`). |

Send all six fields explicitly. The defaults exist only for convenience.

**Processing**

1. The request is validated and every component is resolved to its CAS number.
2. Components with a negligible mole fraction (below 1e-12 after rescaling) are removed, and the same chemical given twice is merged. A list with many zero entries is therefore calculated as the few components that are present.
3. A Peng-Robinson equation of state is set up for the remaining components: a pure-component flash for one component, a vapor / aqueous / organic flash with binary interaction parameters for several. The first request for a new set of components builds this model (about 3 seconds for 10 components); later requests for the same set take milliseconds.
4. The stream is flashed at the inlet condition and at the outlet condition, so a phase change between them (for example vaporisation) is part of the result.
5. `heat_duty_molar = enthalpy_molar(outlet) − enthalpy_molar(inlet)` and `sp_duty = enthalpy_mass(outlet) − enthalpy_mass(inlet)`.

**Response `data`**

| Field | Type | Unit | Description |
| --- | --- | --- | --- |
| `inlet` | object | n/a | State at the inlet condition. |
| `outlet` | object | n/a | State at the outlet condition. |
| `duty` | object | n/a | Heat duty between inlet and outlet. |
| `n_components_used` | integer | count | Components that took part in the calculation. |
| `ethylene_ethane_kij_override` | boolean | n/a | `true` when ethylene and ethane are both present and the calibrated interaction parameter 0.015 was used for that pair (see section 13.5). |

`inlet` and `outlet` each contain:

| Field | Unit | Description |
| --- | --- | --- |
| `vapor_fraction` | mole fraction | Vapor fraction of the stream at that condition (0 = all liquid, 1 = all vapor). |
| `molecular_weight` | g/mol | Molecular weight of the stream. |
| `enthalpy_molar` | kJ/mol | Enthalpy per mole of stream. |
| `enthalpy_mass` | kJ/kg | Enthalpy per kilogram of stream. |

`duty` contains:

| Field | Unit | Description |
| --- | --- | --- |
| `heat_duty_molar` | kJ/mol | Outlet minus inlet enthalpy, per mole. Positive: heat is absorbed (heating, vaporisation). Negative: heat is released (cooling, condensation). |
| `sp_duty` | kJ/kg | Specific heat duty: outlet minus inlet enthalpy, per kilogram. |

**Example 1: C2 stream, heated from 300 K to 368 K** (components given as CAS numbers, mole percent)

```json
{
  "T_in": 300, "P_in": 254920, "T_out": 368, "P_out": 254720,
  "components": ["74-82-8", "74-86-2", "74-85-1", "74-84-0", "74-99-7", "115-07-1", "74-98-6", "106-99-0", "106-98-9", "106-97-8"],
  "zs": [0.02, 0.43, 60.6, 37.94, 0.01, 0.72, 0.14, 0.05, 0.05, 0.04]
}
```

Response (HTTP 200):

```json
{
  "status": "success",
  "data": {
    "inlet":  { "vapor_fraction": 1.0, "molecular_weight": 28.97064, "enthalpy_molar": -0.04241087, "enthalpy_mass": -1.463926 },
    "outlet": { "vapor_fraction": 1.0, "molecular_weight": 28.97064, "enthalpy_molar": 3.439142, "enthalpy_mass": 118.7113 },
    "duty":   { "heat_duty_molar": 3.481552, "sp_duty": 120.1752 },
    "n_components_used": 10,
    "ethylene_ethane_kij_override": true
  },
  "units": {
    "vapor_fraction": "mole fraction", "molecular_weight": "g/mol",
    "enthalpy_molar": "kJ/mol", "enthalpy_mass": "kJ/kg",
    "heat_duty_molar": "kJ/mol", "sp_duty": "kJ/kg", "n_components_used": "count"
  },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 54.2, "zs_normalized": true }
}
```

`zs_normalized` is `true` because the values were given in mole percent and add up to 100.

**Example 2: water, liquid to vapor** (water, 300 K to 400 K at 101325 Pa)

The request `{ "T_in": 300, "P_in": 101325, "T_out": 400, "P_out": 101325, "components": ["water"], "zs": [1] }` returns `vapor_fraction` 0.0 at the inlet and 1.0 at the outlet, `heat_duty_molar` = 48.95733 kJ/mol and `sp_duty` = 2717.545 kJ/kg. The duty includes the latent heat of vaporisation.

**Example 3: cooling** (the C2 stream of example 1 from 368 K back to 300 K)

Swapping inlet and outlet gives the same magnitude with the opposite sign: `heat_duty_molar` = −3.481552 kJ/mol and `sp_duty` = −120.1752 kJ/kg.

**Notes**

- A pure component (one entry, or all other entries zero) is calculated with a pure-component flash; the response is the same structure.
- Components with a mole fraction of 0 are not part of the calculation. A list of 48 components of which 10 are non-zero is calculated as 10 components; `n_components_used` shows how many were used.
- If the flash fails at one condition, the error `flash_failed` is returned and its message names the condition (inlet or outlet).
- Enthalpy values use the reference state of the equation-of-state model. Use differences between conditions, such as the duty, rather than absolute values.

---

## 10. Vent API

### 10.1 Flow versus opening — `POST /vent_flow_calc`

Fits a polynomial to measured flow versus valve opening and estimates the flow at further openings. No components, temperature or pressure are involved; the request carries data points instead.

**URL:** `http://192.168.11.216:4300/api/vent_flow_calc`

**Request body**

| Field | Type | Default | Rules |
| --- | --- | --- | --- |
| `opening_values` | array of numbers | `[19.7, 49.6, 89.7]` | Valve opening of each data point, in %. At least 3 and at most 10 000 values, all finite. |
| `flow_values` | array of numbers | `[48601, 122050, 220698]` | Flow measured at each opening, in any one consistent unit. Same length as `opening_values`. |
| `degree` | integer | `2` | Requested polynomial degree, 1 (linear) to 10. Reduced automatically to what the number of points supports. |
| `estimate_at` | array of numbers | `[]` | Openings (%) at which to estimate the flow. May be empty to get only the fit. At most 10 000 values. |
| `clip_to_fit_range` | boolean | `true` | If `true`, an opening outside the fitted range is evaluated at the nearest end of the range. It is still flagged as extrapolated. |
| `min_flow` | number | `0` | Floor applied to every estimated flow (flow cannot be negative). |

Send all fields explicitly. The defaults exist only for convenience.

**Processing**

1. The request is validated: the two lists must have the same length, hold at least 3 points, and contain finite numbers only.
2. The degree is limited to `n − 2`, where `n` is the number of points, so that at least one residual degree of freedom remains. A higher requested degree is reduced, and the response says so.
3. A least-squares polynomial of that degree is fitted. This is equivalent to Excel `LINEST(Flow, Opening^{1..degree}, TRUE, TRUE)` with Flow as the known y values and Opening as the known x values. The coefficients are returned highest power first, the order used by LINEST.
4. The fit statistics are computed: standard error of every coefficient, R², standard error of the estimate, F statistic, residual degrees of freedom and the regression and residual sums of squares.
5. For every opening in `estimate_at` the polynomial is evaluated. If `clip_to_fit_range` is `true`, an opening outside the fitted range is first moved to the nearest end of the range. The result is raised to `min_flow` if it is lower.

**Response `data`**

| Field | Type | Description |
| --- | --- | --- |
| `fit` | object | The fitted polynomial and its statistics. |
| `estimates` | array of objects | One entry per value of `estimate_at`, in the same order. Empty if `estimate_at` was empty. |
| `warnings` | array of strings | Plain-language notes: degree reduced, estimates outside the fitted range, flows raised to the minimum, undefined statistics. Empty if there is nothing to report. |

`fit` contains:

| Field | Type | Description |
| --- | --- | --- |
| `degree_requested` | integer | The degree you asked for. |
| `degree_used` | integer | The degree actually fitted. |
| `degree_capped` | boolean | `true` if the degree was reduced because there are too few points. |
| `n_points` | integer | Number of data points. |
| `equation` | string | The fitted equation as text, for example `Flow(Opening) = +2458.61*Opening +143.197`. |
| `terms` | array of objects | One entry per power, highest power first: `power`, `coefficient` and `standard_error`. |
| `r_squared` | number or `null` | Coefficient of determination. `null` if all flow values are equal. |
| `standard_error_y` | number or `null` | Standard error of the estimate (LINEST `se_y`), in the unit of the flow values. |
| `f_statistic` | number or `null` | F statistic. `null` if undefined: all flow values equal, or the data fit the polynomial exactly. |
| `df_residual` | integer | Residual degrees of freedom: `n_points − (degree_used + 1)`. |
| `ss_regression` | number | Regression sum of squares. |
| `ss_residual` | number | Residual sum of squares. |
| `opening_range` | object | `min` and `max` of the opening values the curve was fitted on, in %. |

Each entry of `estimates`:

| Field | Type | Description |
| --- | --- | --- |
| `opening` | number | The opening you asked for, in %. |
| `opening_used` | number | The opening used in the polynomial. It differs from `opening` when the value was moved to the end of the fitted range. |
| `flow` | number | Estimated flow, after the `min_flow` floor, in the unit of `flow_values`. |
| `extrapolated` | boolean | `true` if `opening` lies outside the fitted opening range. |
| `floor_applied` | boolean | `true` if the polynomial gave a flow below `min_flow` and the floor was used. |

**Example 1: three points, degree 3 requested** (the reference data)

```json
{
  "opening_values": [19.7, 49.6, 89.7],
  "flow_values": [48601, 122050, 220698],
  "degree": 3,
  "estimate_at": [5, 25, 50, 95, 110],
  "clip_to_fit_range": true,
  "min_flow": 0
}
```

Response (HTTP 200):

```json
{
  "status": "success",
  "data": {
    "fit": {
      "degree_requested": 3,
      "degree_used": 1,
      "degree_capped": true,
      "n_points": 3,
      "equation": "Flow(Opening) = +2458.61*Opening +143.197",
      "terms": [
        { "power": 1, "coefficient": 2458.613, "standard_error": 0.9992376 },
        { "power": 0, "coefficient": 143.197, "standard_error": 60.21554 }
      ],
      "r_squared": 0.9999998,
      "standard_error_y": 49.63446,
      "f_statistic": 6054004.0,
      "df_residual": 1,
      "ss_regression": 14914520000.0,
      "ss_residual": 2463.579,
      "opening_range": { "min": 19.7, "max": 89.7 }
    },
    "estimates": [
      { "opening": 5.0,   "opening_used": 19.7, "flow": 48577.87,  "extrapolated": true,  "floor_applied": false },
      { "opening": 25.0,  "opening_used": 25.0, "flow": 61608.51,  "extrapolated": false, "floor_applied": false },
      { "opening": 50.0,  "opening_used": 50.0, "flow": 123073.8,  "extrapolated": false, "floor_applied": false },
      { "opening": 95.0,  "opening_used": 89.7, "flow": 220680.8,  "extrapolated": true,  "floor_applied": false },
      { "opening": 110.0, "opening_used": 89.7, "flow": 220680.8,  "extrapolated": true,  "floor_applied": false }
    ],
    "warnings": [
      "The requested degree 3 was reduced to 1: 3 data points support at most degree 1.",
      "3 of 5 estimate openings lie outside the fitted range 19.7 to 89.7 % and were clamped to the fitted range."
    ]
  },
  "units": {
    "opening": "%", "opening_used": "%", "flow": "same unit as the supplied flow_values",
    "coefficient": "flow unit per (%)^power", "standard_error": "flow unit per (%)^power",
    "r_squared": "dimensionless", "standard_error_y": "same unit as flow_values",
    "f_statistic": "dimensionless", "df_residual": "count", "n_points": "count",
    "degree_requested": "count", "degree_used": "count",
    "ss_regression": "(flow unit)^2", "ss_residual": "(flow unit)^2"
  },
  "meta": { "request_id": "a1b2c3d4e5f6", "elapsed_ms": 3.1 }
}
```

`meta` has no `zs_normalized`, because this endpoint has no composition.

**Example 2: six points, degree 2** (openings 10, 20, 40, 60, 80, 100 % with flows 350, 700, 1980, 4000, 6600, 9900)

Returns `equation` = `Flow(Opening) = +0.841201*Opening^2 +13.8891*Opening +105.642`, `degree_used` 2 and `degree_capped` false, `r_squared` 0.9999613, `standard_error_y` 29.99768, `f_statistic` 38796.78 and `df_residual` 3. For `estimate_at` = 5, 30, 55, 100, 120 the estimated flows are 328.653, 1279.395, 3414.173, 9906.557 and 9906.557. Only 5 and 120 are `extrapolated`; 120 is evaluated at 100 %, the end of the fitted range.

**Example 3: data that cannot be fitted** (all openings equal)

Request `{ "opening_values": [50, 50, 50, 50], "flow_values": [1, 2, 3, 4], "degree": 2 }` returns HTTP 422:

```json
{
  "status": "error",
  "error": {
    "code": "fit_failed",
    "message": "A degree-2 fit needs at least 3 different opening values; the data contain only 1.",
    "details": { "distinct_opening_values": 1, "required": 3, "degree_used": 2 }
  },
  "request_id": "a1b2c3d4e5f6"
}
```

**Notes**

- A fit of degree *d* needs at least *d* + 2 points and at least *d* + 1 different opening values. The first is handled by reducing the degree; the second is reported as `fit_failed`.
- Use the lowest degree that describes the data. A high degree on few points follows the noise, and the polynomial can behave wildly outside the fitted range; that is why estimates outside the range are clamped by default and always flagged.
- `null` in `r_squared`, `standard_error_y`, `f_statistic` or `standard_error` means the value is undefined for these data; the API never returns NaN or infinity.
- Openings are not limited to 0 to 100 %. Any finite numbers are accepted, as in the data you supply.
- The Vent API does not use the equation of state and starts immediately; there is no model to build.

---

## 11. System

### 11.1 Health check — `GET /health`

Confirms that the service is running and reports the deployed version. It is suitable for uptime monitoring. It needs no request body and no authentication.

**URL:** `http://192.168.11.216:4300/api/health`

**Response** (HTTP 200). This endpoint does not use the standard envelope.

```json
{ "status": "ok", "version": "2.3.0" }
```

| Field | Description |
| --- | --- |
| `status` | `"ok"` while the service is alive. |
| `version` | The deployed API version. |

---

## 12. Choosing between the approaches

| | Property APIs | EOS Stream API |
| --- | --- | --- |
| Calls needed | One per property | One for everything |
| Model | Vapor–liquid equilibrium | Peng-Robinson equation of state, three-phase flash |
| Phases | Vapor and one liquid. The three `triphase_*` endpoints split the liquid into aqueous and organic by approximation. | Vapor, aqueous and organic found by the flash |
| Water | Required for the `triphase_*` endpoints | Optional |
| Real-gas behaviour | No (ideal-gas vapor heat capacity) | Yes |
| Response | One group of fields per property | Every phase and the mixture |
| Typical use | A single property, simple mixtures | Complete stream results, mixtures of water with hydrocarbons, anything where the phase behaviour matters |

The **Enthalpy API** is the only group that returns enthalpy and heat duty. It uses the same equation of state as the EOS Stream API. The **Vent API** is independent of the others: it works on your own measured data and involves no thermodynamics.

For single-phase gas mixtures at low pressure the two approaches agree closely (for example methane/ethane at 423.15 K: heat capacity 55.17 and 55.19 J/mol/K). For mixtures of water with hydrocarbons near their boiling conditions the phase split can differ substantially. In such cases use the EOS Stream API.

---

## 13. Calculation notes

### 13.1 Phase determination

The Property APIs use a vapor–liquid equilibrium (VLE) flash at the given T and P. Typical outcomes are all vapor (`Vapor_fraction` = 1), all liquid (= 0) or two phases (between 0 and 1). The EOS Stream API performs a three-phase flash and reports each phase that exists.

### 13.2 The triphase approximation (Property APIs)

The Property APIs' flash finds one liquid phase. The three `triphase_*` endpoints therefore divide that liquid as follows:

- **Aqueous phase:** pure water. Its share of the liquid equals the water mole fraction in the liquid.
- **Organic phase:** all other components, renormalised to sum to 1.

This suits systems where water and the organic components are essentially immiscible. It does not model mutual solubility or a second liquid phase forming. For a rigorous result use the EOS Stream API.

### 13.3 Component identification

Components can be given as names (`"water"`, `"methane"`) or CAS numbers (`"7732-18-5"`, `"74-82-8"`). If a name is not recognised, use the CAS number. A CAS number identifies one exact chemical. For example, `74-85-1` is ethene (ethylene) and `74-84-0` is ethane.

### 13.4 Heat-capacity basis

The Property APIs report ideal-gas heat capacities for the vapor, which is accurate at low to moderate pressure. The EOS Stream API includes real-gas behaviour.

### 13.5 Ethylene and ethane interaction parameter (Enthalpy API)

Both equation-of-state groups take binary interaction parameters from the ChemSep PR database; a pair without a published value is treated as ideal. For the pair **ethylene / ethane** the Enthalpy API uses the calibrated value **0.015** instead of the database value 0.0078. The database value predicts too much condensation near the mutual critical region of the two components and a heat duty about 42 % away from the plant reference; 0.015 reduces that difference to about 9 %. This value is calibrated, not taken from the database. `ethylene_ethane_kij_override` in the response is `true` when it was applied. The EOS Stream API uses the database value for this pair.

### 13.6 Polynomial fit (Vent API)

The Vent API fits the polynomial by ordinary least squares on the Vandermonde matrix, as Excel LINEST does. For large opening values and a high degree this matrix becomes poorly conditioned: the coefficients and their standard errors then lose precision, although the fitted flows stay accurate. Prefer a low degree. The F statistic is returned as `null` when it would be meaningless (all flows equal, or an exact fit), where the Excel function returns rounding noise.

---

## 14. Client examples

All examples send the request from section 4. Replace the host if the service moves. To call another endpoint, change only the last part of the URL.

### 14.1 Postman

1. Create a request with method **POST** and URL `http://192.168.11.216:4300/api/eos_stream_calc` (or any other endpoint).
2. Open **Body**, select **raw**, and choose **JSON** in the drop-down. Postman then sets `Content-Type: application/json`.
3. Paste the body below and press **Send**.

```json
{
  "T": 300,
  "P": 101325,
  "components": ["water", "hexane"],
  "zs": [0.5, 0.5]
}
```

### 14.2 curl: Windows Command Prompt

```bat
curl.exe -X POST http://192.168.11.216:4300/api/eos_stream_calc -H "Content-Type: application/json" -d "{\"T\":300,\"P\":101325,\"components\":[\"water\",\"hexane\"],\"zs\":[0.5,0.5]}"
```

### 14.3 curl: Linux, macOS, Git Bash

```bash
curl -X POST http://192.168.11.216:4300/api/eos_stream_calc \
  -H "Content-Type: application/json" \
  -d '{"T":300,"P":101325,"components":["water","hexane"],"zs":[0.5,0.5]}'
```

### 14.4 Python

```python
import requests

BASE = "http://192.168.11.216:4300/api"

payload = {
    "T": 300,
    "P": 101325,
    "components": ["water", "hexane"],
    "zs": [0.5, 0.5],
}

resp = requests.post(f"{BASE}/eos_stream_calc", json=payload, timeout=60)
body = resp.json()

if resp.ok:                       # HTTP 200
    data = body["data"]
    print(data["case"], data["mixture"]["Cp"], body["units"]["Cp"])
    for name in ("vapor", "aqueous", "organic"):
        phase = data[name]        # None when the phase does not exist
        if phase:
            print(name, phase["beta"], phase["MW"], phase["rho_mass"])
else:                             # HTTP 4xx / 5xx
    err = body["error"]
    print(err["code"], err["message"], err["details"], "request:", body["request_id"])
```

### 14.5 JavaScript (browser or Node 18+)

```javascript
const BASE = "http://192.168.11.216:4300/api";

const res = await fetch(`${BASE}/eos_stream_calc`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ T: 300, P: 101325, components: ["water", "hexane"], zs: [0.5, 0.5] }),
});
const body = await res.json();
if (res.ok) console.log(body.data.case, body.data.mixture.Cp);
else console.error(body.error.code, body.error.message);
```

### 14.6 Handling responses

1. Check the **HTTP status** first. 200 means success.
2. On success read `data` and `units`. Treat `null` values as "this phase is not present".
3. On error use `error.code` for your logic and `error.message` and `error.details` for display. Log the `request_id`.
4. Do not retry a 422 response unchanged, because the input must change. A 504 may be retried once with a simpler input.

### 14.7 Large mixtures

There is no limit on the number of components. Send the two lists as JSON arrays of equal length. Components with a mole fraction of 0 may be included; the EOS Stream API ignores them, so a stream with 48 listed components of which 24 are non-zero is calculated as 24 components.

### 14.8 Vent API (Python)

```python
import requests

payload = {
    "opening_values": [10, 20, 40, 60, 80, 100],
    "flow_values": [350, 700, 1980, 4000, 6600, 9900],
    "degree": 2,
    "estimate_at": [30, 55],
}

resp = requests.post("http://192.168.11.216:4300/api/vent_flow_calc", json=payload, timeout=60)
body = resp.json()

if resp.ok:
    fit = body["data"]["fit"]
    print(fit["equation"], "R2 =", fit["r_squared"])
    for e in body["data"]["estimates"]:
        print(e["opening"], e["flow"], "(extrapolated)" if e["extrapolated"] else "")
    for warning in body["data"]["warnings"]:
        print("warning:", warning)
else:
    print(body["error"]["code"], body["error"]["message"])
```

---

## 15. Operational limits

| Limit | Value | Behaviour when exceeded |
| --- | --- | --- |
| Calculation time | 30 seconds | `504 calculation_timeout` |
| Request body size | 5 MB | HTTP `413` from the web server |
| Number of components | No limit by default | `422 validation_error` only if the administrator sets a cap |
| Parallel calculations | 2 worker processes | Further requests wait for a free worker |
| Vent API data | At most 10 000 points and 10 000 estimate openings; degree 1 to 10 | `422 validation_error` |
| First EOS Stream or Enthalpy request for a new component set | A few seconds (model build) | Later requests for the same set take milliseconds |

---

## 16. Version history

| Version | Date | Summary |
| --- | --- | --- |
| 2.3.0 | October 2026 | Added the **Vent API** (`POST /vent_flow_calc`): polynomial fit of flow versus valve opening (Excel LINEST equivalent) with coefficient standard errors, R², standard error of the estimate, F statistic and sums of squares, and flow estimates at further openings with extrapolation flags, clipping and a minimum-flow floor. New error code `fit_failed`. |
| 2.2.0 | October 2026 | Added the **Enthalpy API** (`POST /eos_enthalpy_calc`): enthalpy at an inlet and an outlet condition and the heat duty between them, with a pure-component flash, a multi-component three-phase flash and the calibrated ethylene/ethane interaction parameter. |
| 2.1.0 | October 2026 | Added the **EOS Stream API** (`POST /eos_stream_calc`). Property APIs and EOS Stream API are grouped in the documentation, with a description, request example and response example for every endpoint. The first-generation `enthalpy_calc` and `std_enthalpy_calc` endpoints were removed; enthalpy is provided by the Enthalpy API from 2.2.0. |
| 2.0.0 | October 2026 | Consistent response envelope with `units` and `meta`. Proper HTTP status codes and error codes. Strict input validation. Corrected units. `null` for absent phases. Water recognised by name or CAS number. No limit on the number of components. Request ids and a health endpoint. |
