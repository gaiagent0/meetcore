"""
npu_routes.py — Meetily Snapdragon
NPU, Ollama, NexaAI és felhős provider API végpontok.
"""

import logging
import os
from pathlib import Path

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from transcript_processor import (
    _normalize_url,
    check_all_providers, check_genie_health, check_nexa_health, check_ollama_health,
    _text_to_summary,
    GENIE_BASE_URL, OLLAMA_HOST, NEXA_BASE_URL, NEXA_MULTIMODAL_URL, OMNINEURAL_MODEL,
)

logger = logging.getLogger(__name__)

npu_router = APIRouter()

GENIE_TIMEOUT = float(os.getenv("GENIE_TIMEOUT", "10"))
GENIE_MODEL   = os.getenv("GENIE_MODEL", "llama3.1-8b-8380-qnn2.38")


# ── /npu/status ──────────────────────────────────────────────────────────────

@npu_router.get("/status", summary="Összes provider státusza")
async def npu_status():
    try:
        from whisper_npu import is_npu_available
        whisper_hw = is_npu_available()
    except Exception as e:
        whisper_hw = {"error": str(e)}

    providers = await check_all_providers()

    return {
        "providers": providers,
        "genie_api": {
            "url":    GENIE_BASE_URL,
            "online": providers.get("npu", {}).get("online", False),
            "models": providers.get("npu", {}).get("models", []),
        },
        "whisper": whisper_hw,
    }


# ── /npu/providers — DICT formátum a ProviderSelector-nak ───────────────────
# A frontend ezt várja: response[provider_id].online, response[provider_id].models

@npu_router.get("/providers", summary="Összes provider — frontend dict formátumban")
async def list_providers():
    """
    Visszaad egy dict-et: { "npu": {...}, "ollama": {...}, "claude": {...}, ... }
    Cloud providerek online státusza = API kulcs be van-e állítva (DB vagy .env).
    """
    providers = await check_all_providers()

    # Cloud provider státusz felülírása DB-ből
    try:
        from db import DatabaseManager
        _db = DatabaseManager()
        for cloud in ("claude", "groq", "openai", "openrouter"):
            key = await _db.get_api_key(cloud)
            if cloud in providers:
                providers[cloud]["online"] = bool(key)
    except Exception as e:
        logger.debug(f"DB-alapú cloud key check sikertelen: {e}")

    return providers


# ── /npu/transcribe ──────────────────────────────────────────────────────────

@npu_router.post("/transcribe", summary="Hangfájl átírása NPU-val (NexaAI Parakeet)")
async def npu_transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="hu"),
    backend: str = Form(default="auto"),
):
    """
    ASR pipeline: NexaAI Parakeet NPU (:18181).
    Ha a Parakeet nem fut → 503 + instrukcióval.
    Nincs whisper.cpp fallback (nincs konfigurálva).
    """
    audio_bytes = await file.read()
    filename = file.filename or "recording.webm"

    try:
        transcript = await _transcribe_nexa(audio_bytes, language, filename)
        return {"text": transcript, "language": language, "backend": "nexa-parakeet"}
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "nexa_offline",
                "message": (
                    "NexaAI Parakeet ASR nem fut. "
                    "Indítsd el: nexa serve NexaAI/parakeet-tdt-0.6b-v3-npu"
                ),
                "port": 18181,
                "url": NEXA_BASE_URL,
            },
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "nexa_http_error",
                "message": f"NexaAI HTTP {e.response.status_code}: {e.response.text[:200]}",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR hiba: {e}")


# ── /npu/genie/models ────────────────────────────────────────────────────────

@npu_router.get("/genie/models", summary="GenieAPIService modelljei")
async def genie_models():
    try:
        async with httpx.AsyncClient(timeout=GENIE_TIMEOUT) as client:
            r = await client.get(f"{GENIE_BASE_URL}/models")
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"GenieAPIService nem érhető el: {GENIE_BASE_URL}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@npu_router.post("/genie/health", summary="GenieAPIService liveness check")
async def genie_health():
    try:
        async with httpx.AsyncClient(timeout=GENIE_TIMEOUT) as client:
            r = await client.post(
                f"{GENIE_BASE_URL}/chat/completions",
                json={"model": GENIE_MODEL, "messages": [{"role": "user", "content": "Hi"}], "max_tokens": 5},
            )
            return {"online": r.status_code < 500, "status_code": r.status_code}
    except httpx.ConnectError:
        return {"online": False, "error": "Connection refused"}
    except Exception as e:
        return {"online": False, "error": str(e)}


# ── /npu/ollama/models ───────────────────────────────────────────────────────

@npu_router.get("/ollama/models", summary="Ollama betöltött modelljei")
async def ollama_models():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_HOST}/api/tags")
            r.raise_for_status()
            return r.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail=f"Ollama nem érhető el: {OLLAMA_HOST}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── /npu/nexa/health ─────────────────────────────────────────────────────────

@npu_router.get("/nexa/health", summary="NexaAI server elérhetőség")
async def nexa_health():
    info = await check_nexa_health()
    if not info["online"]:
        raise HTTPException(status_code=503, detail=f"NexaAI nem érhető el: {info.get('error')}")
    return info


# ── /npu/omnineural/audio-summary ────────────────────────────────────────────

@npu_router.post("/omnineural/audio-summary", summary="Audio → összefoglaló OmniNeural-4B-vel (egyetlen lépés)")
async def omnineural_audio_summary(
    file: UploadFile = File(...),
    language: str = Form(default="hu"),
):
    """
    Audio közvetlenül OmniNeural-4B-nek — nem kell külön ASR lépés.
    Az audio base64-be kerül és a modell multimodálisan kezeli.
    Visszaad SummaryResponse-kompatibilis dict-et.
    """
    import base64

    audio_bytes = await file.read()
    audio_b64 = base64.b64encode(audio_bytes).decode()

    ext = (file.filename or "recording.webm").rsplit(".", 1)[-1].lower()
    mime = {
        "wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4",
        "ogg": "audio/ogg", "webm": "audio/webm",
    }.get(ext, "audio/wav")

    url = f"{NEXA_MULTIMODAL_URL}/chat/completions"
    payload = {
        "model": OMNINEURAL_MODEL,
        "messages": [
            {"role": "system", "content": "Meeting összefoglaló asszisztens. Magyar nyelven."},
            {"role": "user", "content": [
                {"type": "audio", "audio": {"data": audio_b64, "format": ext}},
                {"type": "text", "text": (
                    "Foglald össze MAGYARUL a felvételt!\n\n"
                    "RÉSZTVEVŐK:\nÖSSZEFOGLALÓ:\nHATÁRIDŐK:\nDÖNTÉSEK:\nTEENDŐK:\nKÖVETKEZŐ LÉPÉSEK:"
                )},
            ]},
        ],
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "omnineural_offline",
                "message": f"OmniNeural-4B nem fut. Indítsd: nexa serve {OMNINEURAL_MODEL} --port 18183",
                "port": 18183,
                "url": NEXA_MULTIMODAL_URL,
            },
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": "omnineural_http_error", "message": f"HTTP {e.response.status_code}: {e.response.text[:300]}"},
        )

    raw = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    if not raw.strip():
        raise HTTPException(status_code=502, detail="OmniNeural üres választ adott")

    summary = _text_to_summary(raw, chunk_index=0)
    return summary.model_dump()


# ── /npu/nexa/services ───────────────────────────────────────────────────────

try:
    from nexa_manager import status_all as _nexa_status_all, start_service as _nexa_start, stop_service as _nexa_stop
    _nexa_manager_ok = True
except ImportError as _e:
    logger.warning(f"nexa_manager nem elérhető: {_e}")
    _nexa_manager_ok = False


@npu_router.get("/nexa/services", summary="Nexa szolgáltatások státusza")
async def nexa_services_status():
    """Visszaadja az összes kezelt Nexa szolgáltatás állapotát (managed + HTTP health)."""
    if not _nexa_manager_ok:
        raise HTTPException(status_code=503, detail="nexa_manager modul nem elérhető")
    return await _nexa_status_all()


@npu_router.post("/nexa/services/{name}/start", summary="Nexa szolgáltatás indítása")
async def nexa_service_start(name: str):
    """
    Elindítja a megadott Nexa szolgáltatást (asr | llm | multimodal).
    Subprocess háttérben; azonnali pid visszaadás.
    """
    if not _nexa_manager_ok:
        raise HTTPException(status_code=503, detail="nexa_manager modul nem elérhető")
    result = _nexa_start(name)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@npu_router.post("/nexa/services/{name}/stop", summary="Nexa szolgáltatás leállítása")
async def nexa_service_stop(name: str):
    """Leállítja a megadott Nexa szolgáltatást (terminate → kill fallback)."""
    if not _nexa_manager_ok:
        raise HTTPException(status_code=503, detail="nexa_manager modul nem elérhető")
    return _nexa_stop(name)


# ── Belső: NexaAI Parakeet átírás ────────────────────────────────────────────

NEXA_ASR_MODEL = os.getenv("NEXA_ASR_MODEL", "NexaAI/parakeet-tdt-0.6b-v3-npu")

async def _transcribe_nexa(audio_bytes: bytes, language: str = "hu", filename: str = "recording.webm") -> str:
    import tempfile, subprocess, shutil
    from pathlib import Path

    url = f"{NEXA_BASE_URL}/audio/transcriptions"
    timeout = float(os.getenv("NEXA_TIMEOUT", "120"))

    send_bytes = audio_bytes
    send_name  = filename
    tmp_files: list[str] = []

    ext = filename.rsplit(".", 1)[-1].lower()
    if ext != "wav":
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            src = tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False)
            src.write(audio_bytes); src.close()
            dst_path = src.name.rsplit(".", 1)[0] + "_conv.wav"
            tmp_files += [src.name, dst_path]
            r = subprocess.run(
                [ffmpeg, "-y", "-i", src.name, "-ar", "16000", "-ac", "1", "-f", "wav", dst_path],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0 and Path(dst_path).exists():
                send_bytes = Path(dst_path).read_bytes()
                send_name  = "recording.wav"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                files={"file": (send_name, send_bytes, "audio/wav" if send_name.endswith(".wav") else "audio/octet-stream")},
                data={"model": NEXA_ASR_MODEL, "language": language},
            )
            resp.raise_for_status()
            result = resp.json()
    finally:
        for f in tmp_files:
            Path(f).unlink(missing_ok=True)

    text = result.get("text") or result.get("transcript") or ""
    if not text:
        raise ValueError(f"NexaAI üres átírást adott: {result}")
    return text.strip()
