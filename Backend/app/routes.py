"""HTTP layer: validation happens in the schemas, maths in thermo_service / eos_service."""
import asyncio
import secrets
import time
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from . import api_docs as docs
from . import enthalpy_service as enth
from . import eos_service as eos
from . import schemas as s
from . import thermo_service as svc
from . import vent_service as vent
from .config import settings
from .errors import CalculationTimeoutError

ERROR_RESPONSES = {
    401: {"model": s.ErrorResponse, "description": "Missing or invalid API key (only when an API key is enabled)."},
    422: {
        "model": s.ErrorResponse,
        "description": "Invalid input (`validation_error`), unknown component (`unknown_component`), failed flash "
                       "(`flash_failed`), missing data (`property_unavailable`), no water for a triphase call (`water_required`) "
                       "or data that cannot be fitted (`fit_failed`).",
        "content": {"application/json": {"example": docs.ERROR_EXAMPLES[422]}},
    },
    500: {"model": s.ErrorResponse, "description": "Unexpected server error (`internal_error`). Quote the `request_id`."},
    504: {"model": s.ErrorResponse, "description": "The calculation exceeded the time limit (`calculation_timeout`)."},
}


def require_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key", description="Only needed when an API key is enabled on the server."),
) -> None:
    if settings.api_key and not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


router = APIRouter(dependencies=[Depends(require_api_key)], responses=ERROR_RESPONSES)


async def _execute(request: Request, fn: Callable, req, units: dict) -> dict:
    """Run a blocking calculation off the event loop, with a time limit."""
    started = time.perf_counter()
    try:
        data = await asyncio.wait_for(
            run_in_threadpool(fn, req), timeout=settings.calc_timeout_seconds
        )
    except asyncio.TimeoutError:
        raise CalculationTimeoutError(
            f"Calculation exceeded {settings.calc_timeout_seconds:g}s."
        ) from None
    meta = {
        "request_id": request.state.request_id,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    if hasattr(req, "was_normalized"):  # endpoints with a composition also report whether zs were rescaled
        meta["zs_normalized"] = req.was_normalized()
    return {
        "data": data,
        "units": units,
        "meta": meta,
    }


def _endpoint(path: str, fn: Callable, data_model, units: dict, input_model):
    doc = docs.ENDPOINT_DOCS[path]

    @router.post(
        path,
        response_model=(s.ApiResponseBasic if doc.basic_meta else s.ApiResponse)[data_model],
        tags=[doc.tag],
        summary=doc.summary,
        description=doc.description,
        operation_id=doc.operation_id,
        responses={200: {"content": {"application/json": {"example": docs.success_example(doc, units)}}}},
        openapi_extra={"requestBody": {"content": {"application/json": {"example": doc.request}}}},
    )
    async def handler(request: Request, input_data: input_model):  # type: ignore[valid-type]
        return await _execute(request, fn, input_data, units)

    return handler


C = s.CPCalcInput

# --- Property APIs: one endpoint per property (vapor-liquid equilibrium model) ---
_endpoint("/cp_calc", svc.cp, s.CpData, s.CP_UNITS, C)
_endpoint("/density_calc", svc.density, s.DensityData, s.DENSITY_UNITS, C)
_endpoint("/mw_calc", svc.molecular_weight, s.MWData, s.MW_UNITS, C)
_endpoint("/vf_calc", svc.vapor_fraction, s.VFData, s.VF_UNITS, C)
_endpoint("/triphase_cp_calc", svc.triphase_cp, s.TriphaseCpData, s.TRI_CP_UNITS, C)
_endpoint("/triphase_mw_calc", svc.triphase_mw, s.TriphaseMWData, s.TRI_MW_UNITS, C)
_endpoint("/triphase_vf_calc", svc.triphase_vf, s.TriphaseVFData, s.TRI_VF_UNITS, C)

# --- EOS Stream API: Peng-Robinson equation of state, three-phase flash ---
_endpoint("/eos_stream_calc", eos.eos_stream, s.EosStreamData, s.EOS_UNITS, C)

# --- Enthalpy API: enthalpy at an inlet and an outlet condition, and the heat duty (Peng-Robinson) ---
_endpoint("/eos_enthalpy_calc", enth.eos_enthalpy, s.EnthalpyDutyData, s.ENTHALPY_UNITS, s.EnthalpyDutyInput)

# --- Vent API: polynomial fit of flow versus valve opening, and flow estimates (no composition involved) ---
_endpoint("/vent_flow_calc", vent.vent_flow, s.VentFlowData, s.VENT_UNITS, s.VentFlowInput)
