# Deployment Guide – Thermo Property API on a Windows Server with nginx

Target: a company Windows computer on the LAN, **Python 3.13**, **nginx already installed**, no API key and no CORS
restrictions (access is limited by the company network). Follow the steps in order; every command is meant to be copied.

---

## 1. How it will look when deployed

```
 Browser on any LAN computer
        |   http://SERVER-NAME/            -> page (Frontend/index.html)
        |   http://SERVER-NAME/api/...     -> API calls
        v
 +--------------------- Windows server ----------------------------+
 |  nginx (port 80)                                                |
 |    /      serves   C:\thermo-api\Frontend\index.html            |
 |    /api/  proxies  http://127.0.0.1:8000/   (prefix removed)    |
 |                          |                                      |
 |            uvicorn + FastAPI (2 workers, localhost only)        |
 |            runs as Windows service "ThermoApi" (auto-start)     |
 +-----------------------------------------------------------------+
```

Why this design:
- The page and the API come from the **same address**, so the browser never does a cross-origin call – **no CORS setup is needed**.
- Port 8000 is bound to `127.0.0.1`, so the backend cannot be reached directly from the network; only nginx (port 80) is exposed.
- Both nginx and the backend run as **services**, so they start when the computer boots and restart if they crash.

**Security note (your decision, recorded here):** there is no API key and CORS is open, because the server is only reachable inside the
company LAN. That means *anyone on the LAN* can use the API and open `/api/docs`. If this ever changes, §12 shows how to switch an API key on without code changes.

---

## 2. What you need before starting (checklist)

| # | Item | How to check |
|---|---|---|
| 1 | Administrator access on the server | You can open PowerShell with *Run as administrator* |
| 2 | **Python 3.13, 64-bit**, installed *for all users*, "Add python.exe to PATH" ticked | `python --version` -> `Python 3.13.x`, and `python -c "import struct;print(struct.calcsize('P')*8)"` -> `64` |
| 3 | nginx for Windows installed (this guide assumes `C:\nginx`) | `C:\nginx\nginx.exe -v` |
| 4 | **NSSM** (turns a program into a Windows service) from https://nssm.cc/download – unzip `win64\nssm.exe` to `C:\Windows\System32` | `nssm version` |
| 5 | Internet access to PyPI **or** the offline wheel folder from §5.2 | `python -m pip download six -d %TEMP%\x` works |
| 6 | Port **80** free (nothing else, e.g. IIS, uses it) | `netstat -ano | findstr ":80 "` shows nothing listening. If it is taken, use another port (§13) |
| 7 | The project folder from this PC (`Backend`, `Frontend`, `deploy`, `DEPLOYMENT.md`) | See §3 |

All pinned packages were checked to have ready-made **binary wheels for Python 3.13 / Windows 64-bit**, so no C compiler is needed.
(Verified with `pip install --dry-run --python-version 3.13 --platform win_amd64 --only-binary=:all:`.)

---

## 3. Put the project on the server

Target folder: **`C:\thermo-api`** (avoid spaces in the path; if you choose another folder, change it in
the nginx file and the NSSM commands as well).

Final layout:
```
C:\thermo-api\
  Backend\        main.py, app\, tests\, requirements.txt
  Frontend\       index.html
  deploy\         nginx.conf, run_backend.bat
  venv\           (created in step 5)
  logs\           (created in step 7)
```

**Option A – git** (if git is installed on the server):
```powershell
git clone https://github.com/IngeGaurav/PropertyCalculation.git C:\thermo-api
```
**Option B – copy:** zip the project folder on your PC (without `__pycache__`, `.pytest_cache`, `venv`), copy it to the server and unzip it into `C:\thermo-api`.

Check: `dir C:\thermo-api` shows `Backend`, `Frontend`, `deploy`.

---

## 4. Allow the services to read the folder
If you will run the service under the default account (Local System) you can skip this. If you create a dedicated service account, give it *Read & execute*
on `C:\thermo-api` and *Modify* on `C:\thermo-api\logs`.

---

## 5. Create the Python environment

Open **PowerShell as Administrator**:

### 5.1 Online server
```powershell
cd C:\thermo-api
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r Backend\requirements-dev.txt
```
(`requirements-dev.txt` = runtime packages + pytest/httpx so you can run the tests in step 6.)

### 5.2 Server without internet
On **any PC with internet** (any Python 3.x is fine for downloading):
```powershell
cd <project>\Backend
python -m pip download -r requirements-dev.txt -d wheels --only-binary=:all: --platform win_amd64 --python-version 3.13
```
Copy the `wheels` folder to the server (e.g. `C:\thermo-api\wheels`), then:
```powershell
cd C:\thermo-api
py -3.13 -m venv venv
.\venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r Backend\requirements-dev.txt
```

Check: `.\venv\Scripts\python.exe -c "import thermo, fastapi; print(thermo.__version__, fastapi.__version__)"` -> `0.6.1 0.142.2`.

---

## 6. Prove the environment works – run the tests
```powershell
cd C:\thermo-api\Backend
..\venv\Scripts\python.exe -m pytest -q tests
```
Expected: **`31 passed`**. If anything fails here, do **not** continue – it means a package version differs from the tested one (re-check step 5).
(The tests need `API_KEY` / `CORS_ORIGINS` to be unset in this PowerShell window; they are by default.)

Then start the backend by hand once, to see it working before making it a service:
```powershell
cd C:\thermo-api
.\deploy\run_backend.bat
```
Leave that window open. In a **second** PowerShell window:
```powershell
curl.exe http://127.0.0.1:8000/health
```
Expected: `{"status":"ok","version":"2.0.0"}`. Stop the first window with `Ctrl+C`.
(The log shows `Warm-up calculation finished.` for each worker – the first calculation is done at startup, so users don't wait for it.)

---

## 7. Install the backend as a Windows service (auto-start)

```powershell
New-Item -ItemType Directory -Force C:\thermo-api\logs | Out-Null

nssm install ThermoApi "C:\thermo-api\venv\Scripts\python.exe" "-m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 --root-path /api --proxy-headers"
nssm set ThermoApi AppDirectory   "C:\thermo-api\Backend"
nssm set ThermoApi DisplayName    "Thermo Property API"
nssm set ThermoApi Start          SERVICE_AUTO_START
nssm set ThermoApi AppEnvironmentExtra "LOG_LEVEL=INFO" "CALC_TIMEOUT_SECONDS=30"
nssm set ThermoApi AppStdout      "C:\thermo-api\logs\backend.log"
nssm set ThermoApi AppStderr      "C:\thermo-api\logs\backend.log"
nssm set ThermoApi AppRotateFiles 1
nssm set ThermoApi AppRotateOnline 1
nssm set ThermoApi AppRotateBytes 10485760
nssm set ThermoApi AppExit Default Restart
nssm start ThermoApi
```
What the flags mean:

| Flag | Why |
|---|---|
| `--host 127.0.0.1` | Only nginx on this computer can reach the backend |
| `--workers 2` | Two processes -> two calculations in parallel. Use the number of CPU cores (1-4) |
| `--root-path /api` | The API lives under `/api` behind nginx; this makes `/api/docs` work |
| `--proxy-headers` | Uses the client address nginx forwards in the logs |

Check:
```powershell
nssm status ThermoApi                       # SERVICE_RUNNING
curl.exe http://127.0.0.1:8000/health       # {"status":"ok",...}
Get-Content C:\thermo-api\logs\backend.log -Tail 20
```

---

## 8. Configure nginx

1. Back up the original: `copy C:\nginx\conf\nginx.conf C:\nginx\conf\nginx.conf.bak`
2. Copy `C:\thermo-api\deploy\nginx.conf` over `C:\nginx\conf\nginx.conf`.
   (If nginx on this computer already serves other sites, do not overwrite – copy only the `server { ... }` block into your existing `http { }`.)
3. Open it and check the `root` line points at your folder: `root C:/thermo-api/Frontend;` (forward slashes!).
4. Test the syntax:
```powershell
cd C:\nginx
.\nginx.exe -t
```
Expected: `syntax is ok` and `test is successful`.

5. Run nginx as a service (nginx for Windows has no service of its own):
```powershell
nssm install nginx "C:\nginx\nginx.exe"
nssm set nginx AppDirectory "C:\nginx"
nssm set nginx Start SERVICE_AUTO_START
nssm set nginx AppStdout "C:\thermo-api\logs\nginx-service.log"
nssm set nginx AppStderr "C:\thermo-api\logs\nginx-service.log"
nssm start nginx
```
(If nginx is already running from a previous manual start, stop it first: `C:\nginx\nginx.exe -s stop`.)

After any later change to `nginx.conf`: `cd C:\nginx` then `.\nginx.exe -t` then `.\nginx.exe -s reload`.

Check on the server itself:
```powershell
curl.exe -I http://localhost/                    # HTTP/1.1 200 OK  (the page)
curl.exe http://localhost/api/health             # {"status":"ok","version":"2.0.0"}
```

---

## 9. Open the firewall for the LAN only

Only port 80 is opened, and only to the local network. **Do not** open 8000.
```powershell
New-NetFirewallRule -DisplayName "Thermo API (HTTP 80)" -Direction Inbound -Protocol TCP -LocalPort 80 `
  -Action Allow -Profile Domain,Private -RemoteAddress LocalSubnet
```
- `LocalSubnet` = the server's own subnet. If users are on other subnets/VLANs, replace it with your company ranges, e.g. `-RemoteAddress 10.0.0.0/8,192.168.0.0/16`.
- If your LAN is classified as "Public" in Windows, run `Get-NetConnectionProfile` and either change the category to Private or add `Public` to `-Profile`.

---

## 10. Test from another computer on the LAN

Find the server name/IP: on the server run `hostname` and `ipconfig` (IPv4 address).

On another PC, open the browser:

| URL | Expected |
|---|---|
| `http://SERVER-NAME/` | The **Thermo API Tester** page. Top-right shows **"connected · API v2.0.0"** |
| `http://SERVER-NAME/api/docs` | Interactive API documentation (Swagger) |
| `http://SERVER-NAME/api/health` | `{"status":"ok","version":"2.0.0"}` |

(`SERVER-NAME` can also be the IP address.) Then in the tester: open each of the 9 tabs, press **Load example** and **Calculate**.
The *Backend URL* box is pre-filled with `http://SERVER-NAME/api` – leave it.

To call the API from other programs (Python, Excel, etc.):
```powershell
curl.exe -X POST http://SERVER-NAME/api/cp_calc -H "Content-Type: application/json" `
  -d '{\"T\":350,\"P\":101325,\"components\":[\"water\",\"hexane\"],\"zs\":[0.5,0.5]}'
```
(Quote escaping differs between PowerShell and cmd; in Python: `requests.post("http://SERVER-NAME/api/cp_calc", json={...})`.)

---

## 11. Operating it

**Logs**
- Backend: `C:\thermo-api\logs\backend.log` (rotates at 10 MB). One line per request: method, path, status, milliseconds, `rid=<request id>`.
  An error response shown to a user contains the same `request_id` – search the log for it to find the details/traceback.
- nginx: `C:\nginx\logs\access.log` and `error.log`.

**Start / stop / restart**
```powershell
nssm restart ThermoApi
nssm restart nginx
nssm status ThermoApi
```

**Deploy an update** (new code from your PC):
```powershell
cd C:\thermo-api
git pull                                     # or copy the new files over the old ones
.\venv\Scripts\python.exe -m pip install -r Backend\requirements-dev.txt     # only needed if requirements changed
cd Backend ; ..\venv\Scripts\python.exe -m pytest -q tests ; cd ..           # must still pass
nssm restart ThermoApi
```
Frontend-only changes need no restart (just refresh the browser; press `Ctrl+F5`). Roll back with `git checkout <previous-commit>` and `nssm restart ThermoApi`.

**After the server reboots:** both services start automatically. Verify with §10.

### Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Page shows "cannot reach backend" | `nssm status ThermoApi`; `curl.exe http://127.0.0.1:8000/health`; read `backend.log`. If the page is opened as a file (not through nginx) the box must contain the real URL. |
| `502 Bad Gateway` from nginx | Backend not running or not on 8000. Start the service, check `backend.log`. |
| `504 Gateway Timeout` / `calculation_timeout` | A calculation took > 30 s. Check the input; raise `CALC_TIMEOUT_SECONDS` (and nginx `proxy_read_timeout`, which must stay larger). |
| `404` on `/api/...` | In `nginx.conf` the `proxy_pass http://127.0.0.1:8000/;` **must end with `/`** and `location /api/` must have the trailing slash. |
| Page loads but `/api/docs` is blank | Service not started with `--root-path /api` (re-run the `nssm install` line). |
| nginx will not start: `bind() to 0.0.0.0:80 failed` | Another program uses port 80 (IIS, Skype, ...). Stop it or change `listen 80;` to another port (§13) and open that port in the firewall. |
| nginx `CreateFile() ... failed` for the page | Wrong `root` path in `nginx.conf`, or backslashes used. Use `C:/thermo-api/Frontend`. |
| Other PCs cannot connect, server itself works | Firewall rule / network profile (§9), or a company firewall between subnets. |
| `422 validation_error` | The input is wrong; the message says which field (e.g. counts of components and mole fractions differ). |
| `422 unknown_component` | thermo does not know that name; use the CAS number. |
| `422 property_unavailable` on standard enthalpy | thermo has no formation enthalpy for a component. Tick *Treat ... as 0* in the page, or send `"allow_missing_hf": true`. |
| `pip install` fails to build scipy/numpy | The venv is not Python 3.13 64-bit. Check `.\venv\Scripts\python.exe --version`. |

---

## 12. Configuration reference (all optional)

The service runs fine with **no** settings. To change one, add it to the service and restart:
```powershell
nssm set ThermoApi AppEnvironmentExtra "LOG_LEVEL=INFO" "CALC_TIMEOUT_SECONDS=30" "API_KEY=your-secret"
nssm restart ThermoApi
```
(`AppEnvironmentExtra` replaces the whole list each time – always include every variable you want.)

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | *(unset = open)* | If set, every calculation request must send header `X-API-Key: <value>`. Without it, anyone who can reach the server may call the API. To use it with the tester page, type the key in the page's "API key" box. |
| `CORS_ORIGINS` | `*` | Allowed browser origins. Irrelevant for the nginx setup (same origin); only matters if you host the page on a different address than the API. |
| `CALC_TIMEOUT_SECONDS` | `30` | Per-calculation time limit (then HTTP 504). |
| `MAX_COMPONENTS` | `0` | `0` = no limit on the number of components. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## 13. Using a different port
If port 80 is not available, change `listen 80;` in `nginx.conf` (e.g. `listen 8080;`), reload nginx, open that port in the firewall rule,
and use `http://SERVER-NAME:8080/` – nothing else changes.

---

## 14. What was checked in the code for this deployment

| Area | Finding / action |
|---|---|
| Python 3.13 | All pinned packages have Windows x64 binary wheels for 3.13 (checked with a pip dry-run). Tests pass; they were run on 3.14 here – step 6 re-runs them on the server's real 3.13. |
| Frontend -> API address | Previously hard-coded to `http://localhost:8000`. Now, when served over http(s), it **defaults to the same server under `/api`** (works with any host name/IP, no CORS). Still editable in the page. |
| Reverse-proxy prefix | Backend now supports `--root-path /api`; verified that the OpenAPI/Swagger URLs become `/api/...` behind nginx. |
| Startup | Added a **warm-up calculation** at startup (thermo needs ~2-4 s to load its data on the first call); the first user no longer waits. A warm-up failure does not stop the service. |
| Multiple workers | Verified on Windows: `--workers 2` starts and answers requests. |
| Open access | API key is **optional and off by default**; CORS defaults to `*`. Both unchanged, as you requested. |
| Request size/limits | No component limit; nginx accepts bodies up to 5 MB (a 48-component request is ~2 KB). |
| Timeouts | App limit 30 s < nginx `proxy_read_timeout` 60 s, so users get a clean JSON `504` instead of a dropped connection. |
| Logging | One line per request with a request id; rotated by NSSM. Unexpected errors log a traceback but show users only the request id. |
| Auto-start | Both backend and nginx are Windows services (start at boot, restart on failure). |
| Files not in the repo | `.gitignore` keeps `venv`, caches and `.env` files out of git. |

Known limitations (unchanged): a calculation that times out keeps running in its worker until finished; the three `triphase_*` endpoints use a water/organic approximation
(see `Backend/DOCUMENTATION.md`).

---

## 15. Go-live checklist

1. [ ] `python --version` on the server is 3.13 (64-bit); `nssm version` and `nginx -v` work.
2. [ ] Project in `C:\thermo-api`; `venv` created with Python 3.13; packages installed.
3. [ ] `pytest` -> `31 passed` on the server.
4. [ ] `nssm status ThermoApi` -> `SERVICE_RUNNING`; `curl http://127.0.0.1:8000/health` OK.
5. [ ] `nginx -t` OK; `nssm status nginx` -> `SERVICE_RUNNING`; `curl http://localhost/api/health` OK.
6. [ ] Firewall rule for port 80 (LAN only); port 8000 **not** opened.
7. [ ] From another LAN computer: `http://SERVER-NAME/` shows "connected"; all 9 tabs return results.
8. [ ] Reboot the server once; confirm the page works again without touching anything.
9. [ ] Someone else knows where `C:\thermo-api\logs` and this guide are.
