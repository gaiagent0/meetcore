"""
tts_routes.py — MeetCore v3
TTS és hangklónozás endpoints.
POST /tts/synthesize   — szöveg → WAV (Piper)
POST /tts/clone        — referencia hang + szöveg → klónozott WAV (F5-TTS)
GET  /tts/status       — elérhető TTS backendek
"""
import logging

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import Response

logger = logging.getLogger(__name__)

tts_router = APIRouter(prefix="/tts", tags=["TTS"])


@tts_router.get("/status", summary="TTS backend státusz")
async def tts_status():
    from tts_service import tts_available
    return await tts_available()


@tts_router.post("/synthesize", summary="Szöveg → WAV (Piper TTS)")
async def synthesize(
    text: str = Form(..., min_length=1, max_length=2000),
):
    """
    Szöveg szintézis Piper TTS-sel.
    CLI subprocess → HTTP proxy fallback.
    Visszaad: audio/wav
    """
    from tts_service import synthesize as _synth
    try:
        wav = await _synth(text)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return Response(content=wav, media_type="audio/wav")


@tts_router.post("/clone", summary="Hangklónozás F5-TTS-sel")
async def clone(
    text: str = Form(..., min_length=1),
    ref_audio: UploadFile = File(..., description="Referencia hangminta (WAV/WebM/MP3)"),
):
    """
    F5-TTS hangklónozás: referencia hangminta alapján szintetizál.
    Szöveg max F5_MAX_CHARS (env var, default 150).
    Visszaad: audio/wav
    """
    from voice_clone import clone_voice
    audio_bytes = await ref_audio.read()
    ext = (ref_audio.filename or "ref.webm").rsplit(".", 1)[-1].lower()
    try:
        wav = await clone_voice(text=text, ref_audio=audio_bytes, ref_ext=ext)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return Response(content=wav, media_type="audio/wav")
