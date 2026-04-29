# MeetCore — Állapotjelentés
> **Dátum:** 2026-04-29 | **Branch:** master | **Repo:** gaiagent0/meetcore

---

## Stack

| Réteg | Technológia | Port |
|-------|------------|------|
| Backend | FastAPI + Python 3.12 | 5167 |
| Frontend | Next.js 15 + React 19 + next-intl (hu/en) | 3118 |
| DB | SQLite (aiosqlite) — `meeting_minutes.db` | — |
| NPU ASR | NexaAI Parakeet TDT 0.6B v3 | 18181 |
| NPU LLM | GenieAPIService (Llama 3.1 8B QNN) | 8912 |
| Nexa LLM | Qwen3-8B-NPU | 18182 |
| Nexa Multimodal | OmniNeural-4B | 18183 |
| Ollama | qwen2.5:14b, deepseek-r1:8b stb. | 11434 |

---

## Backend — Implementált végpontok

### main.py (FastAPI :5167)
```
GET  /health
POST /process-transcript-stream    → SSE streaming összefoglaló
POST /process-transcript           → szinkron összefoglaló
POST /save-transcript              → meeting + átírás mentése DB-be
GET  /get-meetings                 → meeting lista
GET  /search-meetings?q=           → full-text keresés
GET  /get-summary/{id}             → meeting + summary lekérés
POST /save-meeting-summary         → summary frissítés
DELETE /delete-meeting/{id}
GET  /settings/api-keys            → cloud provider kulcs státusz
POST /settings/api-keys            → API kulcs mentése (SQLite)
DELETE /settings/api-keys/{provider}
```

### npu_routes.py (/npu/*)
```
GET  /npu/status                   → összes provider státusz
GET  /npu/providers                → frontend dict formátum
POST /npu/transcribe               → Parakeet ASR (fájl feltöltés)
GET  /npu/genie/models
POST /npu/genie/health
GET  /npu/ollama/models
GET  /npu/nexa/health
POST /npu/omnineural/audio-summary → audio → summary egyetlen lépésben
GET  /npu/nexa/datadir             → NEXA_DATADIR lekérdezés (DB/env/default)
POST /npu/nexa/datadir             → NEXA_DATADIR beállítás (DB-ben tárolva)
GET  /npu/nexa/services            → ASR/LLM/Multimodal service státusz
POST /npu/nexa/services/{name}/start
POST /npu/nexa/services/{name}/stop
```

### live_asr.py (/ws/*)
```
WS   /ws/live-asr                  → WebSocket élő ASR (PCM 16kHz mono → szöveg)
```

### chat_routes.py (/chat/*)
```
POST /chat/{meeting_id}            → kérdés-válasz a meeting kontextusában
POST /chat/{meeting_id}/stream     → SSE streaming chat
```

### tts_routes.py (/tts/*)
```
GET  /tts/status
POST /tts/synthesize               → Piper TTS (WAV)
POST /tts/clone                    → F5-TTS hangklónozás
```

---

## Backend — Modulok

| Fájl | Funkció | Állapot |
|------|---------|---------|
| `main.py` | FastAPI app, CORS, DB init, meeting CRUD, API key mgmt | ✅ |
| `transcript_processor.py` | 7 provider routing, model-family prompting, chunkolás | ✅ |
| `npu_routes.py` | NPU/Nexa/Ollama/OmniNeural endpointok, Nexa manager | ✅ |
| `live_asr.py` | WebSocket ASR, VAD (RMS energia), Parakeet | ✅ |
| `chat_routes.py` | Meeting chat, 7 provider, RAG kontextus, SSE streaming | ✅ |
| `tts_routes.py` | Piper TTS + F5-TTS hangklón endpointok | ✅ |
| `tts_service.py` | Piper ONNX szintézis (hu_HU-anna-medium) | ✅ |
| `voice_clone.py` | F5-TTS hangklónozás | ✅ |
| `rag_service.py` | ChromaDB + BM25 RRF ensemble retriever | ✅ |
| `nexa_manager.py` | Nexa service start/stop/status, NEXA_DATADIR inject | ✅ |
| `db.py` | SQLite: meetings, transcripts, summaries, API keys, app_settings | ✅ |
| `whisper_npu.py` | ARM64 Device Guard kezelés, is_npu_available() | ✅ |
| `schema_validator.py` | Summary JSON schema validáció | ✅ |

### Transcript provider támogatás
`npu` · `ollama` · `nexa` · `omnineural` · `claude` · `groq` · `openai` · `openrouter`

### Model-family prompting
`reasoning` · `nexa_npu` · `qwen3` · `qwen2` · `gemma` · `llama` · `omnineural` · `generic`

---

## Frontend — Komponensek

| Komponens | Funkció | Oldal |
|-----------|---------|-------|
| `page.tsx` | Főoldal: rögzítés, összefoglaló, provider választó | `/[locale]/` |
| `meetings/page.tsx` | Meeting lista, keresés, törlés | `/[locale]/meetings` |
| `meetings/[id]/page.tsx` | Detail: summary szekciók, chat panel, TTS | `/[locale]/meetings/[id]` |
| `NPUStatus.tsx` | Provider badge-ek (lokális + cloud), Whisper státusz | Főoldal |
| `NexaServicePanel.tsx` | Nexa ASR/LLM/Multimodal start/stop, NEXA_DATADIR szerkesztő | Főoldal |
| `ProviderSelector.tsx` | AI provider + modell választó (8 provider) | Főoldal |
| `ApiKeySettings.tsx` | Cloud API kulcs kezelés (Claude/Groq/OpenAI/OpenRouter) | Főoldal |
| `LiveTranscript.tsx` | WebSocket élő ASR, PCM rögzítés, AudioWorklet | Főoldal |
| `TranscriptView.tsx` | Átírás megjelenítés, szegmens lista | Főoldal |
| `AudioLevelMeter.tsx` | Valós idejű hangerő vizualizáció | Főoldal |
| `SummaryGeneratorPanel.tsx` | Összefoglaló generálás trigger, provider választás | Meeting detail |
| `TtsPlayer.tsx` | Piper TTS lejátszó (összefoglaló felolvasás) | Meeting detail |
| `HelpModal.tsx` | Billentyűparancsok, útmutató | Főoldal |
| `LocaleSwitcher.tsx` | hu/en váltó | Minden oldal |

### i18n kulcsok
`common` · `recording` · `summary` · `npu` · `home` · `transcript` · `live` · `providerSelector` · `help`

---

## DB séma (SQLite)

```
meetings          — id, title, created_at, updated_at
transcripts       — id, meeting_id, text, created_at
summary_processes — id, meeting_id, status, provider, ...
transcript_chunks — id, meeting_id, chunk_index, text, vector
settings          — API kulcsok (groq, openai, anthropic, openrouter)
transcript_settings
app_settings      — kulcs-érték (pl. nexa_datadir)
```

---

## Tesztek

```
backend/tests/
  conftest.py
  test_transcript_processor.py  — 50+ teszt (model family, prompting, JSON parse, summary)
  test_live_asr.py              — PCM→WAV, RMS energia, WebSocket mock
  test_npu_routes.py            — provider status, transcribe mock
```
**Eredmény: 74 passed, 0 failed** (`python -m pytest tests/ -v`)

---

## Docker

```yaml
# docker-compose.yml
services:
  backend:   python:3.12-slim + ffmpeg, volume: ./data/meeting_minutes.db
  frontend:  node:20-alpine multi-stage, standalone Next.js
```
- `extra_hosts: host.docker.internal:host-gateway` → AI szolgáltatások elérése hostról
- `NEXA_DATADIR` env átadva a containerből

---

## API kulcs kezelés

Cloud API kulcsok **soha nem** .env-ben — SQLite `settings` táblában tárolva.  
Felület: Főoldal → Beállítások (ApiKeySettings komponens).  
Backend: `GET/POST/DELETE /settings/api-keys`

---

## Ismert hiányosságok / Tech debt

| Téma | Megjegyzés |
|------|-----------|
| `voice_clone.py` | F5-TTS → ARM64-en ~85s/chunk, production-ban lassú |
| `Qwen3-8B-NPU` | Nexa betöltési hiba, LLM service gyakorlatilag nem működik |
| CORS | `allow_origins=["*"]` — production előtt szűkíteni |
| `tsbuildinfo` | `.gitignore`-ba lehetne rakni |

---

## Következő lehetséges fejlesztések

- Nexa LLM service csere működő modellre (pl. `NexaAI/qwen3-4B-npu`)
- Meeting export (PDF/Word)
- Valós idejű összefoglaló frissítés rögzítés közben
- Felhasználói auth (ha megosztott deployment)
