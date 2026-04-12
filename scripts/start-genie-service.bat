@echo off
echo === GenieAPIService inditasa ===
echo EXE:    C:\AI\GenieAPIService_cpp\GenieAPIService.exe
echo Config: models\llama3.1-8b-8380-qnn2.38\config.json
echo Port:   8911
echo.
echo MEGJEGYZES: Qwen3.0-8B-v31 nincs letoltve.
echo Jelenlegi model: llama3.1-8b-8380-qnn2.38 (Snapdragon X Elite ARM64)
echo Qwen3.0-8B-v31 letoltese: https://aihub.qualcomm.com/compute/models
echo.

REM GenieAPIService a sajat konyvtarabol kell futtatni (relativ utak miatt)
cd /d C:\AI\GenieAPIService_cpp

REM Ha a 8910 port foglalt (pl. korabbi lock), hasznald a 8911-et
GenieAPIService.exe -c models\llama3.1-8b-8380-qnn2.38\config.json -l -a -p 8911

pause
