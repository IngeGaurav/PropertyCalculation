"""Flow = f(Opening %) polynomial regression and flow estimation (vent calculation).

Adapted from the reference module supplied by the project lead (`flow_vs_opening_estimator.py`).
The fit is the equivalent of Excel's  LINEST(Flow, Opening^{1..degree}, TRUE, TRUE)  with Flow as known_y's and
Opening as known_x's: coefficients are returned highest power first, with their standard errors, R squared, the
standard error of the estimate, the F statistic, the residual degrees of freedom and the regression / residual sums
of squares. `degree` is capped to what the data support (n - 2, so that at least one residual degree of freedom
remains).

Changes made for use behind an API (the numerics are the reference's):
* inputs are validated by the request model; a fit that cannot be solved (too few DISTINCT openings for the
  degree) is reported as `fit_failed` instead of silently returning a rank-deficient fit;
* NaN / infinity can not be carried by JSON, so undefined statistics are returned as null (the reference returned
  NaN, or +inf for an exact fit). The F statistic is also null when all flows are equal, or when the data fit the
  polynomial exactly (the reference printed a meaningless value from rounding noise, e.g. 7.7e30 or -0.5);
* the result carries the degree requested, the degree used and a `degree_capped` flag, and human-readable warnings.

No FastAPI imports: `vent_flow` takes the validated request and returns the response model.
"""
import math
from typing import List, Optional

import numpy as np

from .errors import FitError
from .schemas import VentEstimate, VentFit, VentFlowData, VentFlowInput, VentRange, VentTerm

# residual / total sum of squares below which the data are treated as an exact fit (F is then meaningless)
EXACT_FIT_RATIO = 1e-20


def _num(x: float) -> Optional[float]:
    """float(x), or None when x is NaN / infinite (JSON can not carry those)."""
    x = float(x)
    return x if math.isfinite(x) else None


def _equation(coefficients: np.ndarray, var: str = "Opening") -> str:
    n = len(coefficients)
    terms = []
    for i, c in enumerate(coefficients):
        power = n - 1 - i
        if power == 0:
            terms.append(f"{c:+.6g}")
        elif power == 1:
            terms.append(f"{c:+.6g}*{var}")
        else:
            terms.append(f"{c:+.6g}*{var}^{power}")
    return f"Flow({var}) = " + " ".join(terms)


def fit_flow_vs_opening(x: np.ndarray, y: np.ndarray, degree: int):
    """Least-squares polynomial fit. Returns (fit model, coefficient array)."""
    n = x.size
    degree_used = min(degree, n - 2)  # largest degree that leaves df_resid >= 1
    p = degree_used + 1

    distinct = int(np.unique(x).size)
    if distinct < p:
        raise FitError(
            f"A degree-{degree_used} fit needs at least {p} different opening values; the data contain only {distinct}.",
            details={"distinct_opening_values": distinct, "required": p, "degree_used": degree_used},
        )

    X = np.vander(x, N=p, increasing=False)  # highest power first
    try:
        coeffs = np.linalg.lstsq(X, y, rcond=None)[0]
    except np.linalg.LinAlgError as exc:
        raise FitError(f"The least-squares fit did not converge: {exc}") from exc
    if not np.all(np.isfinite(coeffs)):
        raise FitError("The fit produced non-finite coefficients; check the magnitude of the data.")

    resid = y - X @ coeffs
    ss_resid = float(np.sum(resid ** 2))
    ss_total = float(np.sum((y - np.mean(y)) ** 2))
    ss_reg = ss_total - ss_resid
    df_resid = n - p
    r_squared = 1.0 - ss_resid / ss_total if ss_total > 0 else None

    if df_resid > 0:
        mse = ss_resid / df_resid
        try:
            xtx_inv = np.linalg.inv(X.T @ X)
            se_coeffs = [_num(v) for v in np.sqrt(np.clip(np.diag(mse * xtx_inv), 0, None))]
        except np.linalg.LinAlgError:
            se_coeffs = [None] * p
        se_y = _num(math.sqrt(mse))
        df_reg = p - 1
        f_stat = None
        exact_fit = ss_total > 0 and ss_resid <= EXACT_FIT_RATIO * ss_total
        if ss_total > 0 and df_reg > 0 and ss_resid > 0 and ss_reg > 0 and not exact_fit:
            f_stat = _num((ss_reg / df_reg) / (ss_resid / df_resid))
    else:  # cannot happen for degree <= n - 2, kept for safety
        se_coeffs = [None] * p
        se_y = None
        f_stat = None

    fit = VentFit(
        degree_requested=degree,
        degree_used=degree_used,
        degree_capped=degree_used < degree,
        n_points=n,
        equation=_equation(coeffs),
        terms=[VentTerm(power=p - 1 - i, coefficient=float(c), standard_error=se)
               for i, (c, se) in enumerate(zip(coeffs, se_coeffs))],
        r_squared=_num(r_squared) if r_squared is not None else None,
        standard_error_y=se_y,
        f_statistic=f_stat,
        df_residual=df_resid,
        ss_regression=_num(ss_reg) or 0.0,
        ss_residual=_num(ss_resid) or 0.0,
        opening_range=VentRange(min=float(np.min(x)), max=float(np.max(x))),
    )
    return fit, coeffs


def estimate_flow(coeffs: np.ndarray, lo: float, hi: float, opening: float,
                  clip_to_fit_range: bool, min_flow: float) -> VentEstimate:
    extrapolated = opening < lo or opening > hi
    used = min(max(opening, lo), hi) if clip_to_fit_range else opening
    raw = float(np.polyval(coeffs, used))
    if not math.isfinite(raw):
        raise FitError(f"The fitted curve gives a non-finite flow at opening {opening:g} %.")
    return VentEstimate(
        opening=opening,
        opening_used=used,
        flow=max(raw, min_flow),
        extrapolated=extrapolated,
        floor_applied=raw < min_flow,
    )


def vent_flow(req: VentFlowInput) -> VentFlowData:
    x = np.asarray(req.opening_values, dtype=float)
    y = np.asarray(req.flow_values, dtype=float)

    fit, coeffs = fit_flow_vs_opening(x, y, req.degree)
    lo, hi = fit.opening_range.min, fit.opening_range.max
    estimates = [estimate_flow(coeffs, lo, hi, float(o), req.clip_to_fit_range, req.min_flow) for o in req.estimate_at]

    warnings: List[str] = []
    if fit.degree_capped:
        warnings.append(
            f"The requested degree {fit.degree_requested} was reduced to {fit.degree_used}: "
            f"{fit.n_points} data points support at most degree {fit.n_points - 2}.")
    if fit.r_squared is None:
        warnings.append("All flow values are equal, so R squared and the F statistic are undefined.")
    if fit.f_statistic is None and fit.r_squared is not None:
        warnings.append("The data fit the polynomial exactly; the F statistic is not meaningful and is returned as null.")
    outside = sum(1 for e in estimates if e.extrapolated)
    if outside:
        action = "clamped to the fitted range" if req.clip_to_fit_range else "extrapolated with the polynomial"
        warnings.append(f"{outside} of {len(estimates)} estimate openings lie outside the fitted range "
                        f"{lo:g} to {hi:g} % and were {action}.")
    floored = sum(1 for e in estimates if e.floor_applied)
    if floored:
        warnings.append(f"{floored} estimated flow(s) were below the minimum flow {req.min_flow:g} and were raised to it.")
    return VentFlowData(fit=fit, estimates=estimates, warnings=warnings)
