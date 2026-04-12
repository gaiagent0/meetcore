@echo off
echo === Meetily Snapdragon inditas ===

:: GenieAPIService (NPU)
if exist "C:\AI\GenieAPIService_cpp\GenieAPIService.exe" (
    start "GenieAPIService" cmd /k "cd /d C:\AI\GenieAPIService_cpp && GenieAPIService.exe -c models\llama3.1-8b-8380-qnn2.38\config.json -l -a -p 8911"
    echo GenieAPIService inditva: port 8911
) else (
    echo FIGYELEM: GenieAPIService.exe nem talalhato: C:\AI\GenieAPIService_cpp\
)

:: Backend
start "Meetily Backend" cmd /k "cd /d %~dp0..\backend\app && python main.py"

:: Frontend dev szerver
start "Meetily Frontend" cmd /k "cd /d %~dp0..\frontend && pnpm run dev"

echo.
echo Backend:  http://localhost:5167
echo Frontend: http://localhost:3118
echo NPU API:  http://localhost:8911
echo Swagger:  http://localhost:5167/docs
echo.
pause
