"""
voice_clone.py — MeetCore v3
F5-TTS hangklónozás HTTP proxy-n át (hu-voice-assistant TTS szerver).
WebM/MP3/OGG → 24kHz WAV mono (ffmpeg) → F5-TTS /synthesize multipart POST.
"""
import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://localhost:7860")
F5_MAX_CHARS   = int(os.getenv("F5_MAX_CHARS",  "150"))
F5_TIMEOUT     = float(os.getenv("F5_TIMEOUT",  "300"))


async def _to_wav24k(audio_bytes: bytes, src_ext: str = "webm") -> bytes:
    """
    ffmpeg: WebM/MP3/OGG/M4A → WAV 24kHz mono s16le.
    F5-TTS 24kHz mono WAV-ot vár.
    Returns original bytes ha ffmpeg nem elérhető.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("[VoiceClone] ffmpeg nem található — konverzió kihagyva")
        return audio_bytes

    loop = asyncio.get_event_loop()

    def _run() -> bytes:
        src = tempfile.NamedTemporaryFile(suffix=f".{src_ext}", delete=False)
        src.write(audio_bytes)
        src.close()
        dst = src.name + "_24k.wav"
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", src.name,
                 "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", "-f", "wav", dst],
                capture_output=True, timeout=60, check=True,
            )
            return Path(dst).read_bytes()
        finally:
            Path(src.name).unlink(missing_ok=True)
            Path(dst).unlink(missing_ok=True)

    try:
        return await loop.run_in_executor(None, _run)
    except Exception as e:
        logger.warning(f"[VoiceClone] ffmpeg konverzió hiba: {e}")
        return audio_bytes


async def clone_voice(text: str, ref_audio: bytes, ref_ext: str = "webm") -> bytes:
    """
    F5-TTS hangklónozás:
      ref_audio + text → klónozott WAV (a TTS szerver F5-TTS engine-jén át)

    Paraméterek:
      text      – szintetizálandó szöveg (max F5_MAX_CHARS)
      ref_audio – referencia hangminta bytes
      ref_ext   – forrás kiterjesztés (webm/mp3/wav/ogg/m4a)
    """
    if len(text) > F5_MAX_CHARS:
        logger.warning(f"[VoiceClone] szöveg truncation: {len(text)} → {F5_MAX_CHARS} kar")
        text = text[:F5_MAX_CHARS]

    wav_bytes = await _to_wav24k(ref_audio, src_ext=ref_ext)

    url = f"{TTS_SERVER_URL.rstrip('/')}/synthesize"
    try:
        async with httpx.AsyncClient(timeout=F5_TIMEOUT) as c:
            resp = await c.post(
                url,
                data={"text": text, "engine": "f5tts"},
                files={"ref_audio": ("reference.wav", wav_bytes, "audio/wav")},
            )
            resp.raise_for_status()
    except httpx.ConnectError as e:
        raise RuntimeError(
            f"TTS szerver nem elérhető ({TTS_SERVER_URL}). "
            f"Indítsd el a hu-voice-assistant TTS szervert: docker compose up tts-server"
        ) from e

    return resp.content
