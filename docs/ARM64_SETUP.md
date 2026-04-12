# ARM64 Setup — Meetily Snapdragon (Qualcomm Snapdragon X Elite)

> Ez az útmutató a **Snapdragon X Elite gépen** elvégzendő lépéseket írja le.
> Fejlesztői gépen (istva) a Device Guard miatt a Rust/Tauri build nem lehetséges.

---

## 1. ELŐFELTÉTELEK

### 1.1 Python ARM64

Töltsd le és telepítsd az ARM64 natív Python-t:

```
https://www.python.org/ftp/python/3.12.8/python-3.12.8-arm64.exe
```

> Ha valamely package nem ARM64-kompatibilis, fallback:
> `python-3.12.8-amd64.exe` (x64, emulálva fut, de minden package megy)

Ellenőrzés:
```powershell
python --version
python -c "import platform; print(platform.machine())"
# → ARM64
```

### 1.2 Node.js ARM64

```
https://nodejs.org/dist/v22.14.0/node-v22.14.0-win-arm64.zip
```

### 1.3 pnpm

```powershell
npm install -g pnpm
```

### 1.4 Rust ARM64 toolchain

```powershell
# Rust telepítése (ha még nincs)
winget install Rustlang.Rustup

# ARM64 target hozzáadása
rustup target add aarch64-pc-windows-msvc
rustup toolchain install stable-aarch64-pc-windows-msvc

# Ellenőrzés
rustup target list --installed
# → aarch64-pc-windows-msvc
```

### 1.5 Visual Studio Build Tools (ARM64)

Visual Studio 2022-ben vagy Build Tools-ban szükséges komponensek:
- MSVC v143 ARM64 build tools
- Windows 11 SDK (10.0.22621.0 vagy újabb)
- CMake tools

```
https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
```

### 1.6 Git

```powershell
winget install Git.Git
```

---

## 2. PROJEKT KLÓNOZÁSA

```powershell
cd C:\Users\<felhasználónév>\Dev

git clone https://github.com/Zackriya-Solutions/meetily meetily-snapdragon
cd meetily-snapdragon
git checkout -b feature/arm64-qualcomm-npu
```

> Vagy másold át a fejlesztői gépről az elkészült projektet (xcopy / robocopy / USB).

---

## 3. BACKEND TELEPÍTÉS

```powershell
cd backend

# Virtuális környezet (ajánlott)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Csomagok telepítése
pip install -r requirements.txt

# NPU extras (opcionális – ha ONNX backend kell)
pip install onnxruntime>=1.20.0 librosa soundfile
```

### .env ellenőrzés

```powershell
notepad app\.env
```

Győződj meg róla, hogy ezek helyesek:
```env
GENIE_BASE_URL=http://127.0.0.1:8912/v1
GENIE_MODEL=llama3.1-8b-8380-qnn2.38
GENIE_TIMEOUT=120
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_TIMEOUT=300
NEXA_BASE_URL=http://127.0.0.1:18181/v1
NEXA_TIMEOUT=300
WHISPER_LANGUAGE=hu
BACKEND_PORT=5167
```

> Cloud API kulcsok (Claude, Groq, OpenAI, OpenRouter) **nem .env-ben** tárolódnak,
> hanem az alkalmazás beállítások oldalán adhatók meg, és a helyi SQLite adatbázisban kerülnek mentésre.

### Backend indítás teszt

```powershell
cd app
python main.py
# → http://localhost:5167/docs
```

---

## 4. WHISPER.CPP ARM64 BUILD

### 4.1 CMake telepítése (ha nincs)

```powershell
winget install Kitware.CMake
```

### 4.2 whisper.cpp klónozása és build

```powershell
cd C:\tools
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp

# ARM64 + DirectML (Adreno GPU fallback)
cmake -B build -DCMAKE_BUILD_TYPE=Release `
  -DGGML_DIRECTML=ON `
  -DCMAKE_SYSTEM_PROCESSOR=ARM64 `
  -A ARM64

cmake --build build --config Release -j
```

> Vagy futtasd a projektben lévő scriptet:
> ```powershell
> .\scripts\build_whisper_arm64.cmd
> ```

### 4.3 Modell letöltése

```powershell
mkdir C:\tools\whisper\models

# Alap modell (~150 MB, gyors)
cd C:\tools\whisper.cpp
.\models\download-ggml-model.cmd base

# Vagy kézzel:
# https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
# → C:\tools\whisper\models\ggml-base.bin
```

### 4.4 whisper-cli.exe elhelyezése

```powershell
mkdir C:\tools\whisper
copy C:\tools\whisper.cpp\build\Release\whisper-cli.exe C:\tools\whisper\
```

### 4.5 Teszt

```powershell
C:\tools\whisper\whisper-cli.exe -m C:\tools\whisper\models\ggml-base.bin -f test.wav --language hu
```

---

## 5. GENIEAPISERVICE TELEPÍTÉS (Qualcomm NPU)

### 5.1 Letöltés

```
https://github.com/quic/ai-engine-direct-helper/releases
```

Töltsd le a legújabb `GenieAPIService_*.zip` fájlt.

### 5.2 Modell letöltése (Qualcomm AI Hub)

```
https://aihub.qualcomm.com/compute/models
```

Ajánlott modellek Snapdragon X Elite-re:
- `llama3.1-8b-8380-qnn2.38` — összefoglalóhoz (ajánlott, Llama 3.1 8B INT4)
- `Llama-3.2-3B-Instruct` — kisebb, gyorsabb
- `DeepSeek-R1-Distill-Qwen-7B` — gondolkodó modell

### 5.3 Indítás

```powershell
GenieAPIService.exe --modelname "llama3.1-8b-8380-qnn2.38" --loadmodel --all-text
```

> Vagy a projekt scriptjével:
> ```powershell
> .\scripts\start-genie-service.bat
> ```

### 5.4 Teszt

```powershell
# NPU státusz lekérdezés
curl http://localhost:5167/npu/status

# Várt válasz (GenieAPIService fut):
# {"genie_api": {"online": true, "models": ["llama3.1-8b-8380-qnn2.38"]}, ...}
```

---

## 6. WHISPER NPU (ONNX + QNN) — OPCIONÁLIS

Ha a valódi NPU Hexagon gyorsítást szeretnéd Whisper-hez is:

### 6.1 QAIRT Runtime letöltés

```
https://github.com/quic/ai-engine-direct-helper/releases → QAIRT_Runtime_*.zip
```

### 6.2 ONNX Whisper modell

```
https://aihub.qualcomm.com/apps/whisper_windows
```

Töltsd le a `whisper-base.onnx` vagy `whisper-large-v3-turbo.onnx` fájlt.

### 6.3 .env módosítás ONNX backendre

```env
WHISPER_NPU_BACKEND=onnx
WHISPER_ONNX_MODEL=C:\tools\whisper\models\whisper-base.onnx
```

### 6.4 onnxruntime QNN provider

```powershell
pip install onnxruntime-qnn
```

---

## 7. FRONTEND TELEPÍTÉS

```powershell
cd frontend
pnpm install
pnpm run dev
# → http://localhost:3118/hu
# → http://localhost:3118/en
```

---

## 8. TAURI ARM64 BUILD

```powershell
cd frontend

# ARM64 target beállítása
$env:CARGO_BUILD_TARGET = "aarch64-pc-windows-msvc"

# Build
pnpm tauri build --target aarch64-pc-windows-msvc
```

A kész telepítő helye:
```
frontend\src-tauri\target\aarch64-pc-windows-msvc\release\bundle\nsis\
```

---

## 9. TELJES APP INDÍTÁS

```powershell
.\scripts\start-meetily-npu.bat
```

Ez egyszerre elindítja:
- FastAPI backend → http://localhost:5167
- GenieAPIService → http://localhost:8910
- Next.js frontend → http://localhost:3118

---

## 10. ELLENŐRZÉSI CHECKLIST

```
[ ] python --version → 3.12.x ARM64
[ ] pip install -r requirements.txt → hiba nélkül
[ ] python main.py → http://localhost:5167/docs elérhető
[ ] whisper-cli.exe → C:\tools\whisper\whisper-cli.exe létezik
[ ] ggml-base.bin → C:\tools\whisper\models\ggml-base.bin létezik
[ ] GET /npu/status → whisper: cpp_exe_found: true, cpp_model_found: true
[ ] GenieAPIService.exe fut → port 8910
[ ] GET /npu/status → genie_api.online: true
[ ] POST /npu/genie/health → online: true
[ ] pnpm run dev → http://localhost:3118/hu HTTP 200
[ ] NPUStatus komponens → "NPU online" zöld jelző
[ ] pnpm tauri build → ARM64 .exe generálódik
```

---

## 11. TELJESÍTMÉNY REFERENCIA (Snapdragon X Elite)

| Feladat | CPU | GPU (Adreno) | NPU (Hexagon) |
|---------|-----|--------------|---------------|
| Whisper base (1 perc audio) | ~8s | ~3s | ~1s |
| LLM token gen (Llama3.1-8B) | ~15 tok/s | ~12 tok/s | ~20-30 tok/s |
| Áramfogyasztás | 20-40W | 15-25W | <5W |

---

## 12. HIBAELHÁRÍTÁS

### GenieAPIService nem indul

```powershell
# Ellenőrizd, hogy a modell le van-e töltve
dir %USERPROFILE%\AppData\Local\qualcomm\models\

# Port foglalt?
netstat -an | findstr 8910
```

### whisper-cli.exe nem fut ARM64-en

```powershell
# Ellenőrizd az architektúrát
dumpbin /headers C:\tools\whisper\whisper-cli.exe | findstr machine
# → AA64 = ARM64 ✓
# → 8664 = x64  ✗ (újra kell buildeni)
```

### Python package nem ARM64-kompatibilis

```powershell
# Fallback: x64 Python (emulált)
python-3.12.8-amd64.exe
# Minden package megy, ~10-15% lassabb
```

### Rust build hiba (Device Guard)

```
error: could not compile ...
```

→ A fejlesztői gépen (istva) ez várható. Csak Snapdragon gépen buildelhető.

### next-intl locale hiba

```
Error: Could not find messages for locale "hu"
```

→ Ellenőrizd: `frontend/messages/hu.json` létezik-e, és a `middleware.ts`-ben `locales: ['hu', 'en']` szerepel-e.

---

*Meetily Snapdragon — ARM64 Setup Guide | 2025*
