"""Enthalpy and heat duty of a stream between an inlet and an outlet state (Peng-Robinson EOS).

Adapted from the reference implementation supplied by the project lead. One composition, two states
(T_in, P_in) and (T_out, P_out), each flashed with the equation of state; the heat duty is the enthalpy
difference outlet minus inlet.

Thermodynamics as in the reference:
* single active component: `FlashPureVLS` with a Peng-Robinson gas and liquid;
* several active components: `FlashVLN` (vapor plus two liquid templates, so an aqueous/organic split is found),
  binary interaction parameters from the ChemSep PR database (missing pairs = 0);
* one documented, calibrated exception: the ethylene-ethane kij is set to 0.015. The database value (0.0078)
  makes the outlet vapor fraction of C2 streams too low and the duty about 42 % wrong against the plant
  reference; 0.015 narrows that to about 9 %.

Changes made for use behind an API (same as `eos_service`): components are resolved to CAS numbers, zero and
negligible mole fractions are removed before the flash, the same chemical given twice is merged, models are
cached (bounded, thread-safe), and failures are raised as `ApiError` subclasses.
"""
import math
import threading
from typing import Dict, Tuple

from thermo import CEOSGas, CEOSLiquid, PRMIX
from thermo.flash import FlashPureVLS, FlashVLN

from .eos_service import _Entry, eos_kwargs_for, get_or_build, load_constants
from .errors import ApiError, CalculationError, FlashError
from .schemas import EnthalpyDutyData, EnthalpyDutyInput, EnthalpyState, HeatDuty
from .thermo_service import identify

ETHYLENE_CAS = "74-85-1"
ETHANE_CAS = "74-84-0"
ETHYLENE_ETHANE_KIJ = 0.015  # calibrated, not database-sourced (see module docstring)
NEGLIGIBLE_FRACTION = 1e-12  # after normalisation; smaller fractions are treated as 0 (as in the reference)


def _active_composition(req: EnthalpyDutyInput) -> Dict[str, float]:
    """CAS -> normalised mole fraction, without zero / negligible components; duplicates merged."""
    zs = req.normalized_zs()
    merged: Dict[str, float] = {}
    for name, z in zip(req.components, zs):
        if z < NEGLIGIBLE_FRACTION:
            continue
        cas = identify(name).cas
        merged[cas] = merged.get(cas, 0.0) + float(z)
    total = sum(merged.values())
    return {cas: z / total for cas, z in merged.items()}


def _override_applies(cas: Tuple[str, ...]) -> bool:
    return len(cas) > 1 and ETHYLENE_CAS in cas and ETHANE_CAS in cas


def _build_entry(cas: Tuple[str, ...]) -> _Entry:
    constants, correlations = load_constants(cas)
    try:
        if len(cas) == 1:
            eos_kwargs = eos_kwargs_for(constants)
            eos_kwargs.pop("kijs", None)  # a pure component has no binary parameters
            gas = CEOSGas(PRMIX, eos_kwargs=eos_kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
            liquid = CEOSLiquid(PRMIX, eos_kwargs=eos_kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
            flasher = FlashPureVLS(constants, correlations, gas=gas, liquids=[liquid], solids=[])
        else:
            overrides = {(ETHYLENE_CAS, ETHANE_CAS): ETHYLENE_ETHANE_KIJ} if _override_applies(cas) else None
            eos_kwargs = eos_kwargs_for(constants, overrides)
            gas = CEOSGas(PRMIX, eos_kwargs=eos_kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
            liquid = CEOSLiquid(PRMIX, eos_kwargs=eos_kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
            flasher = FlashVLN(constants, correlations, liquids=[liquid, liquid], gas=gas)
    except Exception as exc:
        raise CalculationError(f"Could not build the equation-of-state model: {exc}") from exc
    return _Entry(flasher=flasher, cas=cas, lock=threading.Lock())


def _state(res) -> EnthalpyState:
    vf = res.VF
    return EnthalpyState(
        vapor_fraction=float(vf) if vf is not None and not math.isnan(vf) else 0.0,
        molecular_weight=float(res.MW()),
        enthalpy_molar=float(res.H()) / 1000.0,  # J/mol -> kJ/mol
        enthalpy_mass=float(res.H_mass()) / 1000.0,  # J/kg -> kJ/kg
    )


def eos_enthalpy(req: EnthalpyDutyInput) -> EnthalpyDutyData:
    for name in req.components:  # validates every name first, also zero-fraction ones
        identify(name)
    composition = _active_composition(req)
    if not composition:
        raise CalculationError("No component has a usable mole fraction.")
    cas = tuple(sorted(composition))
    zs = [composition[c] for c in cas]

    entry = get_or_build(("enthalpy", cas), lambda: _build_entry(cas))

    def flash(label: str, T: float, P: float):
        try:
            if len(cas) == 1:
                return entry.flasher.flash(T=T, P=P)
            return entry.flasher.flash(T=T, P=P, zs=zs)
        except ApiError:
            raise
        except Exception as exc:
            raise FlashError(
                f"Equation-of-state flash failed at the {label} (T={T:g} K, P={P:g} Pa): {exc}"
            ) from exc

    try:
        with entry.lock:
            res_in = flash("inlet", req.T_in, req.P_in)
            res_out = flash("outlet", req.T_out, req.P_out)
            inlet, outlet = _state(res_in), _state(res_out)
            duty_molar = (float(res_out.H()) - float(res_in.H())) / 1000.0
            duty_mass = (float(res_out.H_mass()) - float(res_in.H_mass())) / 1000.0
    except ApiError:
        raise
    except Exception as exc:
        raise FlashError(f"Enthalpy could not be evaluated: {exc}") from exc

    return EnthalpyDutyData(
        inlet=inlet,
        outlet=outlet,
        duty=HeatDuty(heat_duty_molar=duty_molar, sp_duty=duty_mass),
        n_components_used=len(cas),
        ethylene_ethane_kij_override=_override_applies(cas),
    )
