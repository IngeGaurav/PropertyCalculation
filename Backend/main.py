"""Thermodynamic property API. Run with:  uvicorn main:app --host 0.0.0.0 --port 8000"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.errors import ApiError
from app.routes import router
from app.schemas import CPCalcInput
from app.thermo_service import cp as _warm_up_calc

logging.basicConfig(
    level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("thermo_api")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run one small calculation at startup so thermo loads its databases before the first user."""
    try:
        await run_in_threadpool(_warm_up_calc, CPCalcInput())
        log.info("Warm-up calculation finished.")
    except Exception:
        log.exception("Warm-up failed (the API will still start).")
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Thermo Property API",
    version="2.0.0",
    description="Heat capacity, density, enthalpy, molecular weight and phase "
                "fractions of mixtures, powered by the `thermo` library.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# --------------------------------------------------------------- middleware
@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id, log one line per request, echo the id back."""
    request.state.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    log.info("%s %s -> %s (%.1f ms) rid=%s", request.method, request.url.path,
             response.status_code, (time.perf_counter() - started) * 1000,
             request.state.request_id)
    return response


# ------------------------------------------------------------ error handlers
def _error(request: Request, status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "status": "error",
            "error": {"code": code, "message": message, "details": details},
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    if exc.status_code >= 500:
        log.error("%s: %s rid=%s", exc.code, exc.message, request.state.request_id, exc_info=exc)
    return _error(request, exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body") or "body",
         "message": e["msg"].removeprefix("Value error, ")}
        for e in exc.errors()
    ]
    return _error(request, 422, "validation_error", "Request body is invalid.", details)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    codes = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}
    return _error(request, exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    # Full traceback goes to the log; the client only gets the request id.
    log.exception("Unhandled error rid=%s", request.state.request_id)
    return _error(request, 500, "internal_error",
                  "Unexpected server error. Quote the request_id when reporting it.")


# ------------------------------------------------------------------- routes
@app.get("/health", tags=["meta"], summary="Liveness check")
def health():
    return {"status": "ok", "version": app.version}


app.include_router(router)
