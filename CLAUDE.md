# CLAUDE.md — MeetCore

> Claude Code project context file.

---

## Project

**Name:** MeetCore  
**Stack:** FastAPI backend (port 5167) + Next.js 15 frontend (port 3118) + next-intl (hu/en)  
**Goal:** AI meeting assistant — local NPU-first, with optional cloud provider support  
**Platform:** Qualcomm Snapdragon X Elite ARM64, Windows 11

---

## Architecture

```
FastAPI Backend (Python, port 5167)
  ├── npu        → GenieAPIService http://127.0.0.1:8912/v1  (Qualcomm NPU)
  ├── nexa       → NexaAI server   http://127.0.0.1:18181/v1 (NPU ASR)
  ├── ollama     → http://localhost:11434
  ├── claude     → Anthropic API   (key stored in SQLite DB)
  ├── groq       → Groq API        (key stored in SQLite DB)
  ├── openai     → OpenAI API      (key stored in SQLite DB)
  └── openrouter → OpenRouter API  (key stored in SQLite DB)

Next.js Frontend (port 3118)
  ├── ProviderSelector  — local / cloud provider switch
  ├── ApiKeySettings    — per-provider API key management UI
  ├── NPUStatus         — GenieAPIService health indicator
  └── next-intl i18n    — hu / en

GenieAPIService.exe (Qualcomm, port 8912)
  └── Hexagon NPU — Llama 3.1 8B INT4, 45 TOPS, <5W
```

---

## API Key Management

Cloud provider API keys are stored in the **local SQLite database** (`meeting_minutes.db`).  
Keys are **never** stored in environment variables or committed to git.

**Backend endpoints:**
```
GET    /settings/api-keys           → { claude: bool, groq: bool, ... }
POST   /settings/api-keys           → { provider, api_key }
DELETE /settings/api-keys/{provider}
```

**DB method:** `db.save_api_key(key, provider)` / `db.get_api_key(provider)`  
**Supported providers:** `claude`, `groq`, `openai`, `openrouter`

---

## Environment Variables (`backend/app/.env`)

```env
# Qualcomm GenieAPIService (local NPU)
GENIE_BASE_URL=http://127.0.0.1:8912/v1
GENIE_MODEL=llama3.1-8b-8380-qnn2.38
GENIE_TIMEOUT=120

# Ollama (local CPU)
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_TIMEOUT=300

# NexaAI (NPU ASR + LLM)
NEXA_BASE_URL=http://127.0.0.1:18181/v1
NEXA_TIMEOUT=300
PARAKEET_MODEL_PATH=<path_to_model>

# Whisper ASR
WHISPER_LANGUAGE=hu

# FastAPI
BACKEND_PORT=5167
```

Cloud API keys (Claude, Groq, OpenAI, OpenRouter) are set via the **in-app Settings UI**,  
not via .env. They are stored in the local SQLite database.

---

## Project Structure

```
meetcore/
├── CLAUDE.md
├── README.md
├── .env.example
├── .gitignore
│
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py                  ← FastAPI app, API key endpoints
│       ├── transcript_processor.py  ← all providers, DB key resolver
│       ├── npu_routes.py            ← /npu/* endpoints
│       ├── whisper_npu.py           ← ARM64 Whisper ASR
│       ├── db.py                    ← SQLite, API key storage
│       └── schema_validator.py
│
├── frontend/
│   ├── package.json
│   ├── next.config.js
│   ├── messages/
│   │   ├── hu.json
│   │   └── en.json
│   └── src/
│       ├── middleware.ts
│       ├── i18n/
│       ├── app/[locale]/
│       │   ├── layout.tsx
│       │   └── page.tsx
│       └── components/
│           ├── ApiKeySettings.tsx   ← cloud API key management UI
│           ├── ProviderSelector.tsx
│           ├── NPUStatus.tsx
│           ├── TranscriptView.tsx
│           ├── AudioLevelMeter.tsx
│           └── HelpModal.tsx
│
└── scripts/
    └── start-meetcore.bat
```

---

## Development Commands

```bash
# Backend
cd backend/app
pip install -r ../requirements.txt
python main.py

# Frontend
cd frontend
pnpm install
pnpm dev          # http://localhost:3118
```

---

## Key Rules

- API keys are NEVER hardcoded or committed — always via `/settings/api-keys` endpoint
- Local providers (NPU, Ollama, NexaAI) work without any API key
- The app is fully functional offline with local providers only
- `*.db` files are in `.gitignore` — never committed
- `*.env` files (except `.env.example`) are in `.gitignore`
