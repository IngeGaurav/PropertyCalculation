"""All thermodynamics lives here. No FastAPI imports, so it is testable on its own.

Conventions (thermo 0.6.x): molar quantities are per mol, MW is g/mol,
Chemical.Cpl / Cpg / Hf are mass based (J/kg/K, J/kg); Chemical.Hfm and Mixture.Cplm / Cpgm / Hm are molar.
"""
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Optional

import numpy as np
from thermo import Mixture
from thermo.chemical import Chemical

from .errors import (
    CalculationError,
    FlashError,
    MissingWaterError,
    PropertyUnavailableError,
    UnknownComponentError,
)
from .schemas import (
    Composition,
    CPCalcInput,
    CpData,
    DensityData,
    EnthalpyData,
    MWData,
    StdEnthalpyData,
    StdEnthalpyInput,
    TriphaseCpData,
    TriphaseMWData,
    TriphaseVFData,
    VFData,
)

WATER_CAS = "7732-18-5"
PHASE_EPS = 1e-9
STD_T = 298.15  # K
STD_P = 101325.0  # Pa


# ---------------------------------------------------------------- helpers
@dataclass(frozen=True)
class Compound:
    name: str
    cas: str
    mw: float  # g/mol
    hf: Optional[float]  # J/mol, formation enthalpy at 298.15 K


@lru_cache(maxsize=1024)
def identify(name: str) -> Compound:
    """Resolve a name / CAS to constants that do not depend on T or P (cached)."""
    try:
        chem = Chemical(name)
    except Exception as exc:
        raise UnknownComponentError(
            f"Component '{name}' was not recognised.", details={"component": name}
        ) from exc
    if chem.MW is None:
        raise PropertyUnavailableError(
            f"No molecular weight available for '{name}'.", details={"component": name}
        )
    return Compound(name=name, cas=chem.CAS, mw=float(chem.MW), hf=_opt(chem.Hfm))  # molar; chem.Hf is mass based (J/kg)


def _opt(x) -> Optional[float]:
    """float(x) if x is a usable number, else None."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _need(x, label: str) -> float:
    v = _opt(x)
    if v is None:
        raise PropertyUnavailableError(f"{label} is not available for this mixture/state.")
    return v


@dataclass
class FlashState:
    mix: Mixture
    compounds: List[Compound]
    V: float
    L: float
    xs: Optional[np.ndarray]  # liquid composition, None if no liquid
    ys: Optional[np.ndarray]  # vapor composition, None if no vapor

    @property
    def mws(self) -> np.ndarray:
        return np.array([c.mw for c in self.compounds])

    @property
    def has_vapor(self) -> bool:
        return self.V > PHASE_EPS

    @property
    def has_liquid(self) -> bool:
        return self.L > PHASE_EPS


def _build(req: Composition, T: float, P: float, need_flash: bool = True) -> FlashState:
    compounds = [identify(c) for c in req.components]
    zs = req.normalized_zs()
    try:
        mix = Mixture(IDs=req.components, zs=zs, T=T, P=P)
    except Exception as exc:
        raise CalculationError(f"Could not create mixture: {exc}") from exc

    if not need_flash:
        return FlashState(mix, compounds, 0.0, 1.0, None, None)

    try:
        vf = mix.VF
    except Exception as exc:
        raise FlashError(f"Flash calculation failed: {exc}") from exc
    if vf is None:
        raise FlashError("Could not determine vapor fraction (flash failed).")
    V = min(max(float(vf), 0.0), 1.0)
    xs = np.array(mix.xs, dtype=float) if mix.xs is not None else None
    ys = np.array(mix.ys, dtype=float) if mix.ys is not None else None
    return FlashState(mix, compounds, V, 1.0 - V, xs, ys)


def flash(req: CPCalcInput) -> FlashState:
    return _build(req, req.T, req.P)


# ------------------------------------------------------------- single-phase
def cp(req: CPCalcInput) -> CpData:
    st = flash(req)
    # thermo reports a (hypothetical) value for an absent phase; we only use present phases.
    cp_l = _need(st.mix.Cplm, "Liquid heat capacity") if st.has_liquid else None
    cp_v = _need(st.mix.Cpgm, "Vapor heat capacity") if st.has_vapor else None
    cp_mix = st.L * (cp_l or 0.0) + st.V * (cp_v or 0.0)
    return CpData(Cp_liquid=cp_l, Cp_vapor=cp_v, Cp_mix=cp_mix,
                  Vapor_fraction=st.V, Liquid_fraction=st.L)


def density(req: CPCalcInput) -> DensityData:
    st = _build(req, req.T, req.P, need_flash=False)
    return DensityData(rho_mix=_need(st.mix.rho, "Density"), phase=st.mix.phase)


def enthalpy(req: CPCalcInput) -> EnthalpyData:
    st = _build(req, req.T, req.P, need_flash=False)
    hm = _need(st.mix.Hm, "Enthalpy")  # J/mol
    mw = _need(st.mix.MW, "Molecular weight")  # g/mol
    return EnthalpyData(H_mix_molar=hm, H_mix_mass=hm / mw * 1000.0)


def molecular_weight(req: CPCalcInput) -> MWData:
    st = flash(req)
    mws = st.mws
    return MWData(
        MW_liquid=float(np.sum(st.xs * mws)) if st.has_liquid and st.xs is not None else None,
        MW_vapor=float(np.sum(st.ys * mws)) if st.has_vapor and st.ys is not None else None,
        MW_avg=_need(st.mix.MW, "Average molecular weight"),
    )


def vapor_fraction(req: CPCalcInput) -> VFData:
    st = flash(req)
    return VFData(Vapor_fraction=st.V, Liquid_fraction=st.L)


def std_enthalpy(req: StdEnthalpyInput) -> StdEnthalpyData:
    """Mole-fraction-weighted formation enthalpy at 298.15 K, 1 atm."""
    compounds = [identify(c) for c in req.components]
    missing = [c.name for c in compounds if c.hf is None]
    if missing:
        # The old code silently used 0 here, which produced a wrong answer.
        raise PropertyUnavailableError(
            "Formation enthalpy (Hf) is not available for: " + ", ".join(missing),
            details={"components": missing},
        )
    zs = req.normalized_zs()
    h = float(np.sum(zs * np.array([c.hf for c in compounds])))  # J/mol
    mw = float(np.sum(zs * np.array([c.mw for c in compounds])))  # g/mol
    return StdEnthalpyData(H_mix_std_molar=h, H_mix_std_mass=h / mw * 1000.0)


# ------------------------------------------------------------------ triphase
@dataclass
class Triphase:
    """Vapor / aqueous / organic split.

    thermo's Mixture does a VLE flash only. The liquid is split into 'aqueous'
    (pure water) and 'organic' (everything else) as an approximation.
    """
    st: FlashState
    water_idx: int
    x_water: float  # water mole fraction in the liquid
    x_org: Optional[np.ndarray]  # normalised non-water liquid composition


def triphase(req: CPCalcInput) -> Triphase:
    st = flash(req)
    cas = [c.cas for c in st.compounds]
    if WATER_CAS not in cas:
        raise MissingWaterError(
            "Triphase endpoints require water in the mixture (use 'water' or '7732-18-5')."
        )
    idx = cas.index(WATER_CAS)

    x_water, x_org = 0.0, None
    if st.has_liquid and st.xs is not None:
        x_water = float(st.xs[idx])
        raw = st.xs.copy()
        raw[idx] = 0.0
        total = raw.sum()
        if total > PHASE_EPS:
            x_org = raw / total
    return Triphase(st, idx, x_water, x_org)


def triphase_vf(req: CPCalcInput) -> TriphaseVFData:
    tp = triphase(req)
    st = tp.st
    org_in_liq = 1.0 - tp.x_water if st.has_liquid else 0.0
    return TriphaseVFData(
        vapor_fraction=st.V,
        aqueous_fraction=st.L * tp.x_water,
        organic_fraction=st.L * org_in_liq,
        liquid_fraction=st.L,
        water_in_liquid=tp.x_water,
        organic_in_liquid=org_in_liq,
    )


def triphase_mw(req: CPCalcInput) -> TriphaseMWData:
    tp = triphase(req)
    st, mws = tp.st, tp.st.mws
    return TriphaseMWData(
        MW_aqueous=float(mws[tp.water_idx]) if st.has_liquid and tp.x_water > PHASE_EPS else None,
        MW_organic=float(np.sum(tp.x_org * mws)) if tp.x_org is not None else None,
        MW_vapor=float(np.sum(st.ys * mws)) if st.has_vapor and st.ys is not None else None,
        MW_mix=_need(st.mix.MW, "Average molecular weight"),
    )


def _molar_cp(name: str, T: float, P: float, mw: float, phase: str) -> float:
    """Pure-component molar Cp (J/mol/K). thermo gives J/kg/K, so convert with MW."""
    chem = Chemical(name, T=T, P=P)
    mass_cp = chem.Cpg if phase == "g" else chem.Cpl
    return _need(mass_cp, f"{'Vapor' if phase == 'g' else 'Liquid'} Cp of '{name}'") * mw / 1000.0


def triphase_cp(req: CPCalcInput) -> TriphaseCpData:
    tp = triphase(req)
    st, T, P = tp.st, req.T, req.P
    names = [c.name for c in st.compounds]
    mws = st.mws

    cp_vap = None
    if st.has_vapor and st.ys is not None:
        cp_vap = sum(
            y * _molar_cp(n, T, P, mw, "g")
            for n, y, mw in zip(names, st.ys, mws) if y > PHASE_EPS
        )

    cp_aq = cp_org = None
    if st.has_liquid:
        if tp.x_water > PHASE_EPS:
            cp_aq = _molar_cp(names[tp.water_idx], T, P, mws[tp.water_idx], "l")
        if tp.x_org is not None:
            cp_org = sum(
                x * _molar_cp(n, T, P, mw, "l")
                for n, x, mw in zip(names, tp.x_org, mws) if x > PHASE_EPS
            )

    liquid_cp = tp.x_water * (cp_aq or 0.0) + (1.0 - tp.x_water) * (cp_org or 0.0)
    cp_mix = st.V * (cp_vap or 0.0) + st.L * liquid_cp
    return TriphaseCpData(Cp_aqueous=_opt(cp_aq), Cp_organic=_opt(cp_org),
                          Cp_vapor=_opt(cp_vap), Cp_mix=float(cp_mix))
