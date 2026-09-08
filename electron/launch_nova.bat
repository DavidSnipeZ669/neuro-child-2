@echo off
echo ============================================
echo  Nova AI — Starting backend + Electron
echo ============================================
echo.

cd /d "B:\Hermes\neuro-child-2"

echo [1/2] Starting Nova backend (takes ~45s to load AI models)...
echo.

REM Kill any previous Nova backend by window title (safe)
taskkill /FI "WINDOWTITLE eq Nova Backend*" /T /F >nul 2>&1

REM Write API key to a file Electron reads directly (more reliable than env vars through start)
echo nova-e2e-test > "%APPDATA%\nova-api-key.txt"

REM Launch backend in its own console window with distinctive title
REM Use >> (append) to avoid "file in use" conflict with previous backend's log
start "Nova Backend" /B python nova_server.py --no-speech --port 8009 --api-key nova-e2e-test --log-level info >> "C:\Users\david\AppData\Local\Temp\nova_backend.log" 2>&1

echo    Backend launched. Waiting for it to become ready...

:wait_loop
timeout /t 5 /nobreak >nul 2>&1

curl -s -H "X-API-Key: nova-e2e-test" http://127.0.0.1:8009/health 2>nul | findstr "ok" >nul
if not errorlevel 1 goto backend_ready

echo    Still waiting...
goto wait_loop

:backend_ready
echo    Backend is ready!
echo.

echo [2/2] Launching Nova Electron app...
echo.

REM Kill any previous Nova Electron by window title (safe)
taskkill /FI "WINDOWTITLE eq Nova Electron*" /F >nul 2>&1
timeout /t 1 /nobreak >nul 2>&1

REM Set environment variables directly in this shell session and launch Electron
REM (no cmd /c needed — start launches electron.exe directly, which inherits env vars)
set NOVA_HOST=127.0.0.1
set NOVA_PORT=8009
set NOVA_API_KEY=nova-e2e-test
start "" electron\node_modules\electron\dist\electron.exe electron --api-key nova-e2e-test

echo    Electron launched (with API key via CLI arg).
echo.
echo ============================================
echo  Nova AI is now running!
echo  - Backend: http://127.0.0.1:8009
echo  - Electron window should appear shortly
echo  - Phone (Tailscale): http://100.82.191.112:8009
echo ============================================
echo.
echo Backend log: C:\Users\david\AppData\Local\Temp\nova_backend.log
echo.
pause
