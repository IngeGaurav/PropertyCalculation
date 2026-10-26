"""Request and response models (the public contract of the API)."""
import math
import re
from typing import Any, Dict, Generic, List, Optional, TypeVar

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from .config import settings

T_ = TypeVar("T_")


# ----------------------------------------------------------------- requests
_CAS_FORMAT = re.compile(r"^\d{2,7}-\d{2}-\d$")


def cas_problem(value: str) -> Optional[str]:
    """Why `value` is not an acceptable CAS registry number, or None if it is one.

    A CAS number is three groups of digits (2 to 7, then 2, then 1) joined by hyphens, for example 7732-18-5.
    The last digit is a check digit, so a typing error such as 7732-18-4 is detected.
    """
    if not _CAS_FORMAT.match(value):
        if re.search(r"[A-Za-z]", value):
            return "a name, not a CAS number"
        return "not in CAS format (three groups of digits such as 7732-18-5)"
    digits = value.replace("-", "")
    total = sum((i + 1) * int(d) for i, d in enumerate(reversed(digits[:-1])))
    if total % 10 != int(digits[-1]):
        return "invalid CAS check digit (typing error?)"
    return None


class Composition(BaseModel):
    """Components + mole fractions, with all composition validation in one place."""

    components: List[str] = Field(
        default_factory=lambda: ["74-82-8", "74-84-0"],  # methane, ethane
        min_length=1,
        max_length=settings.max_components or None,
        description="CAS numbers only, for example '7732-18-5' for water. Names are rejected.",
    )
    zs: List[float] = Field(
        default_factory=lambda: [0.5, 0.5],
        min_length=1,
        max_length=settings.max_components or None,
        description="Mole fractions (not mole percent): moles of each component divided by the total moles, "
                    "same order as components. They should add up to 1; small differences are rescaled.",
    )

    @field_validator("components")
    @classmethod
    def _clean_components(cls, v: List[str]) -> List[str]:
        v = [c.strip() for c in v]
        if any(not c for c in v):
            raise ValueError("components cannot be empty")
        bad = [f"'{c}' ({cas_problem(c)})" for c in v if cas_problem(c)]
        if bad:
            raise ValueError("components must be CAS numbers such as 7732-18-5 (water); names are not accepted. "
                             "Not accepted: " + ", ".join(bad))
        if len(set(v)) != len(v):
            raise ValueError("duplicate components are not allowed")
        return v

    @model_validator(mode="after")
    def _check_composition(self):
        if len(self.components) != len(self.zs):
            raise ValueError(
                f"components ({len(self.components)}) and zs ({len(self.zs)}) must have the same length"
            )
        if any(not math.isfinite(z) for z in self.zs):
            raise ValueError("mole fractions must be finite numbers")
        if any(z < 0 for z in self.zs):
            raise ValueError("mole fractions cannot be negative")
        if sum(self.zs) <= 0:
            raise ValueError("sum of mole fractions must be greater than zero")
        return self

    def normalized_zs(self) -> np.ndarray:
        zs = np.array(self.zs, dtype=float)
        return zs / zs.sum()

    def was_normalized(self) -> bool:
        return not math.isclose(sum(self.zs), 1.0, rel_tol=0, abs_tol=1e-9)


class CPCalcInput(Composition):
    """Input for every state-dependent calculation endpoint."""

    T: float = Field(423.15, gt=0, allow_inf_nan=False, description="Temperature, K")
    P: float = Field(29411.81, gt=0, allow_inf_nan=False, description="Pressure, Pa")


class EnthalpyDutyInput(Composition):
    """Inlet and outlet conditions of one stream (same composition at both)."""

    T_in: float = Field(300.0, gt=0, allow_inf_nan=False, description="Inlet temperature, K")
    P_in: float = Field(254920.0, gt=0, allow_inf_nan=False, description="Inlet pressure, Pa")
    T_out: float = Field(368.0, gt=0, allow_inf_nan=False, description="Outlet temperature, K")
    P_out: float = Field(254720.0, gt=0, allow_inf_nan=False, description="Outlet pressure, Pa")


class VentFlowInput(BaseModel):
    """Opening/flow data points, the polynomial degree, and the openings at which to estimate the flow."""

    opening_values: List[float] = Field(
        default_factory=lambda: [19.7, 49.6, 89.7], min_length=3, max_length=10000,
        description="Valve opening data points, % (at least 3)")
    flow_values: List[float] = Field(
        default_factory=lambda: [48601.0, 122050.0, 220698.0], min_length=3, max_length=10000,
        description="Flow measured at each opening, in the unit of your data (for example kg/h). The response uses the same "
                    "unit; nothing is converted. Same length as opening_values")
    degree: int = Field(2, ge=1, le=10, description="Requested polynomial degree: 1 linear, 2 quadratic, 3 cubic ... (maximum 10). "
                                                    "Reduced automatically to what the number of points supports (n - 2).")
    estimate_at: List[float] = Field(
        default_factory=list, max_length=10000,
        description="Openings (%) at which to estimate the flow. May be empty to get only the fit.")
    clip_to_fit_range: bool = Field(True, description="If true, an opening outside the fitted range is clamped to the range "
                                                      "before the polynomial is evaluated (it is still flagged as extrapolated)")
    min_flow: float = Field(0.0, allow_inf_nan=False, description="Floor applied to every estimated flow (flow cannot be negative)")

    @model_validator(mode="after")
    def _check_data(self):
        if len(self.opening_values) != len(self.flow_values):
            raise ValueError(
                f"opening_values ({len(self.opening_values)}) and flow_values ({len(self.flow_values)}) must have the same length")
        for name in ("opening_values", "flow_values", "estimate_at"):
            if any(not math.isfinite(v) for v in getattr(self, name)):
                raise ValueError(f"{name} must contain finite numbers only")
        return self


# ------------------------------------------------------------ response data
class CpData(BaseModel):
    Cp_liquid: Optional[float] = Field(None, description="null when no liquid phase is present")
    Cp_vapor: Optional[float] = Field(None, description="null when no vapor phase is present")
    Cp_mix: float
    Vapor_fraction: float
    Liquid_fraction: float


class DensityData(BaseModel):
    rho_mix: float
    phase: Optional[str] = Field(None, description="'g', 'l' or 'l/g' as reported by thermo")


class MWData(BaseModel):
    MW_liquid: Optional[float] = Field(None, description="null when no liquid phase is present")
    MW_vapor: Optional[float] = Field(None, description="null when no vapor phase is present")
    MW_avg: float


class VFData(BaseModel):
    Vapor_fraction: float
    Liquid_fraction: float


class TriphaseCpData(BaseModel):
    Cp_aqueous: Optional[float] = None
    Cp_organic: Optional[float] = None
    Cp_vapor: Optional[float] = None
    Cp_mix: float


class TriphaseMWData(BaseModel):
    MW_aqueous: Optional[float] = None
    MW_organic: Optional[float] = None
    MW_vapor: Optional[float] = None
    MW_mix: float


class TriphaseVFData(BaseModel):
    vapor_fraction: float = Field(description="of total mixture")
    aqueous_fraction: float = Field(description="of total mixture")
    organic_fraction: float = Field(description="of total mixture")
    liquid_fraction: float = Field(description="aqueous + organic, of total mixture")
    water_in_liquid: float = Field(description="water mole fraction within the liquid")
    organic_in_liquid: float = Field(description="non-water mole fraction within the liquid")


# ------------------------------------------------- EOS (Peng-Robinson) stream
class EosPhase(BaseModel):
    beta: float = Field(description="phase fraction of the total mixture")
    MW: float = Field(description="g/mol")
    Cp: float = Field(description="J/mol/K")
    rho_mass: float = Field(description="kg/m^3")
    rho_molar_kmol_m3: float = Field(description="kmol/m^3")


class EosMixture(BaseModel):
    MW: float = Field(description="g/mol")
    Cp: float = Field(description="J/mol/K")
    Cp_mass_kJ_kgK: float = Field(description="kJ/kg/K")
    rho_mass: float = Field(description="kg/m^3")
    rho_molar_kmol_m3: float = Field(description="kmol/m^3")


class EosStreamData(BaseModel):
    case: str = Field(description="phase situation found by the flash, e.g. 'vapor-only' or 'three-phase vapor-liquid-liquid (VLLE)'")
    V: float = Field(description="vapor fraction (mole)")
    L: float = Field(description="liquid fraction (mole), total of aqueous and organic")
    n_phases: int
    n_components_used: int = Field(description="components with a mole fraction above 0 (zero-fraction components are not flashed)")
    vapor: Optional[EosPhase] = Field(None, description="null when there is no vapor")
    aqueous: Optional[EosPhase] = Field(None, description="null when there is no aqueous liquid")
    organic: Optional[EosPhase] = Field(None, description="null when there is no organic liquid")
    mixture: EosMixture


# ------------------------------------------------------ Enthalpy / heat duty
class EnthalpyState(BaseModel):
    vapor_fraction: float = Field(description="mole fraction")
    molecular_weight: float = Field(description="g/mol")
    enthalpy_molar: float = Field(description="kJ/mol")
    enthalpy_mass: float = Field(description="kJ/kg")


class HeatDuty(BaseModel):
    heat_duty_molar: float = Field(description="kJ/mol; outlet minus inlet. Positive = heat absorbed (heating), negative = heat released (cooling)")
    sp_duty: float = Field(description="kJ/kg; specific heat duty, outlet minus inlet")


class EnthalpyDutyData(BaseModel):
    inlet: EnthalpyState
    outlet: EnthalpyState
    duty: HeatDuty
    n_components_used: int = Field(description="components with a non-negligible mole fraction (the others are not part of the calculation)")
    ethylene_ethane_kij_override: bool = Field(
        description="true when ethylene and ethane are both present and the calibrated binary interaction parameter 0.015 was used for that pair")


# --------------------------------------------------------------- Vent flow fit
class VentTerm(BaseModel):
    power: int = Field(description="power of the opening for this term")
    coefficient: float
    standard_error: Optional[float] = Field(None, description="null when it cannot be computed")


class VentRange(BaseModel):
    min: float
    max: float


class VentFit(BaseModel):
    degree_requested: int
    degree_used: int
    degree_capped: bool = Field(description="true if the requested degree was reduced because there are too few points")
    n_points: int
    equation: str
    terms: List[VentTerm] = Field(description="highest power first (the order of Excel LINEST and numpy polyval)")
    r_squared: Optional[float] = Field(None, description="null when all flow values are equal")
    standard_error_y: Optional[float] = Field(None, description="standard error of the estimate (regression), flow unit; null when df_residual is 0")
    f_statistic: Optional[float] = Field(None, description="null when undefined (exact fit, or all flow values equal)")
    df_residual: int
    ss_regression: float
    ss_residual: float
    opening_range: VentRange = Field(description="opening range the curve was fitted on")


class VentEstimate(BaseModel):
    opening: float = Field(description="requested opening, %")
    opening_used: float = Field(description="opening used in the polynomial (differs from `opening` when clipped), %")
    flow: float = Field(description="estimated flow, after the minimum-flow floor")
    extrapolated: bool = Field(description="true if `opening` lies outside the fitted opening range")
    floor_applied: bool = Field(description="true if the polynomial gave a flow below min_flow and the floor was used")


class VentFlowData(BaseModel):
    fit: VentFit
    estimates: List[VentEstimate]
    warnings: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------- envelopes
class MetaBasic(BaseModel):
    request_id: str
    elapsed_ms: float


class ApiResponseBasic(BaseModel, Generic[T_]):
    """Envelope for endpoints that have no composition (so no `zs_normalized`)."""
    status: str = "success"
    data: T_
    units: Dict[str, str]
    meta: MetaBasic


class Meta(BaseModel):
    request_id: str
    elapsed_ms: float
    zs_normalized: bool = Field(description="true if the supplied zs did not sum to 1 and were rescaled")


class ApiResponse(BaseModel, Generic[T_]):
    status: str = "success"
    data: T_
    units: Dict[str, str]
    meta: Meta


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    status: str = "error"
    error: ErrorBody
    request_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = Field("ok", description="`ok` while the service is alive")
    version: str = Field(description="deployed API version")


# ------------------------------------------------------------------- units
CP_UNITS = {"Cp_liquid": "J/mol/K", "Cp_vapor": "J/mol/K", "Cp_mix": "J/mol/K",
            "Vapor_fraction": "mole fraction", "Liquid_fraction": "mole fraction"}
DENSITY_UNITS = {"rho_mix": "kg/m^3"}
MW_UNITS = {"MW_liquid": "g/mol", "MW_vapor": "g/mol", "MW_avg": "g/mol"}
VF_UNITS = {"Vapor_fraction": "mole fraction", "Liquid_fraction": "mole fraction"}
TRI_CP_UNITS = {"Cp_aqueous": "J/mol/K", "Cp_organic": "J/mol/K", "Cp_vapor": "J/mol/K",
                "Cp_mix": "J/mol/K"}
TRI_MW_UNITS = {"MW_aqueous": "g/mol", "MW_organic": "g/mol", "MW_vapor": "g/mol", "MW_mix": "g/mol"}
TRI_VF_UNITS = {k: "mole fraction" for k in TriphaseVFData.model_fields}
ENTHALPY_UNITS = {
    "vapor_fraction": "mole fraction", "molecular_weight": "g/mol",
    "enthalpy_molar": "kJ/mol", "enthalpy_mass": "kJ/kg",
    "heat_duty_molar": "kJ/mol", "sp_duty": "kJ/kg", "n_components_used": "count",
}
VENT_UNITS = {
    "opening": "%", "opening_used": "%", "flow": "unit of the supplied flow_values (not converted)",
    "coefficient": "flow unit per (%)^power", "standard_error": "flow unit per (%)^power",
    "r_squared": "dimensionless", "standard_error_y": "unit of the supplied flow_values",
    "f_statistic": "dimensionless", "df_residual": "count", "n_points": "count",
    "degree_requested": "count", "degree_used": "count",
    "ss_regression": "(flow unit)^2", "ss_residual": "(flow unit)^2",
}
EOS_UNITS = {
    "V": "mole fraction", "L": "mole fraction", "n_phases": "count", "n_components_used": "count",
    "beta": "mole fraction of the total mixture (per phase)",
    "MW": "g/mol", "Cp": "J/mol/K", "Cp_mass_kJ_kgK": "kJ/kg/K",
    "rho_mass": "kg/m^3", "rho_molar_kmol_m3": "kmol/m^3",
}
