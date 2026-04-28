"""
test_live_asr.py — MeetCore v3
Futtatás: cd backend && python -m pytest tests/ -v
Nem igényel futó szolgáltatásokat.
"""
import io
import struct
import wave
from unittest.mock import AsyncMock, patch

import pytest

from live_asr import _pcm_to_wav, _rms_energy, live_router


# ── _pcm_to_wav ───────────────────────────────────────────────────────────────

class TestPcmToWav:
    def test_output_is_valid_wav(self):
        pcm = struct.pack("<100h", *([1000] * 100))
        wav_bytes = _pcm_to_wav(pcm)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    def test_frame_count_matches_pcm(self):
        samples = [500] * 200
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        wav_bytes = _pcm_to_wav(pcm)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == len(samples)

    def test_custom_sample_rate(self):
        pcm = struct.pack("<10h", *([0] * 10))
        wav_bytes = _pcm_to_wav(pcm, sample_rate=8000)
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getframerate() == 8000

    def test_empty_pcm_produces_valid_wav(self):
        wav_bytes = _pcm_to_wav(b"")
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 0

    def test_returns_bytes(self):
        pcm = struct.pack("<4h", 0, 100, -100, 0)
        assert isinstance(_pcm_to_wav(pcm), bytes)


# ── _rms_energy ───────────────────────────────────────────────────────────────

class TestRmsEnergy:
    def test_silence_is_zero(self):
        pcm = struct.pack("<100h", *([0] * 100))
        assert _rms_energy(pcm) == 0.0

    def test_positive_energy(self):
        samples = [1000] * 100
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        assert _rms_energy(pcm) == pytest.approx(1000.0)

    def test_mixed_positive_negative(self):
        samples = [1000, -1000] * 50
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        assert _rms_energy(pcm) == pytest.approx(1000.0)

    def test_empty_chunk(self):
        assert _rms_energy(b"") == 0.0

    def test_single_byte_chunk(self):
        assert _rms_energy(b"\xff") == 0.0

    def test_louder_signal_higher_energy(self):
        quiet = struct.pack("<100h", *([100] * 100))
        loud  = struct.pack("<100h", *([10000] * 100))
        assert _rms_energy(loud) > _rms_energy(quiet)


# ── WebSocket endpoint teszt ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_websocket_config_message():
    """Config üzenet feldolgozása — nincs élő Parakeet szükséges."""
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    import httpx

    app = FastAPI()
    app.include_router(live_router)

    # WebSocket tesztelése starlette TestClient-tel
    from starlette.testclient import TestClient
    client = TestClient(app)

    with client.websocket_connect("/ws/live-asr") as ws:
        # config üzenet küldése
        ws.send_json({"type": "config", "language": "en"})
        # stop üzenet — buffer üres, done-t kell kapni
        ws.send_json({"type": "stop"})
        msg = ws.receive_json()
        assert msg["type"] == "done"


@pytest.mark.asyncio
async def test_websocket_transcribes_on_silence():
    """Csend detektálás után chunk küldés mock Parakeet-tel."""
    import struct as _struct
    from starlette.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(live_router)

    # 16kHz-en 2 másodperc csend = silence_frames >= limit
    # SILENCE_THRESHOLD_MS=1500, FRAME_SIZE=480 (30ms), SILENCE_FRAMES_LIMIT=50
    # Küldünk sok kis csendes chunk-ot
    silence_chunk = _struct.pack("<480h", *([0] * 480))  # 30ms néma PCM
    # CHUNK_MIN_DURATION_MS=500 → min 500ms = 16000 sample = 32000 byte
    long_silence = silence_chunk * 70  # 2.1s néma PCM

    mock_text = "teszt átírás szöveg"

    with patch("live_asr._transcribe_chunk", new_callable=AsyncMock, return_value=mock_text):
        client = TestClient(app)
        with client.websocket_connect("/ws/live-asr") as ws:
            ws.send_bytes(long_silence)
            msg = ws.receive_json()
            assert msg["type"] == "final"
            assert msg["text"] == mock_text
            ws.send_json({"type": "stop"})
            done = ws.receive_json()
            assert done["type"] == "done"
