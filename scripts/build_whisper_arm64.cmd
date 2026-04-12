@echo off
echo === whisper.cpp ARM64 + DirectML build ===

if not exist whisper.cpp (
    git clone https://github.com/ggerganov/whisper.cpp
)

cd whisper.cpp

cmake -B build -DCMAKE_BUILD_TYPE=Release ^
  -DGGML_DIRECTML=ON ^
  -DCMAKE_SYSTEM_PROCESSOR=ARM64 ^
  -A ARM64

cmake --build build --config Release -j

if exist build\Release\whisper-cli.exe (
    copy build\Release\whisper-cli.exe ..\whisper-cli.exe
    echo OK: whisper-cli.exe keszult
) else (
    echo HIBA: build sikertelen
    exit /b 1
)
