"""Heat capacity versus temperature: the EOS stream calculation repeated over a temperature range at one pressure.

The model is looked up once and each temperature is one flash (`eos_service.stream_at`). A temperature at which the
flash fails does not fail the request: that row has `Cp` = null and the reason in `error`, the others are returned.
"""
from .errors import ApiError, FlashError
from .eos_service import _get_entry, prepare, stream_at
from .schemas import CpCurveData, CpCurveInput, CpCurvePoint


KCAL = 4.184  # J per thermochemical calorie: 1 J/mol/K = 1/4.184 kcal/kmol/K and 1 kJ/kg/K = 1/4.184 kcal/kg/K


def cp_curve(req: CpCurveInput) -> CpCurveData:
    cas, zs = prepare(req)
    entry = _get_entry(cas)
    temperatures = req.temperatures()

    points = []
    for t in temperatures:
        try:
            d = stream_at(entry, cas, zs, t, req.P)
        except ApiError as exc:
            points.append(CpCurvePoint(T=t, error=exc.message))
            continue
        points.append(CpCurvePoint(T=t, case=d.case, V=d.V, Cp=d.mixture.Cp,
                                   Cp_mass_kJ_kgK=d.mixture.Cp_mass_kJ_kgK, MW=d.mixture.MW,
                                   Cp_kcal_kmolK=d.mixture.Cp / KCAL, Cp_mass_kcal_kgK=d.mixture.Cp_mass_kJ_kgK / KCAL))
    failed = sum(1 for p in points if p.error)
    if failed == len(points):  # nothing to show: report the cause as an error instead of a table of nulls
        raise FlashError(f"The calculation failed at every temperature from {temperatures[0]:g} K to {temperatures[-1]:g} K: {points[0].error}")
    return CpCurveData(n_points=len(points), n_failed=failed, n_components_used=len(cas),
                       T_start=temperatures[0], T_end=temperatures[-1], interval=req.interval, points=points)
