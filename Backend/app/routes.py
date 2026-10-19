"""HTTP layer: validation happens in the schemas, maths in thermo_service."""
import asyncio
import secrets
import time
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from . import schemas as s
from . import thermo_service as svc
from .config import settings
from .errors import CalculationTimeoutError

ERROR_RESPONSES = {
    401: {"model": s.ErrorResponse, "description": "Missing or invalid API key"},
    422: {"model": s.ErrorResponse, "description": "Invalid input or no thermodynamic data"},
    500: {"model": s.ErrorResponse, "description": "Unexpected server error"},
    504: {"model": s.ErrorResponse, "description": "Calculation timed out"},
}


def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    if settings.api_key and not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


router = APIRouter(dependencies=[Depends(require_api_key)], responses=ERROR_RESPONSES)


async def _execute(request: Request, fn: Callable, req, units: dict) -> dict:
    """Run a blocking thermo calculation off the event loop, with a time limit."""
    started = time.perf_counter()
    try:
        data = await asyncio.wait_for(
            run_in_threadpool(fn, req), timeout=settings.calc_timeout_seconds
        )
    except asyncio.TimeoutError:
        raise CalculationTimeoutError(
            f"Calculation exceeded {settings.calc_timeout_seconds:g}s."
        ) from None
    return {
        "data": data,
        "units": units,
        "meta": s.Meta(
            request_id=request.state.request_id,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            zs_normalized=req.was_normalized(),
        ),
    }


def _endpoint(path: str, fn: Callable, data_model, units: dict, summary: str, input_model):
    @router.post(path, response_model=s.ApiResponse[data_model], summary=summary, name=fn.__name__)
    async def handler(request: Request, input_data: input_model):  # type: ignore[valid-type]
        return await _execute(request, fn, input_data, units)

    return handler


C, S = s.CPCalcInput, s.StdEnthalpyInput
_endpoint("/cp_calc", svc.cp, s.CpData, s.CP_UNITS, "Heat capacity (liquid, vapor, mixture)", C)
_endpoint("/density_calc", svc.density, s.DensityData, s.DENSITY_UNITS, "Mixture density", C)
_endpoint("/enthalpy_calc", svc.enthalpy, s.EnthalpyData, s.ENTHALPY_UNITS, "Mixture enthalpy at T, P", C)
_endpoint("/mw_calc", svc.molecular_weight, s.MWData, s.MW_UNITS, "Molecular weight per phase", C)
_endpoint("/std_enthalpy_calc", svc.std_enthalpy, s.StdEnthalpyData, s.STD_ENTHALPY_UNITS,
          "Standard enthalpy (298.15 K, 1 atm)", S)
_endpoint("/vf_calc", svc.vapor_fraction, s.VFData, s.VF_UNITS, "Vapor / liquid fraction", C)
_endpoint("/triphase_cp_calc", svc.triphase_cp, s.TriphaseCpData, s.TRI_CP_UNITS,
          "Heat capacity: vapor / aqueous / organic", C)
_endpoint("/triphase_mw_calc", svc.triphase_mw, s.TriphaseMWData, s.TRI_MW_UNITS,
          "Molecular weight: vapor / aqueous / organic", C)
_endpoint("/triphase_vf_calc", svc.triphase_vf, s.TriphaseVFData, s.TRI_VF_UNITS,
          "Phase fractions: vapor / aqueous / organic", C)
