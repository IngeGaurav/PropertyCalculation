"""EOS-based (Peng-Robinson) stream property calculation with a three-phase flash.

Adapted from the reference implementation supplied by the project lead
(`analyze_stream`): one flash at T, P returns the vapor, aqueous and organic phases
and the mixture properties. Differences from the reference, all for use behind an API:

* components are CAS numbers (validated by the request model), so the water phase is always recognised;
* components with a mole fraction of 0 are removed before the flash (the flash time
  grows steeply with the number of components, and results are unchanged);
* components that resolve to the same chemical are merged;
* the flasher cache is bounded, thread-safe and keyed by the sorted CAS list;
* failures are raised as `ApiError` subclasses instead of raw Python exceptions.

The model cache and the equation-of-state parameter helpers here are shared with `enthalpy_service`.
No GUI/IO code here: `eos_stream` takes the validated request and returns the response model.
"""
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, List, Optional, Tuple

import numpy as np
from thermo import CEOSGas, CEOSLiquid, ChemicalConstantsPackage, FlashVLN, PRMIX
from thermo.interaction_parameters import IPDB

from .errors import CalculationError, FlashError, PropertyUnavailableError
from .schemas import CPCalcInput, EosMixture, EosPhase, EosStreamData
from .thermo_service import WATER_CAS, identify

KIJ_SOURCE = "ChemSep PR"
CACHE_MAX_ENTRIES = 64


# --------------------------------------------------------------------- cache
@dataclass
class _Entry:
    flasher: FlashVLN
    cas: Tuple[str, ...]
    lock: threading.Lock  # one flash at a time per flasher (thermo objects are not documented as thread-safe)


_cache: "OrderedDict[Hashable, _Entry]" = OrderedDict()
_cache_lock = threading.Lock()  # protects the dictionary
_build_lock = threading.Lock()  # one model is built at a time (building is the slow part)


def eos_kwargs_for(constants, kij_overrides: Optional[Dict[Tuple[str, str], float]] = None) -> dict:
    """Peng-Robinson parameters with binary interaction parameters (kij) from the ChemSep PR database.

    Pairs the database has no value for stay at 0 (ideal mixing). `kij_overrides` maps a CAS pair to a value
    that replaces the database value (used for documented, calibrated exceptions).
    """
    kwargs = dict(Tcs=constants.Tcs, Pcs=constants.Pcs, omegas=constants.omegas)
    try:
        kwargs["kijs"] = IPDB.get_ip_asymmetric_matrix(KIJ_SOURCE, constants.CASs, "kij")
    except Exception:
        pass  # no interaction-parameter data for this set: run with kij = 0
    if kij_overrides:
        n = len(constants.CASs)
        kijs = [list(row) for row in kwargs["kijs"]] if "kijs" in kwargs else [[0.0] * n for _ in range(n)]
        position = {c: i for i, c in enumerate(constants.CASs)}
        for (a, b), value in kij_overrides.items():
            if a in position and b in position:
                kijs[position[a]][position[b]] = kijs[position[b]][position[a]] = value
        kwargs["kijs"] = kijs
    return kwargs


def load_constants(cas: Tuple[str, ...]):
    """Pure-component constants and correlations; raises ApiError if data are missing."""
    try:
        constants, correlations = ChemicalConstantsPackage.from_IDs(list(cas))
    except Exception as exc:
        raise CalculationError(f"Could not load component data: {exc}") from exc

    missing = [
        c for c, tc, pc, w in zip(cas, constants.Tcs, constants.Pcs, constants.omegas)
        if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in (tc, pc, w))
    ]
    if missing:
        raise PropertyUnavailableError(
            "Critical properties (Tc, Pc, acentric factor) needed by the equation of state "
            "are not available for: " + ", ".join(missing),
            details={"components": missing},
        )
    return constants, correlations


def _build_entry(cas: Tuple[str, ...]) -> _Entry:
    constants, correlations = load_constants(cas)
    eos_kwargs = eos_kwargs_for(constants)
    try:
        gas = CEOSGas(PRMIX, eos_kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
        liquid = CEOSLiquid(PRMIX, eos_kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
        flasher = FlashVLN(constants, correlations, liquids=[liquid, liquid], gas=gas)
    except Exception as exc:
        raise CalculationError(f"Could not build the equation-of-state model: {exc}") from exc
    return _Entry(flasher=flasher, cas=cas, lock=threading.Lock())


def get_or_build(key: Hashable, builder: Callable[[], _Entry]) -> _Entry:
    """Cached, bounded (least recently used dropped) and thread-safe model lookup."""
    with _cache_lock:
        entry = _cache.get(key)
        if entry is not None:
            _cache.move_to_end(key)
            return entry
    with _build_lock:
        with _cache_lock:  # another thread may have built it while we waited
            entry = _cache.get(key)
            if entry is not None:
                return entry
        entry = builder()
        with _cache_lock:
            _cache[key] = entry
            while len(_cache) > CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)
        return entry


def _get_entry(cas: Tuple[str, ...]) -> _Entry:
    return get_or_build(("stream", cas), lambda: _build_entry(cas))


def cache_size() -> int:
    with _cache_lock:
        return len(_cache)


# ------------------------------------------------------------- calculation
def describe_case(has_vapor: bool, has_aqueous: bool, has_organic: bool) -> str:
    """Human-readable label for the phase situation found by the flash."""
    n_liq = int(has_aqueous) + int(has_organic)
    if has_vapor and n_liq == 0:
        return "vapor-only"
    if not has_vapor and n_liq == 1:
        return "liquid-only (single liquid phase)"
    if has_vapor and n_liq == 1:
        return "two-phase vapor-liquid (VL)"
    if not has_vapor and n_liq == 2:
        return "two-phase liquid-liquid (LL, aqueous+organic)"
    if has_vapor and n_liq == 2:
        return "three-phase vapor-liquid-liquid (VLLE)"
    return "no phases found (check inputs)"


def _merge_by_cas(req: CPCalcInput) -> Dict[str, float]:
    """CAS -> normalised mole fraction. Zero fractions are dropped, duplicates merged."""
    zs = req.normalized_zs()
    merged: Dict[str, float] = {}
    for name, z in zip(req.components, zs):
        if z <= 0:
            continue
        cas = identify(name).cas
        merged[cas] = merged.get(cas, 0.0) + float(z)
    return merged


def _phase(res, phase) -> Optional[EosPhase]:
    if phase is None:
        return None
    return EosPhase(
        beta=float(res.betas[res.phases.index(phase)]),
        MW=float(phase.MW()),
        Cp=float(phase.Cp()),
        rho_mass=float(phase.rho_mass()),
        rho_molar_kmol_m3=float(phase.rho()) / 1000.0,
    )


def eos_stream(req: CPCalcInput) -> EosStreamData:
    for name in req.components:  # validates every name first (also for zero-fraction ones)
        identify(name)
    merged = _merge_by_cas(req)
    cas = tuple(sorted(merged))
    total = sum(merged.values())
    zs = [merged[c] / total for c in cas]

    entry = _get_entry(cas)

    try:
        with entry.lock:
            res = entry.flasher.flash(T=req.T, P=req.P, zs=zs)
            vapor_phase = res.gas
            liquid_phases = [p for p in res.phases if p is not vapor_phase]

            water_idx = cas.index(WATER_CAS) if WATER_CAS in cas else None
            if water_idx is not None:
                liquid_phases = sorted(liquid_phases, key=lambda p: p.zs[water_idx], reverse=True)

            aqueous_phase = organic_phase = None
            if len(liquid_phases) == 1:
                only = liquid_phases[0]
                if water_idx is not None and only.zs[water_idx] > 0.5:
                    aqueous_phase = only
                else:
                    organic_phase = only
            elif len(liquid_phases) >= 2:
                aqueous_phase, organic_phase = liquid_phases[0], liquid_phases[1]

            vf = res.VF
            V = float(vf) if vf is not None and not math.isnan(vf) else 0.0
            data = EosStreamData(
                case=describe_case(vapor_phase is not None, aqueous_phase is not None, organic_phase is not None),
                V=V,
                L=1.0 - V,
                n_phases=len(res.phases),
                n_components_used=len(cas),
                vapor=_phase(res, vapor_phase),
                aqueous=_phase(res, aqueous_phase),
                organic=_phase(res, organic_phase),
                mixture=EosMixture(
                    MW=float(res.MW()),
                    Cp=float(res.Cp()),
                    Cp_mass_kJ_kgK=float(res.Cp_mass()) / 1000.0,
                    rho_mass=float(res.rho_mass()),
                    rho_molar_kmol_m3=float(res.rho()) / 1000.0,
                ),
            )
    except (FlashError, CalculationError, PropertyUnavailableError):
        raise
    except Exception as exc:
        raise FlashError(f"Equation-of-state flash failed at T={req.T:g} K, P={req.P:g} Pa: {exc}") from exc
    return data
