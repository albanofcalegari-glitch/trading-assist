@echo off
echo Iniciando Trading Assist...
echo.

:: API Flask (puerto 8000)
start "Trading Assist API" cmd /k ".venv\Scripts\python.exe api.py --port 8000"

:: Esperar 2 segundos
timeout /t 2 /nobreak >nul

:: Frontend React (puerto 3000)
start "Trading Assist UI" cmd /k "cd frontend && npm run dev"

echo.
echo API:      http://localhost:8000
echo Frontend: http://localhost:3001
echo.
