"""Documentation text and examples shown in the generated API documentation (Swagger UI / OpenAPI).

Kept separate from the code that does the work so wording can be reviewed and changed on its own.
Every example below is a real response of this API (values rounded to 7 significant digits).
"""
from dataclasses import dataclass
from typing import Any, Dict

TAG_PROPERTY = "Property APIs"
TAG_EOS = "EOS Stream API"
TAG_ENTHALPY = "Enthalpy API"
TAG_VENT = "Vent API"
TAG_CPCURVE = "Cp vs Temperature API"
TAG_SYSTEM = "System"

API_TITLE = "Thermo Property API"

API_DESCRIPTION = """
Thermodynamic properties of multi-component mixtures at a given temperature and pressure.

The API offers **four groups of calculations**, grouped in this documentation:

| Group | Use it when | Approach |
| --- | --- | --- |
| **Property APIs** | You need one specific property (heat capacity, density, molecular weight, vapor fraction, or the vapor / aqueous / organic split) | One endpoint per property. Vapor–liquid equilibrium model. |
| **EOS Stream API** | You need the complete stream result, or the phase behaviour matters (for example water with hydrocarbons) | One call returns every phase and the mixture. Peng-Robinson equation of state with a real three-phase (vapor / aqueous / organic) flash. |
| **Enthalpy API** | You need the enthalpy of a stream at an inlet and an outlet condition, and the heat duty between them | One call returns the vapor fraction, molecular weight and enthalpy at both conditions and the heat duty. Peng-Robinson equation of state. |
| **Vent API** | You have measured flow at several valve openings and need the flow at other openings | A polynomial of flow versus opening (Excel LINEST equivalent) is fitted to your data points; the response gives the fit statistics and the estimated flows. No components or temperature are involved. |

### Conventions
* All calculation endpoints use `POST` with a JSON body; send `Content-Type: application/json`.
* Inputs of the stream calculations: temperature `T` in **K**, pressure `P` in **Pa**, `components` as **CAS numbers only** (names are rejected), `zs` as **mole fractions** (not mole percent) in the same order. The fractions should add up to 1; a small difference is rescaled (`meta.zs_normalized` is then `true`). The Vent API takes opening and flow data instead (see its group description).
* Units: heat capacity J/mol/K, molecular weight g/mol, density kg/m³, enthalpy and heat duty kJ/mol and kJ/kg, fractions are mole fractions. Every response contains a `units` object.
* A phase that does not exist at the given conditions is returned as `null`. It is never `0`, and it is not an error.
* Values are returned at full precision; round them in your client.

### Responses
* **Success** (HTTP 200): `{ "status": "success", "data": {...}, "units": {...}, "meta": {...} }`
* **Error** (HTTP 4xx / 5xx): `{ "status": "error", "error": { "code", "message", "details" }, "request_id" }`. Use `error.code` in client logic; it is stable.
* Every response carries a `request_id` (also the `X-Request-ID` response header). Quote it when reporting a problem. You may send your own `X-Request-ID` header; it is returned unchanged.

### Limits
Calculation time limit 30 seconds (`504 calculation_timeout`). Request body up to 5 MB. No limit on the number of components.
"""

TAGS = [
    {
        "name": TAG_PROPERTY,
        "description": (
            "One endpoint per property, based on a vapor–liquid equilibrium (VLE) model. Fast and simple. "
            "The three `triphase_*` endpoints split the liquid into an **aqueous** (water) and an **organic** "
            "part by approximation, and require water in the mixture. For mixtures of water with hydrocarbons "
            "near boiling conditions, or whenever the phase behaviour matters, use the **EOS Stream API**."
        ),
    },
    {
        "name": TAG_EOS,
        "description": (
            "Peng-Robinson equation of state with a rigorous three-phase flash. One call returns the vapor, "
            "aqueous and organic phases (fraction, molecular weight, heat capacity, density) and the mixture. "
            "Water is optional. Components with a mole fraction of 0 are not part of the calculation. "
            "The first request for a new set of components builds the model and can take a few seconds; "
            "later requests for the same components take milliseconds."
        ),
    },
    {
        "name": TAG_ENTHALPY,
        "description": (
            "Enthalpy of one stream at an inlet condition (`T_in`, `P_in`) and an outlet condition (`T_out`, `P_out`), "
            "and the heat duty between them (outlet minus inlet). The composition is the same at both conditions. "
            "Peng-Robinson equation of state, with a rigorous flash at each condition so that a phase change between "
            "inlet and outlet is included in the duty. Water is optional. Components with a negligible mole fraction "
            "are not part of the calculation. The first request for a new set of components builds the model and can "
            "take a few seconds; later requests for the same components take milliseconds."
        ),
    },
    {
        "name": TAG_VENT,
        "description": (
            "Flow as a function of valve opening. You supply measured points (`opening_values` in %, `flow_values` in the unit "
            "of your data, for example kg/h) and a polynomial `degree`; the API fits the polynomial by least squares (equivalent to Excel "
            "`LINEST(Flow, Opening^{1..degree}, TRUE, TRUE)`) and returns the coefficients with their standard errors, R squared, "
            "the standard error of the estimate, the F statistic and the sums of squares, plus the flow estimated at each "
            "opening in `estimate_at`. The degree is reduced automatically to what the number of points supports. "
            "An estimate outside the fitted opening range is flagged as extrapolated and, by default, evaluated at the "
            "nearest end of the range. Every flow value in the response is in the unit you supplied; nothing is converted. "
            "This group has no components, temperature or pressure."
        ),
    },
    {
        "name": TAG_CPCURVE,
        "description": (
            "Heat capacity of a stream at one pressure over a range of temperatures. You give `P`, the components (CAS numbers) "
            "with their mole fractions, the first temperature `T_start`, the last temperature `T_end` (default 2273 K) and the "
            "step `interval` in K (for example 10). The API runs the same Peng-Robinson three-phase flash as the EOS Stream API "
            "at every temperature and returns a table: temperature, phase situation, vapor fraction, molecular weight and "
            "mixture heat capacity in J/mol/K and kJ/kg/K. A temperature at which the flash fails is returned with `Cp` null "
            "and the reason in `error`; the other temperatures are still returned. At most 1000 temperatures per request."
        ),
    },
    {"name": TAG_SYSTEM, "description": "Service status."},
]

WATER_HEXANE = {"T": 300, "P": 101325, "components": ["7732-18-5", "110-54-3"], "zs": [0.5, 0.5]}  # water, hexane
_FRACTION = "mole fraction"


@dataclass(frozen=True)
class EndpointDoc:
    operation_id: str
    tag: str
    summary: str
    description: str
    request: Dict[str, Any]
    data: Dict[str, Any]  # example of the `data` object
    basic_meta: bool = False  # True for endpoints without a composition (no zs_normalized in meta)


VENT_REQUEST = {
    "opening_values": [19.7, 49.6, 89.7],
    "flow_values": [48601, 122050, 220698],
    "degree": 3,
    "estimate_at": [5, 25, 50, 95, 110],
    "clip_to_fit_range": True,
    "min_flow": 0.0,
}

VENT_INPUT = """
**Request.** `opening_values` (valve opening in %, at least 3 points) and `flow_values` (flow at each opening, one consistent
unit, same length); `degree` (1 to 10); optionally `estimate_at` (openings in % at which to estimate the flow),
`clip_to_fit_range` (default true) and `min_flow` (default 0). See *Conventions* at the top of this page.
""".strip()

COMMON_INPUT = """
**Request.** `T` (K, above 0), `P` (Pa, above 0), `components` (CAS numbers only, no duplicates) and `zs`
(mole fractions, not mole percent, same length and order as `components`). See *Conventions* at the top of this page.
""".strip()

ENTHALPY_INPUT = """
**Request.** `T_in` and `P_in` (inlet temperature in K and pressure in Pa), `T_out` and `P_out` (outlet temperature and
pressure), all above 0; `components` (CAS numbers only, no duplicates) and `zs` (mole fractions, not mole percent,
same length and order as `components`; they should add up to 1). See *Conventions* at the top of this page.
""".strip()

LEAD_STREAM_REQUEST = {
    "T_in": 300, "P_in": 254920, "T_out": 368, "P_out": 254720,
    "components": ["74-82-8", "74-86-2", "74-85-1", "74-84-0", "74-99-7", "115-07-1", "74-98-6", "106-99-0", "106-98-9", "106-97-8"],
    "zs": [0.0002, 0.0043, 0.606, 0.3794, 0.0001, 0.0072, 0.0014, 0.0005, 0.0005, 0.0004],
}

ENDPOINT_DOCS: Dict[str, EndpointDoc] = {
    "/cp_calc": EndpointDoc(
        "heat_capacity", TAG_PROPERTY, "Heat capacity",
        """Returns the heat capacity of the liquid phase, the vapor phase and the whole mixture, with the phase fractions.

**Method.** A vapor–liquid flash at `T` and `P` gives the vapor fraction *V* and the liquid fraction *L = 1 − V*.
`Cp_mix = L · Cp_liquid + V · Cp_vapor`. Vapor heat capacity is the ideal-gas value of the vapor composition.

**Phases.** `Cp_liquid` is `null` when no liquid exists, and `Cp_vapor` is `null` when no vapor exists.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"Cp_liquid": 135.909, "Cp_vapor": None, "Cp_mix": 135.909, "Vapor_fraction": 0.0, "Liquid_fraction": 1.0},
    ),
    "/density_calc": EndpointDoc(
        "density", TAG_PROPERTY, "Density",
        """Returns the density of the mixture at `T` and `P`.

**Method.** The mixture is built at `T` and `P` and its density and phase state are read.

**`phase`.** `"g"` gas, `"l"` liquid, `"l/g"` two-phase.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"rho_mix": 694.6499, "phase": "l"},
    ),
    "/mw_calc": EndpointDoc(
        "molecular_weight", TAG_PROPERTY, "Molecular weight",
        """Returns the molecular weight of the liquid phase, the vapor phase and the whole mixture.

**Method.** A vapor–liquid flash gives the composition of each phase. `MW_liquid = Σ xᵢ·MWᵢ` and
`MW_vapor = Σ yᵢ·MWᵢ`; `MW_avg` is the molecular weight of the overall mixture.

**Phases.** `MW_liquid` is `null` when no liquid exists, and `MW_vapor` is `null` when no vapor exists.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"MW_liquid": 52.09532, "MW_vapor": None, "MW_avg": 52.09532},
    ),
    "/vf_calc": EndpointDoc(
        "vapor_fraction", TAG_PROPERTY, "Vapor fraction",
        """Returns the fraction of the mixture that is vapor and the fraction that is liquid.

**Method.** A vapor–liquid flash at `T` and `P`. `Vapor_fraction` is 0 for an all-liquid state and 1 for an
all-vapor state; `Liquid_fraction = 1 − Vapor_fraction`.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"Vapor_fraction": 0.0, "Liquid_fraction": 1.0},
    ),
    "/triphase_cp_calc": EndpointDoc(
        "triphase_heat_capacity", TAG_PROPERTY, "Heat capacity: vapor / aqueous / organic",
        """Returns the heat capacity of the vapor, aqueous (water) and organic phases of a mixture that contains water.

**Method.** After the vapor–liquid flash the liquid is split by approximation into an *aqueous* phase (water) and an
*organic* phase (all other components, renormalised). Each phase heat capacity is computed from the pure-component
values in mole-fraction proportions. `Cp_mix = V·Cp_vapor + L·(x_water·Cp_aqueous + (1 − x_water)·Cp_organic)`.

**Water is required** (CAS `7732-18-5`); otherwise the error `water_required` is returned.
A phase that does not exist is `null`.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"Cp_aqueous": 75.31529, "Cp_organic": 196.5026, "Cp_vapor": None, "Cp_mix": 135.909},
    ),
    "/triphase_mw_calc": EndpointDoc(
        "triphase_molecular_weight", TAG_PROPERTY, "Molecular weight: vapor / aqueous / organic",
        """Returns the molecular weight of the vapor, aqueous and organic phases of a mixture that contains water.

**Method.** Same phase split as *Heat capacity: vapor / aqueous / organic*. `MW_aqueous` is the molecular weight of
water; `MW_organic` and `MW_vapor` are the composition-weighted values of those phases.

**Water is required.** A phase that does not exist is `null`.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"MW_aqueous": 18.01528, "MW_organic": 86.17536, "MW_vapor": None, "MW_mix": 52.09532},
    ),
    "/triphase_vf_calc": EndpointDoc(
        "triphase_fractions", TAG_PROPERTY, "Phase fractions: vapor / aqueous / organic",
        """Returns how the total mixture divides into vapor, aqueous and organic phases.

**Method.** `aqueous_fraction = L · x_water` and `organic_fraction = L · (1 − x_water)`, where *x_water* is the water
mole fraction in the liquid. `vapor_fraction + aqueous_fraction + organic_fraction = 1`.
`water_in_liquid` and `organic_in_liquid` give the split **within the liquid**.

**Water is required.**

""" + COMMON_INPUT,
        WATER_HEXANE,
        {"vapor_fraction": 0.0, "aqueous_fraction": 0.5, "organic_fraction": 0.5, "liquid_fraction": 1.0,
         "water_in_liquid": 0.5, "organic_in_liquid": 0.5},
    ),
    "/eos_stream_calc": EndpointDoc(
        "eos_stream", TAG_EOS, "Stream properties (vapor / aqueous / organic / mixture)",
        """Returns the complete result for a stream in one call: the phase situation, the vapor fraction, and for each
phase that exists its fraction, molecular weight, heat capacity and density, plus the mixture values.

**Method.** Peng-Robinson equation of state with binary interaction parameters and a rigorous three-phase flash
(vapor, aqueous liquid, organic liquid). The liquid with the highest water content is reported as *aqueous* and
the other as *organic*; with a single liquid, it is *aqueous* if it is more than 50 mol % water.

**`case`** is one of: `vapor-only`, `liquid-only (single liquid phase)`, `two-phase vapor-liquid (VL)`,
`two-phase liquid-liquid (LL, aqueous+organic)`, `three-phase vapor-liquid-liquid (VLLE)`.

**Phases.** `vapor`, `aqueous` and `organic` are `null` when that phase does not exist. `beta` is the phase fraction
of the total mixture; the `beta` values of the existing phases sum to 1.

**Components.** Water is optional. Components with a mole fraction of 0 are not part of the calculation
(`n_components_used` shows how many were).

**Timing.** The first request for a new set of components builds the model (a few seconds for about 25 components);
later requests for the same set take milliseconds.

""" + COMMON_INPUT,
        WATER_HEXANE,
        {
            "case": "two-phase liquid-liquid (LL, aqueous+organic)", "V": 0.0, "L": 1.0, "n_phases": 2, "n_components_used": 2,
            "vapor": None,
            "aqueous": {"beta": 0.4904076, "MW": 18.01528, "Cp": 81.16374, "rho_mass": 847.61, "rho_molar_kmol_m3": 47.0495},
            "organic": {"beta": 0.5095924, "MW": 84.89234, "Cp": 186.3908, "rho_mass": 663.8171, "rho_molar_kmol_m3": 7.819517},
            "mixture": {"MW": 52.09532, "Cp": 134.7867, "Cp_mass_kJ_kgK": 2.587308, "rho_mass": 689.1598, "rho_molar_kmol_m3": 13.22882},
        },
    ),
    "/eos_enthalpy_calc": EndpointDoc(
        "eos_enthalpy", TAG_ENTHALPY, "Enthalpy and heat duty (inlet to outlet)",
        """Returns the enthalpy of a stream at an inlet and an outlet condition and the heat duty between them.

**Method.** Peng-Robinson equation of state. The stream is flashed at the inlet condition and at the outlet
condition (a rigorous vapor / aqueous / organic flash for mixtures; a pure-component flash when only one component
is present), so a phase change between inlet and outlet is included in the result.
`heat_duty_molar = enthalpy_molar(outlet) − enthalpy_molar(inlet)` and `sp_duty = enthalpy_mass(outlet) − enthalpy_mass(inlet)`.
A positive duty means heat is absorbed (heating or vaporisation), a negative duty means heat is released.

**Response.** `inlet` and `outlet` each give `vapor_fraction` (mole fraction), `molecular_weight` (g/mol),
`enthalpy_molar` (kJ/mol) and `enthalpy_mass` (kJ/kg). `duty` gives `heat_duty_molar` (kJ/mol) and `sp_duty` (kJ/kg).
`n_components_used` is the number of components that took part in the calculation.

**Components.** Water is optional. Components with a negligible mole fraction (below 1e-12 after rescaling) are not
part of the calculation, so lists with many zero entries are fast.

**Ethylene and ethane.** When both are present the binary interaction parameter of that pair is set to the calibrated
value 0.015 instead of the database value 0.0078, which reproduces the plant reference duty of C2 streams much more
closely. `ethylene_ethane_kij_override` is `true` when this was applied.

**Timing.** The first request for a new set of components builds the model (about 3 seconds for 10 components); later
requests for the same set take milliseconds.

""" + ENTHALPY_INPUT,
        LEAD_STREAM_REQUEST,
        {"inlet": {"vapor_fraction": 1.0, "molecular_weight": 28.97064, "enthalpy_molar": -0.04241087, "enthalpy_mass": -1.463926}, "outlet": {"vapor_fraction": 1.0, "molecular_weight": 28.97064, "enthalpy_molar": 3.439142, "enthalpy_mass": 118.7113}, "duty": {"heat_duty_molar": 3.481552, "sp_duty": 120.1752}, "n_components_used": 10, "ethylene_ethane_kij_override": True},
    ),
    "/eos_cp_curve_calc": EndpointDoc(
        "eos_cp_curve", TAG_CPCURVE, "Heat capacity versus temperature",
        """Returns the heat capacity of a stream at every temperature from `T_start` to `T_end` in steps of `interval`, at one pressure.

**Method.** The Peng-Robinson three-phase flash of the EOS Stream API is performed at each temperature
(`T_start`, `T_start + interval`, `T_start + 2·interval`, ...; the last temperature is the largest one not above `T_end`).
Phase changes along the range are therefore included: `Cp` is the heat capacity of the whole mixture, `case` and `V`
show which phases exist at that temperature.

**Response.** `points` is the table, one row per temperature: `T` (K), `case`, `V` (mole fraction vapor), `Cp` (J/mol/K),
`Cp_mass_kJ_kgK` (kJ/kg/K), `Cp_kcal_kmolK` (kcal/kmol/K), `Cp_mass_kcal_kgK` (kcal/kg/K) and `MW` (g/mol). The kcal values are the J and kJ values divided by 4.184. `T_end` in `data` is the last temperature actually calculated.

**Failed temperatures.** If the flash does not work at a temperature, that row has `Cp` null and the reason in `error`;
the rest of the table is returned and `n_failed` counts them. If every temperature fails, the call returns `flash_failed`.

**Limits.** `T_end` must not be below `T_start`; at most 1000 temperatures per request (use a larger `interval` otherwise).

**Request.** `P` (Pa, above 0), `T_start`, `T_end` and `interval` (K, above 0), `components` (CAS numbers only, no duplicates)
and `zs` (mole fractions, not mole percent, same length and order as `components`). See *Conventions* at the top of this page.

""",
        {"P": 101325, "components": ["74-82-8", "74-84-0"], "zs": [0.5, 0.5], "T_start": 300, "T_end": 330, "interval": 10},
        {'n_points': 4, 'n_failed': 0, 'n_components_used': 2, 'T_start': 300.0, 'T_end': 330.0, 'interval': 10.0, 'points': [{'T': 300.0, 'case': 'vapor-only', 'V': 1.0, 'Cp': 44.41757, 'Cp_mass_kJ_kgK': 1.926529, 'Cp_kcal_kmolK': 10.61605, 'Cp_mass_kcal_kgK': 0.4604515, 'MW': 23.05575, 'error': None}, {'T': 310.0, 'case': 'vapor-only', 'V': 1.0, 'Cp': 45.21018, 'Cp_mass_kJ_kgK': 1.960907, 'Cp_kcal_kmolK': 10.80549, 'Cp_mass_kcal_kgK': 0.468668, 'MW': 23.05575, 'error': None}, {'T': 320.0, 'case': 'vapor-only', 'V': 1.0, 'Cp': 46.0269, 'Cp_mass_kJ_kgK': 1.99633, 'Cp_kcal_kmolK': 11.00069, 'Cp_mass_kcal_kgK': 0.4771344, 'MW': 23.05575, 'error': None}, {'T': 330.0, 'case': 'vapor-only', 'V': 1.0, 'Cp': 46.86496, 'Cp_mass_kJ_kgK': 2.03268, 'Cp_kcal_kmolK': 11.20099, 'Cp_mass_kcal_kgK': 0.4858222, 'MW': 23.05575, 'error': None}]},
    ),
    "/vent_flow_calc": EndpointDoc(
        "vent_flow", TAG_VENT, "Flow versus opening: polynomial fit and flow estimate",
        """Fits a polynomial to measured flow versus valve opening and estimates the flow at further openings.

**Method.** Least-squares polynomial of the requested `degree`, equivalent to Excel
`LINEST(Flow, Opening^{1..degree}, TRUE, TRUE)` with Flow as known_y's and Opening as known_x's. The coefficients are
returned **highest power first** (the order of LINEST and of `numpy.polyval`), each with its standard error.
Flow = a·Opening^d + … + c·Opening + e.

**Degree.** A degree-d fit needs at least d + 2 points (so that one residual degree of freedom remains). If you request
a higher degree it is reduced automatically; `degree_used` and `degree_capped` say so, and a warning is added.
The fit also needs at least d + 1 different opening values; otherwise `fit_failed` is returned.

**Statistics** (`fit`). `r_squared`, `standard_error_y` (standard error of the estimate), `f_statistic`, `df_residual`,
`ss_regression`, `ss_residual`, `n_points` and the fitted `opening_range`. A statistic that is undefined is `null`:
`r_squared` and `f_statistic` when all flows are equal, `f_statistic` also when the data fit the polynomial exactly.

**Estimates** (`estimates`, one per entry of `estimate_at`). `opening` is what you asked for; with
`clip_to_fit_range` = true (default) an opening outside the fitted range is evaluated at the nearest end of the range
(`opening_used`), because a polynomial can behave wildly outside the data. `extrapolated` is true whenever the
requested opening lies outside the fitted range. The flow is raised to `min_flow` (default 0) if the polynomial gives
less, and `floor_applied` says so.

**Units.** Openings are in %. You give the flow in the unit of your data (for example kg/h); `flow_values`, the
coefficients, `standard_error_y` and every estimated flow in the response are in that same unit, and nothing is converted.

""" + VENT_INPUT,
        VENT_REQUEST,
        {"fit": {"degree_requested": 3, "degree_used": 1, "degree_capped": True, "n_points": 3, "equation": "Flow(Opening) = +2458.61*Opening +143.197", "terms": [{"power": 1, "coefficient": 2458.613, "standard_error": 0.9992376}, {"power": 0, "coefficient": 143.197, "standard_error": 60.21554}], "r_squared": 0.9999998, "standard_error_y": 49.63446, "f_statistic": 6054004.0, "df_residual": 1, "ss_regression": 14914520000.0, "ss_residual": 2463.579, "opening_range": {"min": 19.7, "max": 89.7}}, "estimates": [{"opening": 5.0, "opening_used": 19.7, "flow": 48577.87, "extrapolated": True, "floor_applied": False}, {"opening": 25.0, "opening_used": 25.0, "flow": 61608.51, "extrapolated": False, "floor_applied": False}, {"opening": 50.0, "opening_used": 50.0, "flow": 123073.8, "extrapolated": False, "floor_applied": False}, {"opening": 95.0, "opening_used": 89.7, "flow": 220680.8, "extrapolated": True, "floor_applied": False}, {"opening": 110.0, "opening_used": 89.7, "flow": 220680.8, "extrapolated": True, "floor_applied": False}], "warnings": ["The requested degree 3 was reduced to 1: 3 data points support at most degree 1.", "3 of 5 estimate openings lie outside the fitted range 19.7 to 89.7 % and were clamped to the fitted range."]},
        True,
    ),
}

EXAMPLE_META = {"request_id": "a1b2c3d4e5f6", "elapsed_ms": 14.2, "zs_normalized": False}
EXAMPLE_META_BASIC = {"request_id": "a1b2c3d4e5f6", "elapsed_ms": 3.1}

ERROR_EXAMPLES = {
    422: {
        "status": "error",
        "error": {
            "code": "validation_error",
            "message": "Request body is invalid.",
            "details": [{"field": "body", "message": "components (2) and zs (1) must have the same length"}],
        },
        "request_id": "a1b2c3d4e5f6",
    },
}


def success_example(doc: EndpointDoc, units: Dict[str, str]) -> Dict[str, Any]:
    return {"status": "success", "data": doc.data, "units": units,
            "meta": EXAMPLE_META_BASIC if doc.basic_meta else EXAMPLE_META}
