"""Domain exceptions. Each carries the HTTP status and a stable machine code."""
from typing import Any, Optional


class ApiError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.details = details


class UnknownComponentError(ApiError):
    status_code = 422
    code = "unknown_component"


class FlashError(ApiError):
    """Phase-equilibrium (flash) calculation did not converge / returned nothing."""
    status_code = 422
    code = "flash_failed"


class PropertyUnavailableError(ApiError):
    """thermo has no data for the requested property at this state."""
    status_code = 422
    code = "property_unavailable"


class MissingWaterError(ApiError):
    status_code = 422
    code = "water_required"


class CalculationTimeoutError(ApiError):
    status_code = 504
    code = "calculation_timeout"


class CalculationError(ApiError):
    """Unexpected failure inside thermo."""
    status_code = 500
    code = "calculation_failed"
