"""
tts_service.py — MeetCore v3
Piper TTS: subprocess CLI → fallback HTTP proxy (hu-voice-assistant TTS szerver).
Nincs torch/piper Python csomag szükség — csak a CLI bináris.
"""
import asyncio
import io
import logging
import os
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PIPER_MODEL    = os.getenv("PIPER_MODEL",    r"E:\hu-voice-ai\models\hu_HU-anna-medium.onnx")
PIPER_SR       = int(os.getenv("PIPER_SR",  "22050"))    # anna-medium sample rate
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://localhost:7860")
TTS_TIMEOUT    = float(os.getenv("TTS_TIMEOUT", "30"))
PIPER_SPEED    = float(os.getenv("PIPER_SPEED", "1.0"))


def _find_piper() -> Optional[str]:
    found = shutil.which("piper")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "piper" / "piper.exe",
        Path("C:/piper/piper.exe"),
        Path("E:/piper/piper.exe"),
        Path(r"C:\piper\piper.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _pcm_to_wav(raw_pcm: bytes, sample_rate: int = PIPER_SR) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_pcm)
    return buf.getvalue()


async def synthesize_piper(text: str) -> Optional[bytes]:
    """Piper CLI subprocess → WAV bytes. None ha CLI/modell nem elérhető."""
    piper_bin = _find_piper()
    model_path = Path(PIPER_MODEL)
    if not piper_bin:
        logger.debug("[TTS] piper CLI nem található")
        return None
    if not model_path.exists():
        logger.debug(f"[TTS] Piper modell nem található: {model_path}")
        return None

    loop = asyncio.get_event_loop()

    def _run() -> bytes:
        result = subprocess.run(
            [piper_bin, "--model", str(model_path), "--output_raw", "--length_scale", str(1.0 / PIPER_SPEED)],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[:300])
        return result.stdout

    try:
        raw_pcm = await loop.run_in_executor(None, _run)
        return _pcm_to_wav(raw_pcm)
    except Exception as e:
        logger.warning(f"[TTS] Piper subprocess hiba: {e}")
        return None


async def synthesize_proxy(text: str, engine: str = "piper") -> bytes:
    """HTTP proxy → TTS szerver /synthesize (hu-voice-assistant kompatibilis)."""
    url = f"{TTS_SERVER_URL.rstrip('/')}/synthesize"
    async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as c:
        resp = await c.post(url, json={"text": text, "engine": engine, "speed": PIPER_SPEED})
        resp.raise_for_status()
    return resp.content


async def synthesize(text: str) -> bytes:
    """
    TTS pipeline:
      1. Piper CLI subprocess (ha elérhető)
      2. HTTP proxy a TTS szervernek
    Raises RuntimeError ha mindkettő sikertelen.
    """
    wav = await synthesize_piper(text)
    if wav:
        logger.info(f"[TTS] Piper CLI: {len(text)} kar → {len(wav)} byte WAV")
        return wav
    try:
        wav = await synthesize_proxy(text)
        logger.info(f"[TTS] Proxy: {len(text)} kar → {len(wav)} byte WAV")
        return wav
    except Exception as e:
        raise RuntimeError(f"TTS szintézis sikertelen (piper CLI + proxy): {e}") from e


async def tts_available() -> dict:
    """Ellenőrzi, hogy melyik TTS backend elérhető."""
    piper_bin  = _find_piper()
    model_ok   = Path(PIPER_MODEL).exists()
    proxy_ok   = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{TTS_SERVER_URL.rstrip('/')}/health")
            proxy_ok = r.status_code < 500
    except Exception:
        pass
    return {
        "piper_cli":   bool(piper_bin),
        "piper_model": model_ok,
        "proxy":       proxy_ok,
        "proxy_url":   TTS_SERVER_URL,
        "available":   bool(piper_bin and model_ok) or proxy_ok,
    }
