# Deployment guide – Thermo Property API

How to take the code in `Backend/` from your laptop to a server where the API is reachable by others,
and how to publish the `Frontend/` tester. Written for a Linux server (the usual choice); a Windows
server variant is in §9. No deployment files are included in the project – everything you need is shown
inline here, so you copy only what you decide to use.

```
FastApi/
  Backend/    FastAPI service  (main.py, app/, tests/, DOCUMENTATION.md)
  Frontend/   index.html – the 9-endpoint tester (static, no build step)
  DEPLOYMENT.md  (this file)
```

---

## 1. What "building" means for this project

Python has no compile step. "Building" = **reproducing the same environment on the server**:

1. the same Python version family,
2. the same pinned package versions,
3. the code,
4. a long-running process that serves it, started automatically and restarted on failure,
5. (recommended) a reverse proxy in front of it that handles HTTPS.

The frontend is one static HTML file: "building" it means copying it to a web server and pointing its
"Backend URL" box at the API.

---

## 2. Before you touch the server

**2.1 Pick the Python version.** The code was developed and tested on Python 3.14. `thermo` depends on
numpy/scipy, whose binary wheels appear a little later for brand-new Python versions. For the server use
**Python 3.11 or 3.12** (wheels exist for everything), then **run the tests on the server** (§5.4) – that is
your proof the environment is good.

**2.2 Pin the dependencies.** Create `Backend/requirements.txt` with the versions tested here:

```
fastapi==0.142.2
uvicorn[standard]==0.54.0
thermo==0.6.1
chemicals==1.5.2
fluids==1.3.1
numpy==2.5.3
scipy==1.18.1
pydantic==2.13.5
```
(`thermo` brings numpy/scipy/chemicals/fluids itself; listing them keeps the install reproducible.
If numpy 2.5.3 or scipy 1.18.1 have no wheel for your server's Python, let pip choose by deleting those two lines, then run the tests.)
For running tests only (not needed in production): `pytest`, `httpx`.

> thermo is the version-sensitive part. The code relies on 0.6.x behaviour (`Chemical.Hf` being mass-based,
> `Hfm`, `Cpl`/`Cpg` in J/kg/K, `Mixture.VF/xs/ys`). Keep `thermo==0.6.1` unless you re-run the tests after upgrading.

**2.3 Decide the security posture** (see §7): will the API be public or only on your network, do you want an
API key, which website origin(s) may call it from a browser.

**2.4 Decide the address**: `https://api.yourcompany.com` (a DNS record pointing to the server) is better than a raw IP,
because HTTPS certificates need a name.

---

## 3. Configuration (environment variables)

| Variable | Recommended production value |
|---|---|
| `API_KEY` | A long random string, e.g. output of `python -c "import secrets;print(secrets.token_urlsafe(32))"`. Clients send it as header `X-API-Key`. |
| `CORS_ORIGINS` | The exact origin(s) of your frontend, e.g. `https://thermo.yourcompany.com`. Not `*`. |
| `CALC_TIMEOUT_SECONDS` | `30` (raise only if you really have slow mixtures) |
| `MAX_COMPONENTS` | `0` (unlimited; set e.g. `200` if you want a safety cap) |
| `LOG_LEVEL` | `INFO` |

Keep them in a file readable only by the service user (e.g. `/etc/thermo-api.env`, `chmod 600`) – never in git.

---

## 4. Server preparation (Ubuntu 22.04/24.04 example)

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv nginx ufw      # python3.11 works too
sudo adduser --system --group --home /opt/thermo-api thermo   # unprivileged service user
sudo mkdir -p /opt/thermo-api && sudo chown thermo:thermo /opt/thermo-api
```

Firewall – only SSH and web ports are open; uvicorn itself stays private on localhost:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'      # 80 and 443
sudo ufw enable
```

---

## 5. Install the backend

### 5.1 Copy the code
From your PC (PowerShell), copy the **contents of `Backend/`** (not the tests' caches):
```powershell
scp -r Backend\main.py Backend\app Backend\tests Backend\requirements.txt user@SERVER:/tmp/thermo-api/
```
(or `git clone` your repository on the server – preferable, because updates become `git pull`.)
```bash
sudo rsync -a /tmp/thermo-api/ /opt/thermo-api/ && sudo chown -R thermo:thermo /opt/thermo-api
```

### 5.2 Create the virtual environment and install
```bash
sudo -u thermo python3.12 -m venv /opt/thermo-api/venv
sudo -u thermo /opt/thermo-api/venv/bin/pip install --upgrade pip
sudo -u thermo /opt/thermo-api/venv/bin/pip install -r /opt/thermo-api/requirements.txt
```

### 5.3 Create the environment file
```bash
sudo tee /etc/thermo-api.env >/dev/null <<'EOF'
API_KEY=put-the-generated-key-here
CORS_ORIGINS=https://thermo.yourcompany.com
CALC_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
EOF
sudo chmod 600 /etc/thermo-api.env
```

### 5.4 Verify the environment with the test-suite
```bash
sudo -u thermo /opt/thermo-api/venv/bin/pip install pytest httpx
cd /opt/thermo-api && sudo -u thermo /opt/thermo-api/venv/bin/python -m pytest -q tests
```
Expect `31 passed`. If a test fails here but passed on your PC, the cause is almost always a different
thermo/numpy version – fix the pins before going on.
The tests read settings from the environment, so run them in a shell where `API_KEY` / `CORS_ORIGINS` are **not** exported
(the systemd env file is not loaded by your shell, so the command above is fine). If you exported them, prefix with `env -u API_KEY`.

### 5.5 Run it as a service (systemd)
Create `/etc/systemd/system/thermo-api.service`:
```ini
[Unit]
Description=Thermo Property API
After=network.target

[Service]
User=thermo
Group=thermo
WorkingDirectory=/opt/thermo-api
EnvironmentFile=/etc/thermo-api.env
ExecStart=/opt/thermo-api/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now thermo-api
sudo systemctl status thermo-api
curl http://127.0.0.1:8000/health          # {"status":"ok","version":"2.0.0"}
journalctl -u thermo-api -f                # live logs (one line per request, with request id)
```
Notes on `--workers 2`: thermo calculations are CPU-bound Python. Each worker is a separate process, so use roughly
the number of CPU cores (1–4 is typical). More workers = more parallel calculations and better isolation from
a slow one. The first request per worker is slow (~2 s) because thermo loads its databases; this is normal.

---

## 6. Put HTTPS in front (nginx + Let's Encrypt)

`/etc/nginx/sites-available/thermo-api`:
```nginx
server {
    server_name api.yourcompany.com;

    client_max_body_size 64k;           # requests are tiny; reject anything large

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;         # must be larger than CALC_TIMEOUT_SECONDS
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/thermo-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourcompany.com      # issues the certificate and enables auto-renewal
```
Optional rate limiting (stops one client from saturating the CPU): in the `http {}` block of `nginx.conf` add
`limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;` and inside `location /` add `limit_req zone=api burst=20 nodelay;`.

**Smoke-test from anywhere:**
```bash
curl https://api.yourcompany.com/health
curl -X POST https://api.yourcompany.com/cp_calc \
  -H "Content-Type: application/json" -H "X-API-Key: YOUR_KEY" \
  -d '{"T":350,"P":101325,"components":["water","hexane"],"zs":[0.5,0.5]}'
```
Interactive docs: `https://api.yourcompany.com/docs`.
Note: with `API_KEY` set, `/docs` and `/health` still load without a key, but "Try it out" in `/docs` requires you to send the header (the
`/docs` page does not have a key field; use the Frontend or curl). If you do not want `/docs` public, block it in nginx:
`location /docs { return 404; }` and `location /openapi.json { return 404; }`.

---

## 7. Security checklist

- [ ] `API_KEY` set to a long random value, shared only with the people/systems that need it.
- [ ] `CORS_ORIGINS` is the exact frontend origin, not `*`.
- [ ] HTTPS only (certbot redirects HTTP to HTTPS). Without HTTPS the API key travels in clear text.
- [ ] uvicorn bound to `127.0.0.1`; only nginx is reachable from outside; firewall allows only 22/80/443.
- [ ] Service runs as the unprivileged `thermo` user; env file is `chmod 600`.
- [ ] The API key typed into the Frontend is stored in that browser's localStorage. Use the tester only on trusted machines. A public website
      should **not** embed the key in page JavaScript – call the API from your own server instead.
- [ ] Rate limiting enabled in nginx if the API is exposed to the internet.
- [ ] OS security updates enabled (`unattended-upgrades`).

---

## 8. Publishing the frontend

`Frontend/index.html` is a static file; it runs entirely in the user's browser and talks to the API with `fetch`.

**Option A – just open the file.** Double-click it, type the backend URL in the top box, press *Check connection*. Works because the
API allows cross-origin calls (with the default `CORS_ORIGINS=*`; if you restrict CORS, a page opened from disk has origin `null` and will be blocked – use option B).

**Option B – serve it from nginx (recommended for a team):**
```bash
sudo mkdir -p /var/www/thermo && sudo cp Frontend/index.html /var/www/thermo/
```
```nginx
server {
    server_name thermo.yourcompany.com;
    root /var/www/thermo;
    index index.html;
}
```
then `sudo certbot --nginx -d thermo.yourcompany.com` and set `CORS_ORIGINS=https://thermo.yourcompany.com` on the API
(`sudo systemctl restart thermo-api` after editing the env file).
To pre-fill the backend URL for your users, change the default in `index.html`
(`value="http://localhost:8000"` in the `baseUrl` input).

**Option C – same domain, no CORS at all:** serve the HTML from the same nginx `server` as the API, e.g. API under `/api/`
(strip the prefix with `proxy_pass http://127.0.0.1:8000/;`) and put `https://yourdomain/api` in the Backend URL box.

---

## 9. Windows Server variant

1. Install Python 3.11/3.12 (tick *Add to PATH*).
2. `python -m venv C:\thermo-api\venv` → `C:\thermo-api\venv\Scripts\pip install -r requirements.txt` → run the tests (§5.4, use `python -m pytest`).
3. Set machine-level environment variables (`API_KEY`, `CORS_ORIGINS`, …) in *System Properties → Environment Variables*, or with `setx /M`.
4. Run: `C:\thermo-api\venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000` from `C:\thermo-api`.
   (Windows cannot use `--workers` with gunicorn, but uvicorn's own `--workers N` works.)
5. Make it a service that starts on boot and restarts on failure with **NSSM** (`nssm install ThermoApi`, set the uvicorn command line and
   working directory) or Task Scheduler ("run at startup", "restart on failure").
6. Open the port: `New-NetFirewallRule -DisplayName ThermoApi -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`.
   Only do this on a trusted network, or put IIS (with the URL Rewrite + ARR modules) / nginx for Windows in front for HTTPS.

---

## 10. Operating it

**Deploy an update**
```bash
cd /opt/thermo-api && sudo -u thermo git pull            # or rsync the new files
sudo -u thermo venv/bin/pip install -r requirements.txt  # only matters if requirements changed
sudo -u thermo venv/bin/python -m pytest -q tests        # must still pass
sudo systemctl restart thermo-api
curl https://api.yourcompany.com/health
```
Keep the previous release (e.g. `git tag`) so you can roll back with `git checkout <tag>` + restart.

**Find a problem for a user.** Ask for the `request_id` in the error JSON (or the `X-Request-ID` header) and run
`journalctl -u thermo-api | grep <request_id>`. 500 errors log the full traceback.

**Monitoring.** Point an uptime checker (UptimeRobot, Zabbix, a cron + curl) at `GET /health`. Watch for repeated `504 calculation_timeout`
(a pathological mixture – lower `MAX_COMPONENTS` or `CALC_TIMEOUT_SECONDS`) and `5xx` rates in the logs.

**Capacity.** One calculation typically takes 10–50 ms once warm. A timed-out calculation keeps its thread busy until it finishes
(see `Backend/DOCUMENTATION.md` §7), so a client repeatedly sending hard mixtures can tie up a worker – rate limiting (§6) is your protection.

**Logs.** journald rotates automatically. For a file-based setup, add `logrotate`.

---

## 11. Optional: containers
If your organisation prefers containers, the equivalent is a `python:3.12-slim` image that copies `Backend/`, runs
`pip install -r requirements.txt`, and starts `uvicorn main:app --host 0.0.0.0 --port 8000`, with the same environment variables passed at run time and the
nginx/HTTPS layer unchanged. This guide does not require it.

---

## 12. Go-live checklist

1. [ ] Tests pass on the server (`31 passed`).
2. [ ] `systemctl status thermo-api` is `active (running)`; it survives `sudo reboot`.
3. [ ] `https://api…/health` returns `ok` from outside the server.
4. [ ] A calculation with the API key works; the same call **without** the key returns `401`.
5. [ ] Frontend loads, *Check connection* shows "connected", each of the 9 tabs returns a result with *Load example*.
6. [ ] A bad input (e.g. mismatched component/fraction counts) shows a readable error in the Frontend.
7. [ ] CORS restricted, firewall on, key not committed to git.
8. [ ] Someone other than you knows where the env file, logs and this guide are.
