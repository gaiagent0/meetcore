"""
live_asr.py — MeetCore v3
WebSocket alapú élő beszédátírás Parakeet NPU-val.

Protokoll:
  Client → Server: binary audio chunks (16kHz mono PCM, 16-bit)
  Server → Client: JSON {"type":"partial"|"final","text":"...","ts":float}

VAD (Voice Activity Detection):
  - RMS energia alapú egyszerű VAD
  - Csendet detektál → chunk lezárás → Parakeet-re küldés
  - Beszéd közben buffer gyűjtés
"""
import asyncio
import io
import json
import logging
import os
import struct
import wave

import httpx
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

live_router = APIRouter()

NEXA_BASE_URL = os.getenv("NEXA_BASE_URL", "http://127.0.0.1:18181/v1").rstrip("/")
NEXA_ASR_MODEL = os.getenv("NEXA_ASR_MODEL", "NexaAI/parakeet-tdt-0.6b-v3-npu")
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD_MS = 1500   # 1.5s csend = chunk vége
CHUNK_MIN_DURATION_MS = 500   # Minimum chunk hossz


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """PCM 16-bit mono → WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _rms_energy(pcm_chunk: bytes) -> float:
    """RMS energia számítás VAD-hez."""
    if len(pcm_chunk) < 2:
        return 0.0
    samples = struct.unpack(f"<{len(pcm_chunk)//2}h", pcm_chunk)
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


async def _transcribe_chunk(wav_bytes: bytes, language: str = "hu") -> str:
    """WAV bytes → szöveg via Nexa Parakeet."""
    url = f"{NEXA_BASE_URL}/audio/transcriptions"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
            data={"model": NEXA_ASR_MODEL, "language": language},
        )
        resp.raise_for_status()
        result = resp.json()
    return (result.get("text") or result.get("transcript") or "").strip()


@live_router.websocket("/ws/live-asr")
async def live_asr_websocket(ws: WebSocket):
    """
    WebSocket élő ASR.

    Client küld: binary PCM 16-bit mono 16kHz (ArrayBuffer)
    Server válaszol: JSON {"type":"partial"|"final","text":"...","segment":int}
    """
    await ws.accept()
    logger.info("[LiveASR] WebSocket csatlakozva")

    pcm_buffer = bytearray()
    silence_frames = 0
    segment_count = 0
    language = "hu"

    SILENCE_ENERGY_THRESHOLD = 300
    FRAME_SIZE = SAMPLE_RATE * 2 * 30 // 1000  # 30ms frame
    SILENCE_FRAMES_LIMIT = SILENCE_THRESHOLD_MS // 30

    try:
        while True:
            data = await ws.receive()

            if "text" in data:
                try:
                    msg = json.loads(data["text"])
                    if msg.get("type") == "config":
                        language = msg.get("language", "hu")
                        logger.info(f"[LiveASR] Config: language={language}")
                    elif msg.get("type") == "stop":
                        if len(pcm_buffer) > CHUNK_MIN_DURATION_MS * SAMPLE_RATE * 2 // 1000:
                            wav = _pcm_to_wav(bytes(pcm_buffer))
                            text = await _transcribe_chunk(wav, language)
                            if text:
                                await ws.send_json({
                                    "type": "final", "text": text, "segment": segment_count,
                                })
                        await ws.send_json({"type": "done"})
                        break
                except Exception:
                    pass
                continue

            if "bytes" in data:
                audio_chunk = data["bytes"]
                pcm_buffer.extend(audio_chunk)

                energy = _rms_energy(audio_chunk)

                if energy < SILENCE_ENERGY_THRESHOLD:
                    silence_frames += len(audio_chunk) // FRAME_SIZE + 1
                else:
                    silence_frames = 0

                if (silence_frames >= SILENCE_FRAMES_LIMIT
                        and len(pcm_buffer) > CHUNK_MIN_DURATION_MS * SAMPLE_RATE * 2 // 1000):
                    wav = _pcm_to_wav(bytes(pcm_buffer))
                    text = await _transcribe_chunk(wav, language)

                    if text:
                        segment_count += 1
                        await ws.send_json({
                            "type": "final", "text": text, "segment": segment_count,
                        })

                    pcm_buffer.clear()
                    silence_frames = 0

    except WebSocketDisconnect:
        logger.info("[LiveASR] WebSocket bontva")
    except Exception as e:
        logger.error(f"[LiveASR] Hiba: {e}", exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
