# Thermo Property API

A web service that calculates thermodynamic properties of multi-component mixtures — heat capacity, density, molecular weight and phase fractions — using the Python [`thermo`](https://github.com/CalebBell/thermo) library. It offers four groups — individual **Property APIs**, a complete-stream **EOS Stream API**, an **Enthalpy API** for enthalpy and heat duty and a **Vent API** (flow versus valve opening) — and includes a browser-based tester with a tab for each.

| | |
|---|---|
| **Production address** | `http://192.168.11.216:4300/` (web tester) · `http://192.168.11.216:4300/api` (API) |
| **Interactive API docs** | `http://192.168.11.216:4300/api/docs` |
| **Version** | 2.3.0 |

## Documentation

| Document | Read it when you want to… |
|---|---|
| [docs/Thermo-API-Integration-Guide.docx](docs/Thermo-API-Integration-Guide.docx) (and [PDF](docs/Thermo-API-Integration-Guide.pdf)) | **Hand to an integrator or vendor**: a short guide with one page per endpoint (request, response, errors); regenerate it with [docs/vendor-guide](docs/vendor-guide/README.md) |
| [docs/02-API-Reference.md](docs/02-API-Reference.md) | **Use the API**: every endpoint with request/response examples, error codes, client code |
| [docs/01-Deployment-Guide.md](docs/01-Deployment-Guide.md) | **Deploy or operate it**: server setup, services, logs, how to release an update, rollback, troubleshooting |
| [docs/03-Backend-Design-and-Changes.md](docs/03-Backend-Design-and-Changes.md) | **Maintain or extend the code**: structure, design, defects fixed, differences from the original version |

## Repository layout

```
Backend/      FastAPI application (main.py, app/, tests/, requirements*.txt)
Frontend/     index.html — the web tester (served by nginx)
deploy/       nginx-thermo-block.conf (server block), run_backend.bat (manual start)
docs/         Documentation
```

## Quick start (development PC)

```bat
cd Backend
python -m venv ..\venv
..\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
..\venv\Scripts\python.exe -m pytest -q tests
..\venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

Then open `http://localhost:8000/docs`, or open `Frontend/index.html` in a browser (it connects to `http://localhost:8000` when opened as a file).

## Example call

```bash
curl -X POST http://192.168.11.216:4300/api/eos_stream_calc \
  -H "Content-Type: application/json" \
  -d '{"T":300,"P":101325,"components":["water","hexane"],"zs":[0.5,0.5]}'
```

## Endpoints

| Group | Endpoints |
|---|---|
| **Property APIs** (one endpoint per property) | `POST /cp_calc` · `/density_calc` · `/mw_calc` · `/vf_calc` · `/triphase_cp_calc` · `/triphase_mw_calc` · `/triphase_vf_calc` |
| **EOS Stream API** (complete stream, Peng-Robinson three-phase flash) | `POST /eos_stream_calc` |
| **Enthalpy API** (enthalpy at an inlet and an outlet condition, heat duty) | `POST /eos_enthalpy_calc` |
| **Vent API** (polynomial fit of flow versus valve opening, flow estimates) | `POST /vent_flow_calc` |
| **System** | `GET /health` |

Details are in the [API Reference](docs/02-API-Reference.md). Interactive documentation: `/api/docs`.
