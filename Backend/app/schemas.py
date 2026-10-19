"""Request and response models (the public contract of the API)."""
import math
from typing import Any, Dict, Generic, List, Optional, TypeVar

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

from .config import settings

T_ = TypeVar("T_")


# ----------------------------------------------------------------- requests
class Composition(BaseModel):
    """Components + mole fractions, with all composition validation in one place."""

    components: List[str] = Field(
        default_factory=lambda: ["methane", "ethane"],
        min_length=1,
        max_length=settings.max_components,
        description="Names or CAS numbers (e.g. 'water' or '7732-18-5')",
    )
    zs: List[float] = Field(
        default_factory=lambda: [0.5, 0.5],
        min_length=1,
        max_length=settings.max_components,
        description="Mole fractions, same order as components. Normalised to sum 1.",
    )

    @field_validator("components")
    @classmethod
    def _clean_components(cls, v: List[str]) -> List[str]:
        v = [c.strip() for c in v]
        if any(not c for c in v):
            raise ValueError("component names cannot be empty")
        lowered = [c.lower() for c in v]
        if len(set(lowered)) != len(lowered):
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


class StdEnthalpyInput(Composition):
    """Standard enthalpy is fixed at 298.15 K / 101325 Pa, so T and P are not part of the input."""


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


class EnthalpyData(BaseModel):
    H_mix_molar: float
    H_mix_mass: float


class MWData(BaseModel):
    MW_liquid: Optional[float] = Field(None, description="null when no liquid phase is present")
    MW_vapor: Optional[float] = Field(None, description="null when no vapor phase is present")
    MW_avg: float


class StdEnthalpyData(BaseModel):
    H_mix_std_molar: float
    H_mix_std_mass: float


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


# ---------------------------------------------------------------- envelopes
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


# ------------------------------------------------------------------- units
CP_UNITS = {"Cp_liquid": "J/mol/K", "Cp_vapor": "J/mol/K", "Cp_mix": "J/mol/K",
            "Vapor_fraction": "mole fraction", "Liquid_fraction": "mole fraction"}
DENSITY_UNITS = {"rho_mix": "kg/m^3"}
ENTHALPY_UNITS = {"H_mix_molar": "J/mol", "H_mix_mass": "J/kg"}
MW_UNITS = {"MW_liquid": "g/mol", "MW_vapor": "g/mol", "MW_avg": "g/mol"}
STD_ENTHALPY_UNITS = {"H_mix_std_molar": "J/mol", "H_mix_std_mass": "J/kg"}
VF_UNITS = {"Vapor_fraction": "mole fraction", "Liquid_fraction": "mole fraction"}
TRI_CP_UNITS = {"Cp_aqueous": "J/mol/K", "Cp_organic": "J/mol/K", "Cp_vapor": "J/mol/K",
                "Cp_mix": "J/mol/K"}
TRI_MW_UNITS = {"MW_aqueous": "g/mol", "MW_organic": "g/mol", "MW_vapor": "g/mol", "MW_mix": "g/mol"}
TRI_VF_UNITS = {k: "mole fraction" for k in TriphaseVFData.model_fields}
