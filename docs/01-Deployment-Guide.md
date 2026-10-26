# Thermo Property API — Deployment & Operations Guide

| | |
|---|---|
| **System** | Thermo Property API (FastAPI backend + static web tester) |
| **Version documented** | API 3.0.0 (initial deployment on 22 October 2026 was 2.0.0; upgrades in Appendices C, D, E and F) |
| **Deployed on** | Windows server `192.168.11.216` |
| **Deployment date** | 22 October 2026 |
| **Audience** | Developers and administrators who deploy, operate or update the service |
| **Related documents** | [02-API-Reference.md](02-API-Reference.md), [03-Backend-Design-and-Changes.md](03-Backend-Design-and-Changes.md) |

---

## Contents

1. [Quick reference](#1-quick-reference)
2. [Overview](#2-overview)
3. [Architecture](#3-architecture)
4. [Environment inventory](#4-environment-inventory)
5. [Directory layout](#5-directory-layout)
6. [Initial deployment procedure](#6-initial-deployment-procedure)
7. [Verification checklist](#7-verification-checklist)
8. [Day-to-day operations](#8-day-to-day-operations)
9. [Releasing changes (how to deploy an update)](#9-releasing-changes-how-to-deploy-an-update)
10. [Configuration reference](#10-configuration-reference)
11. [Security notes](#11-security-notes)
12. [Troubleshooting](#12-troubleshooting)
13. [Known constraints](#13-known-constraints)
14. [Appendix A — Complete command list](#appendix-a--complete-command-list)
15. [Appendix B — Uninstall / rollback of the whole deployment](#appendix-b--uninstall--rollback-of-the-whole-deployment)
16. [Appendix C — Upgrade from 2.0.0 to 2.1.0](#appendix-c--upgrade-from-200-to-210)
17. [Appendix D — Upgrade from 2.1.0 to 2.2.0](#appendix-d--upgrade-from-210-to-220)
18. [Appendix E — Upgrade from 2.2.0 to 2.3.0](#appendix-e--upgrade-from-220-to-230)
19. [Appendix F — Upgrade from 2.3.0 to 3.0.0](#appendix-f--upgrade-from-230-to-300)

---

## 1. Quick reference

| Item | Value |
|---|---|
| Web tester (users) | `http://192.168.11.216:4300/` |
| API base URL | `http://192.168.11.216:4300/api` |
| Interactive API docs (Swagger) | `http://192.168.11.216:4300/api/docs` |
| Health check | `http://192.168.11.216:4300/api/health` |
| Backend service name | `ThermoApi` (display name *Thermo Property API*) |
| nginx service name | `nginx` |
| Project folder | `C:\thermo-api` |
| Backend log file | `C:\thermo-api\logs\backend.log` |
| Backend listens on | `127.0.0.1:8000` (internal only) |
| nginx site listens on | port `4300` (all interfaces) |

**The commands you will use most** (run in an *Administrator* Command Prompt; see §8.1 for the one-time `PATH` line that makes `nssm` available):

| Task | Command |
|---|---|
| Is the backend running? | `nssm status ThermoApi` |
| Apply backend code or setting changes | `nssm restart ThermoApi` |
| Apply nginx configuration changes (briefly affects all nginx sites) | `nssm restart nginx` |
| Read the backend log | `type C:\thermo-api\logs\backend.log` |
| Backend health, bypassing nginx | `curl.exe http://127.0.0.1:8000/health` |

For updating the application after a code change, follow [§9](#9-releasing-changes-how-to-deploy-an-update).

---

## 2. Overview

The Thermo Property API calculates thermodynamic properties of multi-component mixtures (heat capacity, density, molecular weight, phase fractions) using the Python [`thermo`](https://github.com/CalebBell/thermo) library. It offers four groups: seven per-property endpoints (**Property APIs**), one complete-stream endpoint based on an equation of state (**EOS Stream API**), one enthalpy and heat-duty endpoint (**Enthalpy API**) and one flow-versus-valve-opening endpoint (**Vent API**), plus a health endpoint (see the API Reference).

The deployment consists of two parts:

| Part | Technology | Purpose |
|---|---|---|
| **Backend** | Python 3.13, FastAPI, uvicorn, `thermo` | Performs the calculations and exposes the JSON API |
| **Frontend** | One static HTML file (`index.html`) | Browser-based tester with four tabs at the top (*Property APIs*, *EOS Stream API*, *Enthalpy API*, *Vent API*) |

Both are served to users by **nginx** on a single address and port, so the browser never makes cross-origin requests and no CORS configuration is required.

---

## 3. Architecture

```
  Browser / Postman / other client  (company LAN or VPN)
                    │
                    │  http://192.168.11.216:4300
                    ▼
  ┌───────────────────────── Windows server 192.168.11.216 ──────────────────────────┐
  │                                                                                  │
  │   nginx 1.28.0  (Windows service "nginx", managed by NSSM)                       │
  │     ├─ :4200  existing site (iEnerZ)                    — not part of this app   │
  │     ├─ :3000  existing site (Nextloop-IEnerZ)           — not part of this app   │
  │     └─ :4300  THIS APPLICATION                                                   │
  │           /       → serves  C:\thermo-api\Frontend\index.html                    │
  │           /api/   → proxies to http://127.0.0.1:8000/   (the "/api" is removed)  │
  │                                       │                                          │
  │   uvicorn + FastAPI, 2 worker processes                                          │
  │   (Windows service "ThermoApi", managed by NSSM, auto-start, restart on crash)   │
  │                                                                                  │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

### Request path (example)

| Step | What happens |
|---|---|
| 1 | Client sends `POST http://192.168.11.216:4300/api/cp_calc` with a JSON body. |
| 2 | nginx matches `location /api/`, removes the `/api` prefix, and forwards `POST /cp_calc` to `127.0.0.1:8000`. |
| 3 | uvicorn hands the request to one of two FastAPI worker processes. |
| 4 | FastAPI validates the body, runs the thermo calculation in a worker thread (30 s limit), and builds the response. |
| 5 | The JSON response travels back through nginx to the client. |

### Design decisions

| Decision | Reason |
|---|---|
| Backend bound to `127.0.0.1` | Port 8000 cannot be reached from the network; only nginx is exposed. |
| Page and API on the same origin (`:4300`) | No cross-origin calls, so no CORS setup. |
| New nginx `server` block on its own port | The two existing sites (4200, 3000) are untouched. |
| Backend run as a Windows service (NSSM) | Starts at boot, restarts after a crash, logs to a rotating file. |
| `--root-path /api` | Makes the Swagger docs and OpenAPI links work behind the `/api` prefix. |
| Warm-up calculation at start-up | `thermo` needs a few seconds to load its data; the first user does not wait. |

---

## 4. Environment inventory

| Component | Detail |
|---|---|
| Operating system | Windows (administrator access required for deployment) |
| Server address | `192.168.11.216` (the host also has an internal adapter `172.22.16.1`, not for users) |
| Python (project) | 3.13.7, 64-bit, in the virtual environment `C:\thermo-api\venv` |
| Other Python installs | 3.14 (system default — **not used** by this project), 3.13t (free-threaded — not used) |
| Key packages | thermo 0.6.1, fastapi 0.142.2, uvicorn 0.54.0, numpy 2.5.3, scipy 1.18.1, pydantic 2.13.5 (full list: `Backend\requirements.txt`) |
| nginx | 1.28.0, folder `C:\Users\Sustainability\AppData\Local\nginx`, config `...\conf\nginx.conf` |
| NSSM | 2.24 (64-bit), `C:\Users\Sustainability\AppData\Local\nssm\nssm.exe` (not on the system `PATH`) |
| Windows Firewall | **Off** on Domain, Private and Public profiles. No firewall rule was needed. |
| Authentication | None (API key feature is available but disabled) |
| CORS | Not applicable (same origin); backend default is permissive (`*`) |

---

## 5. Directory layout

```
C:\thermo-api\
├── Backend\
│   ├── main.py                  Application entry point (middleware, error handlers, /health)
│   ├── app\                     config, schemas, routes, errors, thermodynamic calculations
│   ├── tests\                   Automated tests (132)
│   ├── requirements.txt         Runtime dependencies (pinned)
│   └── requirements-dev.txt     Runtime + test dependencies
├── Frontend\
│   └── index.html               Web tester (served by nginx)
├── deploy\
│   ├── nginx-thermo-block.conf  The nginx server block used for this site
│   └── run_backend.bat          Manual start script (for troubleshooting)
├── docs\                        This documentation
├── venv\                        Python 3.13 virtual environment (not in version control)
└── logs\
    └── backend.log              Backend log (rotates at ~10 MB)
```

---

## 6. Initial deployment procedure

> **Historical record.** This section documents the first deployment (API 2.0.0, 31 tests, nine endpoints) exactly as it was performed. The outputs shown (version `2.0.0`, `31 passed`) are those of that release. For the current release see Appendix C.

This section records exactly what was done on 22 October 2026, in order. All commands are for the **Windows Command Prompt run as Administrator**.

> **Tip:** paste one command at a time and check that the prompt looks like `C:\...>`. If the prompt shows `>>>`, you are inside Python — type `exit()` first.

### Step 1 — Verify the server

```bat
python --version
py -0p
python -c "import struct; print(struct.calcsize('P')*8)"
dir C:\thermo-api
```

| Command | Purpose | Result on this server |
|---|---|---|
| `python --version` | Default Python version | 3.14.0 (not used) |
| `py -0p` | List all installed Pythons and their paths | 3.14, 3.13t and **3.13** (`C:\Program Files\Python313\python.exe`) found |
| `python -c "import struct; ..."` | Python bitness (must be 64) | 64 |
| `dir C:\thermo-api` | Confirm the project folder | `Backend`, `deploy`, `Frontend`, `DEPLOYMENT.md` present |

### Step 2 — Create the project's Python environment

```bat
cd C:\thermo-api
py -3.13 -m venv venv
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -c "import struct; print(struct.calcsize('P')*8)"
```

`py -3.13 -m venv venv` creates a private Python 3.13 installation in `C:\thermo-api\venv`, isolated from other applications and from Python 3.14. Expected output: `Python 3.13.7` and `64`.

### Step 3 — Install the packages

```bat
dir Backend
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r Backend\requirements-dev.txt
.\venv\Scripts\python.exe -c "import thermo, fastapi, uvicorn; print(thermo.__version__, fastapi.__version__, uvicorn.__version__)"
```

Installs the pinned dependencies into the venv (internet access to PyPI required; an offline alternative is in §12). Expected final output: `0.6.1 0.142.2 0.54.0`.

### Step 4 — Run the automated tests

```bat
set | findstr /i "API_KEY CORS_ORIGINS MAX_COMPONENTS CALC_TIMEOUT"
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests
```

The first command confirms that no leftover application settings exist (no output is correct). The test run must end with **`31 passed`**; one harmless warning about `httpx` is expected. Do not continue if any test fails.

### Step 5 — Prepare for the service

```bat
netstat -ano | findstr :8000
reg query HKLM\SYSTEM\CurrentControlSet\Services /s /v ImagePath | findstr /i nssm
set PATH=%PATH%;C:\Users\Sustainability\AppData\Local\nssm
nssm version
sc query ThermoApi
mkdir C:\thermo-api\logs
dir C:\thermo-api
```

| Command | Purpose |
|---|---|
| `netstat -ano \| findstr :8000` | Port 8000 must be free (no output). |
| `reg query ... \| findstr /i nssm` | Locates the existing `nssm.exe` (it is not on the `PATH`). |
| `set PATH=%PATH%;...\nssm` | Makes `nssm` available **in the current window only**. |
| `nssm version` | Confirms NSSM works (2.24, 64-bit). |
| `sc query ThermoApi` | The service name must not exist yet (`...does not exist as an installed service`). |
| `mkdir C:\thermo-api\logs` | Folder for the backend log. |

### Step 6 — Create the backend service

```bat
nssm install ThermoApi "C:\thermo-api\venv\Scripts\python.exe" "-m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 --root-path /api --proxy-headers"
nssm set ThermoApi AppDirectory "C:\thermo-api\Backend"
nssm set ThermoApi DisplayName "Thermo Property API"
nssm set ThermoApi Start SERVICE_AUTO_START
nssm set ThermoApi AppEnvironmentExtra "LOG_LEVEL=INFO" "CALC_TIMEOUT_SECONDS=30"
nssm set ThermoApi AppStdout "C:\thermo-api\logs\backend.log"
nssm set ThermoApi AppStderr "C:\thermo-api\logs\backend.log"
nssm set ThermoApi AppRotateFiles 1
nssm set ThermoApi AppRotateOnline 1
nssm set ThermoApi AppRotateBytes 10485760
nssm set ThermoApi AppExit Default Restart
nssm get ThermoApi Application
nssm get ThermoApi AppParameters
nssm get ThermoApi AppDirectory
```

Meaning of the main parameters:

| Parameter | Meaning |
|---|---|
| `nssm install ThermoApi <python.exe> "<arguments>"` | Registers a Windows service that runs uvicorn using the project's Python. |
| `main:app` | Load the `app` object from `main.py`. |
| `--host 127.0.0.1` | Accept connections from this computer only. |
| `--port 8000` | Internal port. |
| `--workers 2` | Two worker processes → two calculations in parallel. |
| `--root-path /api` | Application is mounted under `/api` behind nginx (fixes Swagger links). |
| `--proxy-headers` | Use the client address forwarded by nginx. |
| `AppDirectory` | Working directory (must contain `main.py`). |
| `Start SERVICE_AUTO_START` | Start automatically at system boot. |
| `AppEnvironmentExtra` | Application settings (see §10). **Replaces the whole list each time it is set.** |
| `AppStdout` / `AppStderr` | Write output and errors to `backend.log`. |
| `AppRotate*` | Start a new log file at about 10 MB. |
| `AppExit Default Restart` | Restart the program if it exits unexpectedly. |

### Step 7 — Start the service and test the backend

```bat
nssm start ThermoApi
nssm status ThermoApi
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
curl.exe -X POST http://127.0.0.1:8000/cp_calc -H "Content-Type: application/json" -d "{\"T\":350,\"P\":101325,\"components\":[\"7732-18-5\",\"110-54-3\"],\"zs\":[0.5,0.5]}"
type C:\thermo-api\logs\backend.log
```

Expected: `SERVICE_RUNNING`; `{"status":"ok","version":"2.0.0"}`; a JSON response with `"status":"success"` and `"Cp_mix":146.029...`; and a log showing `Uvicorn running on http://127.0.0.1:8000` and `Warm-up calculation finished.` twice (one per worker).

> The log lines show `/api/health` although the request was `/health`. This is expected: `--root-path /api` makes the application log its paths with the prefix.

### Step 8 — Locate the existing nginx

```bat
sc query nginx
nssm get nginx Application
nssm get nginx AppDirectory
dir C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
netstat -ano | findstr :4300
netstat -ano | findstr "LISTENING" | findstr ":4200 :3000"
```

nginx was found as service `nginx` in `C:\Users\Sustainability\AppData\Local\nginx`. Port 4300 was free. The last command is the *before* snapshot: ports 4200 and 3000 listening.

### Step 9 — Back up the nginx configuration and add the site

```bat
copy C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf.bak-before-thermo
dir C:\thermo-api\Frontend
notepad C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
findstr /n "listen" C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
```

In Notepad, the following block was inserted inside `http { ... }`, directly after the last existing `server { ... }` block (the one listening on 3000). The same text is kept in `deploy\nginx-thermo-block.conf`.

```nginx
    # ---------- Thermo Property API (page + API) ----------
    server {
        listen       4300;
        server_name  _;

        client_max_body_size  5m;

        # the page
        root   C:/thermo-api/Frontend;
        index  index.html;

        location / {
            try_files $uri $uri/ =404;
        }

        # the API: /api/xxx  ->  backend on this computer, port 8000
        location /api/ {
            proxy_pass         http://127.0.0.1:8000/;
            proxy_http_version 1.1;
            proxy_set_header   Host              $host;
            proxy_set_header   X-Real-IP         $remote_addr;
            proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_read_timeout    60s;
        }

        location = /api {
            return 302 /api/docs;
        }
    }
```

| Directive | Meaning |
|---|---|
| `listen 4300;` | This site answers on port 4300 only. |
| `root C:/thermo-api/Frontend;` | Location of the page. nginx requires **forward slashes**, even on Windows. |
| `location / { try_files ... }` | Serves `index.html` and other static files. |
| `proxy_pass http://127.0.0.1:8000/;` | Forwards `/api/...` to the backend. The **trailing `/`** is essential: it removes the `/api` prefix. |
| `proxy_read_timeout 60s;` | Must be larger than the application's 30 s calculation limit so users get a clean JSON timeout instead of a dropped connection. |
| `client_max_body_size 5m;` | Allows very long component lists (a typical request is a few KB). |

The `findstr` check showed `listen` lines for 4200, 3000 and 4300.

### Step 10 — Test the configuration and apply it

```bat
cd /d C:\Users\Sustainability\AppData\Local\nginx
nginx.exe -t
nssm restart nginx
nssm status nginx
netstat -ano | findstr "LISTENING" | findstr ":4200 :3000 :4300"
curl.exe -I http://localhost:4300/
curl.exe http://localhost:4300/api/health
curl.exe -I http://localhost:4200/
curl.exe -I http://localhost:3000/
```

`nginx.exe -t` must report `syntax is ok` and `test is successful` **before** restarting. `nginx.exe -s reload` was attempted first but failed with *Access is denied* (the nginx service runs under a different Windows account than the administrator's command prompt), so the service is restarted with `nssm restart nginx` instead. A restart interrupts all nginx sites (4200, 3000, 4300) for a few seconds.

Result: all three ports listening; `http://localhost:4300/` → `200 OK`; `/api/health` → `{"status":"ok","version":"2.0.0"}`; both existing sites still `200 OK`.

### Step 11 — Network access

```bat
netsh advfirewall show allprofiles state
ipconfig | findstr /i "IPv4"
```

The Windows Firewall is **Off** on all profiles, so no rule was needed. From another computer on the network, `http://192.168.11.216:4300/` and the API calculations were confirmed working.

---

## 7. Verification checklist

Use this after the first deployment, after a server reboot, and after any significant change.

| # | Check | Command / action | Expected |
|---|---|---|---|
| 1 | Backend service running | `nssm status ThermoApi` | `SERVICE_RUNNING` |
| 2 | Backend answers locally | `curl.exe http://127.0.0.1:8000/health` | `{"status":"ok","version":"3.0.0"}` |
| 3 | nginx running | `nssm status nginx` | `SERVICE_RUNNING` |
| 4 | Site and API through nginx | `curl.exe http://localhost:4300/api/health` | same JSON as above |
| 5 | Existing sites unaffected | `curl.exe -I http://localhost:4200/` and `...:3000/` | `HTTP/1.1 200 OK` |
| 6 | Network access | Browser on another PC: `http://192.168.11.216:4300/` | Page loads, status bar shows *connected · API v3.0.0* |
| 7 | All APIs | Web tester, tab *Property APIs*: each of the 7 entries → *Load example* → *Calculate*. Tabs *EOS Stream API*, *Enthalpy API* and *Vent API*: *Calculate* | Result tables, no error |
| 8 | Postman | `POST http://192.168.11.216:4300/api/cp_calc` with JSON body | `"status":"success"` |
| 9 | Auto-start (recommended) | `sc qc ThermoApi` and `sc qc nginx` | `START_TYPE : 2 AUTO_START` |
| 10 | Reboot test (recommended, off-hours) | Reboot the server, wait 2 minutes, repeat checks 1–6 | All pass without manual action |

---

## 8. Day-to-day operations

### 8.1 Using `nssm`

`nssm.exe` is installed but **not on the system `PATH`**. In every new Command Prompt run this first (it only affects that window):

```bat
set PATH=%PATH%;C:\Users\Sustainability\AppData\Local\nssm
```

### 8.2 Service control

| Task | Command |
|---|---|
| Status | `nssm status ThermoApi` |
| Start | `nssm start ThermoApi` |
| Stop | `nssm stop ThermoApi` |
| Restart | `nssm restart ThermoApi` |
| Show a setting | `nssm get ThermoApi AppParameters` |
| Open the settings GUI | `nssm edit ThermoApi` |

The same commands work for the `nginx` service. Windows' own **Services** application (`services.msc`) also lists both services (*Thermo Property API* and *nginx*).

### 8.3 Logs

| Log | Location | Notes |
|---|---|---|
| Backend | `C:\thermo-api\logs\backend.log` | One line per request: time, method, path, status, duration, `rid=<request id>`. Rotates at ~10 MB. Unexpected errors include a full traceback. |
| nginx access | `C:\Users\Sustainability\AppData\Local\nginx\logs\access.log` | If enabled in `nginx.conf`. |
| nginx errors | `C:\Users\Sustainability\AppData\Local\nginx\logs\error.log` | |

Reading a log: `type C:\thermo-api\logs\backend.log`. For a long file, show only the end with `powershell -Command "Get-Content C:\thermo-api\logs\backend.log -Tail 50"`.

**Tracing a user's problem:** every API response contains a `request_id` (also sent as the `X-Request-ID` header). Ask the user for it, then search the log:

```bat
findstr "a1b2c3d4e5f6" C:\thermo-api\logs\backend.log
```

### 8.4 Monitoring

Point any uptime checker at `http://192.168.11.216:4300/api/health`; it returns `200` with `{"status":"ok", ...}` when the backend is alive. Repeated `504 calculation_timeout` responses in the log indicate unusually heavy inputs.

---

## 9. Releasing changes (how to deploy an update)

**Why a restart is needed:** the backend loads its code when the service starts and does not watch for file changes. After you change backend files you must restart `ThermoApi` before the new behaviour appears. Frontend files are plain files served by nginx and need no restart.

### 9.1 Which procedure applies?

| What changed | Procedure | Restart needed? |
|---|---|---|
| Python code in `Backend\main.py` or `Backend\app\` | §9.3 | `nssm restart ThermoApi` |
| `Backend\requirements.txt` (new or changed package) | §9.3 + §9.4 | `nssm restart ThermoApi` |
| `Frontend\index.html` | §9.5 | None (refresh browsers with `Ctrl+F5`) |
| nginx site configuration | §9.6 | `nssm restart nginx` (interrupts all nginx sites for a few seconds) |
| An application setting (timeout, API key, …) | §9.7 | `nssm restart ThermoApi` |
| Service definition (port, workers, …) | §9.8 | `nssm restart ThermoApi` |

### 9.2 Getting the new files onto the server

Choose one method.

**Method A — Git** (if `C:\thermo-api` is a git clone; check with `git -C C:\thermo-api status`):

```bat
cd C:\thermo-api
git pull
```

**Method B — Copy a prepared folder.** Copy the updated project to a temporary folder on the server, for example `C:\temp\thermo-new`, then use `robocopy` (included with Windows). It copies only new or changed files and **never deletes** anything on the server (no `/MIR`):

```bat
robocopy C:\temp\thermo-new\Backend  C:\thermo-api\Backend  /E /XD __pycache__ .pytest_cache
robocopy C:\temp\thermo-new\Frontend C:\thermo-api\Frontend /E
robocopy C:\temp\thermo-new\docs     C:\thermo-api\docs     /E
```

`robocopy` exit codes 0–7 mean success (1 = files were copied). Never copy `venv` or `logs` from another machine.

### 9.3 Updating the backend code (standard procedure)

**0. Once per Command Prompt window** — make `nssm` available:
```bat
set PATH=%PATH%;C:\Users\Sustainability\AppData\Local\nssm
```

**1. Back up the current backend** (a safe copy for rollback; `/MIR` makes the *backup* folder identical to the current backend):
```bat
robocopy C:\thermo-api\Backend C:\thermo-api-backups\Backend /MIR /XD __pycache__ .pytest_cache
```

**2. Bring in the new files** (Method A or B from §9.2).

**3. Run the automated tests** with the server's Python — they must pass:
```bat
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests
```

**4. Restart the service** so it loads the new code:
```bat
nssm restart ThermoApi
```

**5. Wait for the start-up calculation, then verify:**
```bat
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
type C:\thermo-api\logs\backend.log
```

**Do not restart if the tests fail** — fix the problem or roll back (§9.9). The running service keeps working with the old code until you restart it.

**Making the new version visible:** the version number is defined in `Backend\main.py` (`version="3.0.0"`) and is returned by `/api/health` and shown in the web tester's status bar. Increase it with each release (for example `2.3.1`) so that you can confirm from any browser that the new code is live.

### 9.4 When the dependencies change

If `requirements.txt` changed (new library or new version), install before running the tests:

```bat
cd C:\thermo-api
.\venv\Scripts\python.exe -m pip install -r Backend\requirements-dev.txt
```

Then continue with the tests and the restart in §9.3. On a server without internet, see "Offline installation" in §12.

### 9.5 Updating the frontend

```bat
copy /y C:\temp\thermo-new\Frontend\index.html C:\thermo-api\Frontend\index.html
```

No restart is needed. Users must refresh with **`Ctrl+F5`** so the browser does not show a cached copy. Verify by opening `http://192.168.11.216:4300/`.

### 9.6 Changing the nginx configuration

**1. Back up** (use a new file name each time, for example with the date):
```bat
copy C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf.bak-2026-10-22
```

**2. Edit:**
```bat
notepad C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
```

**3. Test the file.** It must say `test is successful`. If it does not, fix the file — nothing has changed for users yet:
```bat
cd /d C:\Users\Sustainability\AppData\Local\nginx
nginx.exe -t
```

**4. Apply.** All nginx sites restart for a few seconds, so choose a quiet time:
```bat
nssm restart nginx
nssm status nginx
```

**5. Verify all three sites:**
```bat
curl.exe -I http://localhost:4300/
curl.exe -I http://localhost:4200/
curl.exe -I http://localhost:3000/
```

> `nginx.exe -s reload` does **not** work on this server (*Access is denied*), which is why the service is restarted instead.

### 9.7 Changing an application setting

Settings are environment variables stored in the service (see §10). Example — set a 60-second calculation limit and keep the log level:

```bat
nssm set ThermoApi AppEnvironmentExtra "LOG_LEVEL=INFO" "CALC_TIMEOUT_SECONDS=60"
nssm restart ThermoApi
```

`AppEnvironmentExtra` **replaces the entire list**, so always include every variable you want to keep. If you raise `CALC_TIMEOUT_SECONDS`, keep nginx's `proxy_read_timeout` larger than it (§9.6).

### 9.8 Changing the service definition (port, number of workers)

```bat
nssm set ThermoApi AppParameters "-m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4 --root-path /api --proxy-headers"
nssm restart ThermoApi
```

If you change the port, update `proxy_pass` in the nginx block as well (§9.6).

### 9.9 Rolling back a bad backend release

```bat
set PATH=%PATH%;C:\Users\Sustainability\AppData\Local\nssm
nssm stop ThermoApi
robocopy C:\thermo-api-backups\Backend C:\thermo-api\Backend /MIR /XD __pycache__ .pytest_cache
nssm start ThermoApi
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
```

This restores the backup made in step 1 of §9.3. (`/MIR` here makes the live `Backend` folder identical to the backup, which is the point of a rollback.) If git is used, `git checkout <previous-commit>` followed by `nssm restart ThermoApi` achieves the same. To roll back **nginx**, copy the `.bak` file over `nginx.conf`, run `nginx.exe -t`, then `nssm restart nginx`.

### 9.10 Release checklist

1. [ ] Change made and tested on the development PC (`python -m pytest tests`).
2. [ ] Version number increased in `Backend\main.py` (if the backend changed).
3. [ ] Backup of the current server version made (§9.3 step 1).
4. [ ] New files copied/pulled; packages installed if `requirements.txt` changed.
5. [ ] Tests pass on the server.
6. [ ] Service restarted; `/api/health` shows the new version.
7. [ ] Web tester and one Postman call verified; log shows no errors.
8. [ ] Documentation updated (`docs\`) if behaviour or API changed.
9. [ ] Change committed and pushed to the repository.

---

## 10. Configuration reference

All settings are optional. They are environment variables read at start-up and stored in the service through `AppEnvironmentExtra` (§9.7).

| Variable | Default | Current value | Description |
|---|---|---|---|
| `LOG_LEVEL` | `INFO` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `CALC_TIMEOUT_SECONDS` | `30` | `30` | Maximum duration of one calculation; afterwards the API returns HTTP 504. |
| `MAX_COMPONENTS` | `0` | not set | Maximum components per request; `0` means no limit. |
| `API_KEY` | not set | not set | If set, every calculation request must include the header `X-API-Key: <value>`. `/health` and the docs remain open. |
| `CORS_ORIGINS` | `*` | not set | Comma-separated list of allowed browser origins. Not relevant while page and API share one origin. |

**To enable an API key later:** `nssm set ThermoApi AppEnvironmentExtra "LOG_LEVEL=INFO" "CALC_TIMEOUT_SECONDS=30" "API_KEY=<long random value>"`, then `nssm restart ThermoApi`. In Postman add the header `X-API-Key`; in the web tester type the key into the *API key* box.

---

## 11. Security notes

| Topic | Current state | Comment |
|---|---|---|
| Authentication | Disabled | Anyone who can reach `192.168.11.216:4300` can use the API and open `/api/docs`. Access control relies on the company network/VPN. |
| Network exposure | Port 4300 only | The backend (8000) listens on `127.0.0.1` and is not reachable from the network. |
| Windows Firewall | Off (server-wide) | Not changed by this deployment. Turning it on would require rules for 4200, 3000 and 4300. |
| Transport | HTTP (no TLS) | Acceptable inside a trusted LAN; do not expose to the internet without HTTPS. |
| Input handling | Validated | Strict validation, 5 MB request limit, 30 s calculation limit. Errors never expose internal details; only a `request_id`. |
| Secrets | None stored | `.gitignore` keeps `venv`, caches and `.env` files out of version control. |

---

## 12. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `'nssm' is not recognized` | `nssm` is not on the `PATH` | Run the `set PATH=...` line from §8.1 in that window. |
| Prompt shows `>>>` and commands give `SyntaxError` | You are inside the Python interpreter | Type `exit()` and press Enter. |
| Web tester shows *cannot reach backend* | Backend service stopped | `nssm status ThermoApi`; `nssm start ThermoApi`; read `backend.log`. |
| `502 Bad Gateway` | nginx cannot reach port 8000 | Backend not running or wrong port; `curl.exe http://127.0.0.1:8000/health`. |
| `504` / `calculation_timeout` | Calculation exceeded 30 s | Check the input; see §9.7 to raise the limit (and nginx `proxy_read_timeout`). |
| `404` on `/api/...` | nginx `proxy_pass` or `location` slash missing | `proxy_pass http://127.0.0.1:8000/;` and `location /api/ {` must both end with `/`. |
| `/api/docs` page is blank | Service not started with `--root-path /api` | Check `nssm get ThermoApi AppParameters`. |
| `nginx.exe -t` reports an error | Syntax error in `nginx.conf` | Fix, or restore the `.bak` file. The running nginx is unaffected until restarted. |
| `nginx.exe -s reload` → *Access is denied* | Service runs under another account | Use `nssm restart nginx`. |
| nginx will not start after a change | Bad configuration | Restore the backup: `copy /y ...\nginx.conf.bak-... ...\nginx.conf`, then `nssm restart nginx`. |
| New code does not appear | Service not restarted, or browser cache | `nssm restart ThermoApi`; browsers `Ctrl+F5`; compare the version in `/api/health`. |
| Other PCs cannot connect (server works) | Network/VPN routing or a corporate firewall | From the client: `powershell -Command "Test-NetConnection 192.168.11.216 -Port 4300"` must show `TcpTestSucceeded : True`; otherwise involve IT. |
| `422 validation_error` | Invalid input | The response lists the field and the problem. See the API Reference. |
| `422 unknown_component` | Name not known to thermo | Use the CAS number instead. |
| `422 property_unavailable` | Data needed by a model is missing for a component (rare; named in `error.details.components`) | Remove or replace that component. |
| `pip install` fails on numpy/scipy | Wrong Python in the venv | `.\venv\Scripts\python.exe --version` must show 3.13, 64-bit. |

**Offline installation of packages.** On a computer with internet: `python -m pip download -r Backend\requirements-dev.txt -d wheels --only-binary=:all: --platform win_amd64 --python-version 3.13`. Copy the `wheels` folder to the server and run `.\venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r Backend\requirements-dev.txt`.

---

## 13. Known constraints

- **nginx cannot be reloaded without a restart** on this server (§9.6). Changing nginx briefly affects every site it hosts.
- **A timed-out calculation keeps running** in its worker until it finishes; the client simply receives the 504 earlier. If heavy inputs are common, increase `--workers` (§9.8).
- **Three-phase endpoints use an approximation:** the liquid is split into *aqueous* (pure water) and *organic* (everything else) because `thermo.Mixture` performs a vapor–liquid flash only. See the API Reference.
- **First request after a restart** may take a few seconds per worker; the start-up warm-up covers most of this.
- **Reboot test** (§7 check 10) should be performed once at a convenient time to confirm unattended start-up of both services.

---

## Appendix A — Complete command list

All commands used in the initial deployment, in order (Command Prompt, Administrator).

```bat
:: --- Step 1: verify server ---
python --version
py -0p
python -c "import struct; print(struct.calcsize('P')*8)"
dir C:\thermo-api

:: --- Step 2: virtual environment ---
cd C:\thermo-api
py -3.13 -m venv venv
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -c "import struct; print(struct.calcsize('P')*8)"

:: --- Step 3: packages ---
dir Backend
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r Backend\requirements-dev.txt
.\venv\Scripts\python.exe -c "import thermo, fastapi, uvicorn; print(thermo.__version__, fastapi.__version__, uvicorn.__version__)"

:: --- Step 4: tests ---
set | findstr /i "API_KEY CORS_ORIGINS MAX_COMPONENTS CALC_TIMEOUT"
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests

:: --- Step 5: preparation ---
netstat -ano | findstr :8000
reg query HKLM\SYSTEM\CurrentControlSet\Services /s /v ImagePath | findstr /i nssm
set PATH=%PATH%;C:\Users\Sustainability\AppData\Local\nssm
nssm version
sc query ThermoApi
mkdir C:\thermo-api\logs
dir C:\thermo-api

:: --- Step 6: create the backend service ---
nssm install ThermoApi "C:\thermo-api\venv\Scripts\python.exe" "-m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 --root-path /api --proxy-headers"
nssm set ThermoApi AppDirectory "C:\thermo-api\Backend"
nssm set ThermoApi DisplayName "Thermo Property API"
nssm set ThermoApi Start SERVICE_AUTO_START
nssm set ThermoApi AppEnvironmentExtra "LOG_LEVEL=INFO" "CALC_TIMEOUT_SECONDS=30"
nssm set ThermoApi AppStdout "C:\thermo-api\logs\backend.log"
nssm set ThermoApi AppStderr "C:\thermo-api\logs\backend.log"
nssm set ThermoApi AppRotateFiles 1
nssm set ThermoApi AppRotateOnline 1
nssm set ThermoApi AppRotateBytes 10485760
nssm set ThermoApi AppExit Default Restart
nssm get ThermoApi Application
nssm get ThermoApi AppParameters
nssm get ThermoApi AppDirectory

:: --- Step 7: start and test the backend ---
nssm start ThermoApi
nssm status ThermoApi
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
curl.exe -X POST http://127.0.0.1:8000/cp_calc -H "Content-Type: application/json" -d "{\"T\":350,\"P\":101325,\"components\":[\"7732-18-5\",\"110-54-3\"],\"zs\":[0.5,0.5]}"
type C:\thermo-api\logs\backend.log

:: --- Step 8: locate nginx ---
sc query nginx
nssm get nginx Application
nssm get nginx AppDirectory
dir C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
netstat -ano | findstr :4300
netstat -ano | findstr "LISTENING" | findstr ":4200 :3000"

:: --- Step 9: back up nginx.conf and add the server block ---
copy C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf.bak-before-thermo
dir C:\thermo-api\Frontend
notepad C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
findstr /n "listen" C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf

:: --- Step 10: test and apply nginx ---
cd /d C:\Users\Sustainability\AppData\Local\nginx
nginx.exe -t
nssm restart nginx
nssm status nginx
netstat -ano | findstr "LISTENING" | findstr ":4200 :3000 :4300"
curl.exe -I http://localhost:4300/
curl.exe http://localhost:4300/api/health
curl.exe -I http://localhost:4200/
curl.exe -I http://localhost:3000/

:: --- Step 11: network access ---
netsh advfirewall show allprofiles state
ipconfig | findstr /i "IPv4"
```

---

## Appendix B — Uninstall / rollback of the whole deployment

Only if the application must be removed completely.

```bat
set PATH=%PATH%;C:\Users\Sustainability\AppData\Local\nssm

:: 1. remove the backend service
nssm stop ThermoApi
nssm remove ThermoApi confirm

:: 2. restore the original nginx configuration (removes the port 4300 site) and restart nginx
copy /y C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf.bak-before-thermo C:\Users\Sustainability\AppData\Local\nginx\conf\nginx.conf
cd /d C:\Users\Sustainability\AppData\Local\nginx
nginx.exe -t
nssm restart nginx

:: 3. delete the files (optional)
rmdir /s /q C:\thermo-api
```

The existing sites on ports 4200 and 3000 are not modified by the uninstall, because their configuration is identical in the backup file.

---

## Appendix C — Upgrade from 2.0.0 to 2.1.0

Release 2.1.0 adds the **EOS Stream API**, groups the documentation into *Property APIs* and *EOS Stream API*, and removes the two enthalpy endpoints.

### What changes for users

| Area | Change |
| --- | --- |
| New endpoint | `POST /eos_stream_calc` — complete stream result from a Peng-Robinson equation of state with a three-phase flash. |
| Removed endpoints | `/enthalpy_calc` and `/std_enthalpy_calc` now return `404 not_found`. Enthalpy will be provided in a later release. |
| Unchanged endpoints | `/cp_calc`, `/density_calc`, `/mw_calc`, `/vf_calc`, `/triphase_cp_calc`, `/triphase_mw_calc`, `/triphase_vf_calc` and `/health` behave as before (the `version` in `/health` becomes `2.1.0`). |
| Web tester | Two tabs at the top: *Property APIs* (7 entries) and *EOS Stream API* (with an optional comparison against the Property APIs). |
| API documentation | `/api/docs` now shows the two groups, and a description, request example and response example for every endpoint. |
| Server configuration | **No change** to nginx, to the `ThermoApi` service, to environment variables or to Python packages. |

### Files to deploy

| Path (under `C:\thermo-api`) | Status |
| --- | --- |
| `Backend\main.py` | changed |
| `Backend\app\routes.py`, `schemas.py`, `thermo_service.py` | changed |
| `Backend\app\api_docs.py`, `eos_service.py` | **new** |
| `Backend\tests\test_api.py` | changed (enthalpy tests removed) |
| `Backend\tests\test_eos.py`, `test_openapi.py` | **new** |
| `Frontend\index.html` | changed |
| `docs\` | changed |

### Procedure

Follow §9.3 (backend) and §9.5 (frontend) with these specifics.

**1. Back up the current backend** (once per window, first make `nssm` available with the `set PATH` line of §8.1):
```bat
robocopy C:\thermo-api\Backend C:\thermo-api-backups\Backend /MIR /XD __pycache__ .pytest_cache
```

**2. Copy the new files** from your prepared folder (see §9.2), for example:
```bat
robocopy C:\temp\thermo-new\Backend  C:\thermo-api\Backend  /E /XD __pycache__ .pytest_cache
robocopy C:\temp\thermo-new\Frontend C:\thermo-api\Frontend /E
robocopy C:\temp\thermo-new\docs     C:\thermo-api\docs     /E
```
`robocopy` does not delete anything. The removed enthalpy code lives inside the files that are replaced, so no file has to be deleted by hand.

**3. Run the tests.** They must end with **`66 passed`**:
```bat
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests
```

**4. Restart the backend and verify:**
```bat
nssm restart ThermoApi
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
curl.exe -X POST http://127.0.0.1:8000/eos_stream_calc -H "Content-Type: application/json" -d "{\"T\":300,\"P\":101325,\"components\":[\"7732-18-5\",\"110-54-3\"],\"zs\":[0.5,0.5]}"
curl.exe -o NUL -s -w "%{http_code}" -X POST http://127.0.0.1:8000/enthalpy_calc -H "Content-Type: application/json" -d "{}"
```
Expected: `{"status":"ok","version":"2.1.0"}`; a JSON response whose `data.case` is `two-phase liquid-liquid (LL, aqueous+organic)`; and `404` for the removed enthalpy endpoint.

**5. Check the page.** Open `http://192.168.11.216:4300/` and press `Ctrl+F5`. The status bar shows *connected · API v2.1.0*, and the two tabs *Property APIs* and *EOS Stream API* appear. Open `http://192.168.11.216:4300/api/docs` to see the documentation.

### Things to know after the upgrade

- The first EOS request for a new set of components builds the model (about 3 seconds for the 24-component sample stream, much less for small mixtures). The `ThermoApi` service runs two worker processes, and each worker keeps its own models in memory (up to 32 component sets), so the first request that reaches each worker is slow.
- Rolling back: restore the backup with the command in §9.9 and restart the service.

---

## Appendix D — Upgrade from 2.1.0 to 2.2.0

Release 2.2.0 adds the **Enthalpy API** (`POST /eos_enthalpy_calc`) and a third tab in the web tester.

### What changes for users

| Area | Change |
| --- | --- |
| New endpoint | `POST /eos_enthalpy_calc` — enthalpy of a stream at an inlet and an outlet condition, and the heat duty between them (Peng-Robinson equation of state). |
| Unchanged endpoints | All other endpoints behave as before. `/health` reports `2.2.0`. |
| Web tester | A third tab, *Enthalpy API*, with its own inlet/outlet fields, examples and a result view that highlights the heat duty. |
| API documentation | `/api/docs` shows a third group, *Enthalpy API*, with description, request example and response example. |
| Server configuration | **No change** to nginx, the `ThermoApi` service, environment variables or Python packages. |

### Files to deploy

| Path (under `C:\thermo-api`) | Status |
| --- | --- |
| `Backend\main.py` | changed (version) |
| `Backend\app\routes.py`, `schemas.py`, `api_docs.py` | changed |
| `Backend\app\eos_service.py` | changed (shared model cache and parameter helpers; behaviour unchanged) |
| `Backend\app\enthalpy_service.py` | **new** |
| `Backend\tests\test_openapi.py` | changed |
| `Backend\tests\test_enthalpy.py` | **new** |
| `Frontend\index.html` | changed |
| `docs\` | changed |

### Procedure

Follow §9.3 (backend) and §9.5 (frontend), exactly as in Appendix C.

**1. Back up** (after the `set PATH` line of §8.1):
```bat
robocopy C:\thermo-api\Backend C:\thermo-api-backups\Backend /MIR /XD __pycache__ .pytest_cache
```

**2. Copy the new files:**
```bat
robocopy C:\temp\thermo-new\Backend  C:\thermo-api\Backend  /E /XD __pycache__ .pytest_cache
robocopy C:\temp\thermo-new\Frontend C:\thermo-api\Frontend /E
robocopy C:\temp\thermo-new\docs     C:\thermo-api\docs     /E
```

**3. Run the tests.** They must end with **`97 passed`**:
```bat
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests
```

**4. Restart and verify:**
```bat
nssm restart ThermoApi
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
curl.exe -X POST http://127.0.0.1:8000/eos_enthalpy_calc -H "Content-Type: application/json" -d "{\"T_in\":300,\"P_in\":101325,\"T_out\":400,\"P_out\":101325,\"components\":[\"7732-18-5\"],\"zs\":[1]}"
```
Expected: `{"status":"ok","version":"2.2.0"}`, and a response in which `duty.sp_duty` is `2717.545` (kJ/kg) and the outlet `vapor_fraction` is `1.0`.

**5. Check the page.** Open `http://192.168.11.216:4300/`, press `Ctrl+F5`, and confirm that the status bar shows *connected · API v2.2.0* and that the tab *Enthalpy API* works (press *Calculate*; the heat duty is 3.481552 kJ/mol and 120.1752 kJ/kg for the default example).

### Things to know after the upgrade

- The first request for a new set of components builds the equation-of-state model (about 3 seconds for the 10-component sample stream). Models are shared by the EOS Stream API and the Enthalpy API, kept per worker process (64 sets, least recently used dropped).
- Rolling back: restore the backup with the command in §9.9 and restart the service.

---

## Appendix E — Upgrade from 2.2.0 to 2.3.0

Release 2.3.0 adds the **Vent API** (`POST /vent_flow_calc`) and a fourth tab in the web tester.

### What changes for users

| Area | Change |
| --- | --- |
| New endpoint | `POST /vent_flow_calc` — polynomial fit of flow versus valve opening and flow estimates at further openings. It works on the data points in the request; there is no composition, temperature or pressure. |
| Unchanged endpoints | All other endpoints behave as before. `/health` reports `2.3.0`. |
| New error code | `fit_failed` (HTTP 422) for data that cannot be fitted. |
| Web tester | A fourth tab, *Vent API*, with a table of data points, a paste-arrays panel, the degree, the openings to estimate and result tables. |
| API documentation | `/api/docs` shows a fourth group, *Vent API*. |
| Server configuration | **No change** to nginx, the `ThermoApi` service, environment variables or Python packages (the new code uses only `numpy`, which is already installed). |

### Files to deploy

| Path (under `C:\thermo-api`) | Status |
| --- | --- |
| `Backend\main.py` | changed (version) |
| `Backend\app\routes.py`, `schemas.py`, `errors.py`, `api_docs.py` | changed |
| `Backend\app\vent_service.py` | **new** |
| `Backend\tests\test_openapi.py` | changed |
| `Backend\tests\test_vent.py` | **new** |
| `Frontend\index.html` | changed |
| `docs\` | changed |

### Procedure

Follow §9.3 (backend) and §9.5 (frontend), exactly as in Appendices C and D.

**1. Back up** (after the `set PATH` line of §8.1):
```bat
robocopy C:\thermo-api\Backend C:\thermo-api-backups\Backend /MIR /XD __pycache__ .pytest_cache
```

**2. Copy the new files:**
```bat
robocopy C:\temp\thermo-new\Backend  C:\thermo-api\Backend  /E /XD __pycache__ .pytest_cache
robocopy C:\temp\thermo-new\Frontend C:\thermo-api\Frontend /E
robocopy C:\temp\thermo-new\docs     C:\thermo-api\docs     /E
```

**3. Run the tests.** They must end with **`132 passed`**:
```bat
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests
```

**4. Restart and verify:**
```bat
nssm restart ThermoApi
timeout /t 15 /nobreak
curl.exe http://127.0.0.1:8000/health
curl.exe -X POST http://127.0.0.1:8000/vent_flow_calc -H "Content-Type: application/json" -d "{\"opening_values\":[19.7,49.6,89.7],\"flow_values\":[48601,122050,220698],\"degree\":3,\"estimate_at\":[50]}"
```
Expected: `{"status":"ok","version":"2.3.0"}`, and a response with `fit.degree_used` 1, `fit.degree_capped` true and the estimate at 50 % equal to `123073.8`.

**5. Check the page.** Open `http://192.168.11.216:4300/`, press `Ctrl+F5`, confirm that the status bar shows *connected · API v3.0.0*, and press *Calculate* on the *Vent API* tab (equation `Flow(Opening) = +2458.61*Opening +143.197`).

### Things to know after the upgrade

- The Vent API does not use the equation-of-state models, so it needs no warm-up and does not touch the model cache.
- Rolling back: restore the backup with the command in §9.9 and restart the service.

---

## Appendix F — Upgrade from 2.3.0 to 3.0.0

Release 3.0.0 accepts **CAS numbers only** as components (names are rejected with HTTP 422), documents `zs` as **mole fractions** and states that the Vent API returns flows in the unit the user entered. Notify API users before the upgrade, because a client that sends names will receive errors.

**1.** Stop the service so no file is locked: `nssm stop ThermoApi`.

**2.** Replace `Backend\app\*.py`, `Backend\main.py`, `Backend\tests\*` and `Frontend\index.html` with the new versions (the dependency list is unchanged; no `pip install` is needed).

**3.** Start the service: `nssm start ThermoApi`. (nginx needs no change.)

**4.** Check the version: `curl.exe http://127.0.0.1:8000/health` returns `{"status":"ok","version":"3.0.0"}`.

**5.** Check the new rule. A request with `"components":["water","hexane"]` to `/eos_stream_calc` must return HTTP 422 with `error.code` `validation_error`, and the same request with `["7732-18-5","110-54-3"]` must return HTTP 200.

**6.** Open `http://192.168.11.216:4300/`, press `Ctrl+F5` and confirm *connected · API v3.0.0*. Optionally run the tests (`python -m pytest -q tests`, expected `236 passed`).

**Rollback:** restore the previous `Backend` and `Frontend` folders and run `nssm restart ThermoApi`.
