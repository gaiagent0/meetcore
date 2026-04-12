# MeetCore

> **Lokális meeting hangrögzítő és összefoglaló alkalmazás**  
> Qualcomm Snapdragon X Elite ARM64 Windows – NPU-gyorsított Parakeet ASR + AI összefoglalás

---

## Mi ez?

MeetCore egy olyan desktop alkalmazás, amely **100%-ban lokálisan** működő meeting-felvételt, hangfájl-feltöltést, beszéd-átírást (ASR) és AI-alapú összefoglalást kínál. A Qualcomm **Hexagon NPU**-t használja a nagy nyelvmodellek futtatásához, így minimális energiafogyasztás mellett (<5W) dolgozik.

### Főbb funkciók

- **Hangrögzítés** közvetlenül az alkalmazásból
- **Hangfájl feltöltés** (WAV, MP3, M4A, stb.)
- **Parakeet TDT ASR** NPU-n futtatva, magyar nyelvű átíráshoz
- **AI összefoglalás** 6 különböző szolgáltatóval:
  - 🖥️ **Qualcomm NPU** (helyi, GenieAPIService, Hexagon NPU)
  - 🤖 **Ollama** (helyi, CPU/GPU)
  - 🟠 **NexaAI** (helyi, NPU ASR)
  - 🔵 **Claude** (Anthropic — API kulcs szükséges)
  - ⚡ **Groq** (API kulcs szükséges)
  - 🟢 **OpenAI** (API kulcs szükséges)
  - 🔀 **OpenRouter** (API kulcs szükséges)
- **In-app API kulcskezelés** — kulcsok biztonságosan a helyi SQLite adatbázisban tárolódnak
- **Magyar / angol felület** (next-intl i18n)
- **SQLite** alapú helyi adattárolás — semmi sem kerül a felhőbe

---

## Architektúra

```
┌─────────────────────────────────────────────────┐
│              Meetily Snapdragon                 │
├──────────────┬──────────────────────────────────┤
│  Frontend    │  Backend (FastAPI, :5167)        │
│  Next.js     │                                  │
│  React 18    │  ├── /npu/*   → NPU átírás       │
│  port :3118  │  ├── /process-transcript         │
│              │  ├── /get-summary/:id            │
│  i18n: hu/en │  ├── /save-transcript            │
│              │  └── /get-meetings               │
└──────┬───────┴────────────┬─────────────────────┘
       │                    │
       │  API hívások       │  ASR + összefoglalás
       ▼                    ▼
┌─────────────────────┐  ┌────────────────────┐
│ GenieAPIService     │  │ Parakeet ASR       │
│ port :8911          │  │ E:\models-nexa\... │
│ QNN NPU → LLM       │  │ NPU gyorsítás      │
│ llama3.1-8b-qnn     │  │ magyar nyelv        │
└─────────────────────┘  └────────────────────┘
```

---

## Követelmények

### Hardver

- **Qualcomm Snapdragon X Elite** processzor (ajánlott)
- **RAM:** 16 GB minimum
- **NPU:** Hexagon NPU (45-80 TOPS)
- **Tárhely:** ~10 GB (modellek + alkalmazás)

### Szoftver

- **Windows 11 ARM64**
- **Python 3.12.8** (ARM64 natív, vagy x64 emulált)
- **Node.js 20+** (PNPM csomagkezelővel)
- **whisper.cpp** (opcionális, ARM64 build)
  - vagy ONNX Runtime + QNN Execution Provider

### Modellek

| Modell | Hely | Megjegyzés |
|--------|------|------------|
| **Parakeet TDT 0.6B v3 NPU** | `E:\models-nexa\models\NexaAI\parakeet-tdt-0.6b-v3-npu` | ASR (átírás) |
| **llama3.1-8b-8380-qnn2.38** | GenieAPIService betöltve | LLM (összefoglalás) |

---

## Telepítés

### 1. Repo klónozása

```bash
git clone https://github.com/gaiagent0/meetcore.git
cd meetcore
```

### 2. Backend telepítése

```bash
cd backend
pip install -r requirements.txt
```

### 3. Környezeti változók

```bash
# Másold az .env.example-t .env néven
copy .env.example backend\app\.env

# Szerkeszd a backend/app/.env fájlt a saját értékeiddel
notepad backend\app\.env
```

> Cloud provider API kulcsokat (Claude, Groq, OpenAI, OpenRouter) **nem .env-ben** kell megadni,  
> hanem az alkalmazás **Beállítások** oldalán, ahol biztonságosan a helyi SQLite adatbázisban tárolódnak.

### 4. Frontend telepítése

```bash
cd frontend
pnpm install
```

---

## Indítás

### Fejlesztői mód

```bash
# 1. terminál – Backend
cd backend\app
python main.py
# → http://localhost:5167

# 2. terminál – Frontend
cd frontend
pnpm run dev
# → http://localhost:3118/hu

# 3. terminál – GenieAPIService (opcionális)
GenieAPIService.exe --modelname "llama3.1-8b-8380-qnn2.38" --loadmodel
# → port 8911
```

### Vagy használhatod az indító scripteket:

```bash
scripts\start-meetily-npu.bat    # Minden indítása együtt
scripts\start-genie-service.bat  # Csak GenieAPIService
```

---

## Használat

1. **Nyisd meg** a frontendet: `http://localhost:3118/hu`
2. **Ellenőrizd az NPU státuszt** – zöld pont = online
3. **Vegyél fel meetinget** vagy **tölts fel hangfájlt**
4. **Válassz AI szolgáltatót** (NPU/Ollama = helyi, Claude/Groq stb. = felhő, API kulcs szükséges)
5. **Kattints az összefoglalás generálására**
6. Az eredmény megjelenik strukturált formában:
   - Résztvevők
   - Összefoglaló
   - Kritikus határidők
   - Főbb döntések
   - Teendők
   - Következő lépések

---

## API végpontok

### Backend (FastAPI :5167)

| Metode | Útvonal | Leírás |
|--------|---------|--------|
| GET | `/npu/status` | NPU hardver + GenieAPIService státusz |
| GET | `/npu/providers` | Összes provider státusza (frontend dict) |
| POST | `/npu/transcribe` | Hangfájl → szöveg (NPU ASR) |
| GET | `/npu/genie/models` | Elérhető NPU modellek |
| POST | `/npu/genie/health` | GenieAPIService liveness check |
| GET | `/settings/api-keys` | Cloud API kulcsok konfiguráltsága |
| POST | `/settings/api-keys` | Cloud API kulcs mentése |
| DELETE | `/settings/api-keys/{provider}` | Cloud API kulcs törlése |
| POST | `/process-transcript` | Átírás feldolgozása + összefoglalás |
| GET | `/get-summary/:id` | Összefoglaló lekérdezése |
| POST | `/save-transcript` | Meeting + átírás mentése |
| GET | `/get-meetings` | Összes meeting listája |
| POST | `/save-meeting-summary` | Összefoglaló manuális mentése |

### Swagger dokumentáció

Nyisd meg: `http://localhost:5167/docs`

---

## Környezeti változók

| Változó | Alapértelme | Leírás |
|---------|-------------|--------|
| `GENIE_BASE_URL` | `http://127.0.0.1:8912/v1` | GenieAPIService URL |
| `GENIE_MODEL` | `llama3.1-8b-8380-qnn2.38` | Betöltött NPU modell |
| `GENIE_TIMEOUT` | `120` | Timeout mp-ban |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama szerver URL |
| `OLLAMA_TIMEOUT` | `300` | Ollama timeout mp-ban |
| `NEXA_BASE_URL` | `http://127.0.0.1:18181/v1` | NexaAI szerver URL |
| `NEXA_TIMEOUT` | `300` | NexaAI timeout mp-ban |
| `WHISPER_LANGUAGE` | `hu` | Alapértelmezett ASR nyelv |
| `BACKEND_PORT` | `5167` | FastAPI port |

> **Cloud API kulcsok** (Claude, Groq, OpenAI, OpenRouter) az alkalmazás **Beállítások** oldalán adhatók meg.  
> Biztonságosan a helyi SQLite adatbázisban tárolódnak — nem .env-ben, nem kódban.

---

## Projekt struktúra

```
meetily-snapdragon/
├── CLAUDE.md                    # Architektúra dokumentáció
├── README.md                    # Ez a fájl
├── .env.example                 # Környezeti változó sablon
├── .gitignore
│
├── backend/
│   ├── requirements.txt         # Python függőségek
│   └── app/
│       ├── main.py              # FastAPI belépési pont
│       ├── transcript_processor.py # AI összefoglalás logika
│       ├── npu_routes.py        # NPU API végpontok
│       ├── whisper_npu.py       # ASR NPU integráció
│       ├── db.py                # SQLite adatbázis kezelés
│       ├── schema_validator.py  # Sém validátor
│       └── .env                 # API kulcsok (NE commitold!)
│
├── frontend/
│   ├── package.json             # Node.js függőségek
│   ├── next.config.js           # Next.js konfiguráció
│   ├── messages/
│   │   ├── hu.json              # Magyar fordítások
│   │   └── en.json              # Angol fordítások
│   └── src/
│       ├── i18n/
│       │   ├── routing.ts       # next-intl routing
│       │   └── request.ts       # next-intl request handler
│       ├── middleware.ts        # Nemzetköziesítés middleware
│       ├── app/[locale]/
│       │   ├── layout.tsx       # Locale layout
│       │   └── page.tsx         # Főoldal
│       └── components/
│           ├── ApiKeySettings.tsx   # Cloud API kulcskezelés UI
│           ├── ProviderSelector.tsx # Provider választó
│           ├── NPUStatus.tsx        # NPU státusz kijelző
│           ├── TranscriptView.tsx   # Átírás megjelenítő
│           └── AudioLevelMeter.tsx  # Hangerő mérő
│
├── scripts/
│   ├── start-meetily-npu.bat    # Teljes indítás
│   ├── start-genie-service.bat  # GenieAPIService indítás
│   └── build_whisper_arm64.cmd  # whisper.cpp ARM64 build
│
├── docs/
│   └── ARM64_SETUP.md           # ARM64 beállítási útmutató
│
└── whisper.cpp/                 # whisper.cpp submodule
```

---

## Biztonság

- `.env` fájl **SOHA** nem kerül a repoba (`.gitignore` védi)
- API kulcsok SQLite adatbázisban vannak tárolva, nem a kódban
- CORS beállítások fejlesztésben `*`, productionben konfiguráld!
- GenieAPIService helyi, nincs API kulcs szükséges

---

## Hibaelhárítás

### Device Guard hiba (Rust/Tauri build)

Windows Device Guard blokkolja a `cargo`/`rustc` futtatást.  
→ Python backend fejlesztés: bármely gépen OK  
→ Rust/Tauri build: CSAK Snapdragon X Elite gépen, Device Guard kikapcsolva

### GenieAPIService nem indul

1. Ellenőrizd, hogy a port nem foglalt (alapértelmezett: **8911**)
2. Ellenőrizd a modell elérési útját a `.env`-ben
3. Indítsd újra a szolgáltatást: `scripts\start-genie-service.bat`

### Nem találja a Parakeet modellt

Ellenőrizd a fájlt: `E:\models-nexa\models\NexaAI\parakeet-tdt-0.6b-v3-npu`  
Ha hiányzik, töltsd le a NexaAI segítségével.

---

## Fejlesztés

### Új AI provider hozzáadása

1. `backend/app/transcript_processor.py` – adj hozzá egy új `elif model ==` ágat
2. Ha OpenAI-kompatibilis → használd a `_call_openai_compatible_direct()` metódust
3. `backend/app/db.py` – add hozzá az új provider oszlopát a settings táblához
4. `backend/app/main.py` – add hozzá a `CLOUD_PROVIDERS` set-be
5. `frontend/src/components/ApiKeySettings.tsx` – add hozzá a `PROVIDERS` tömbhöz

### Új frontend oldal

1. Hozz létre egy fájlt: `frontend/src/app/[locale]/[oldal]/page.tsx`
2. Használd a `useTranslations()` hookot az i18n-hez
3. Adj hozzá fordításokat: `messages/hu.json` és `messages/en.json`

---

## License

Eredeti Meetily: https://github.com/Zackriya-Solutions/meetily  
MeetCore: https://github.com/gaiagent0/meetcore

---

## Elérhetőség

- **Repo:** https://github.com/gaiagent0/meetcore
- **Backend:** FastAPI 0.115.9 · Python 3.12
- **Frontend:** Next.js 15 · React 18 · TypeScript
