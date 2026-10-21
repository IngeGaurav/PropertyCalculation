@echo off
rem Manual start of the backend (for testing). The Windows service (NSSM) runs the same command.
rem Layout assumed:  <root>\venv   <root>\Backend   <root>\Frontend   <root>\deploy (this file)
cd /d "%~dp0..\Backend"
"%~dp0..\venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 --root-path /api --proxy-headers
