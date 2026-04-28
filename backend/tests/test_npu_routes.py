"""
test_npu_routes.py — MeetCore v3
Futtatás: cd backend && python -m pytest tests/ -v
Nem igényel futó szolgáltatásokat — mock-olt httpx hívások.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_app():
    from npu_routes import npu_router
    app = FastAPI()
    app.include_router(npu_router, prefix="/npu")
    return app


# ── /npu/status ───────────────────────────────────────────────────────────────

class TestNpuStatus:
    def test_status_returns_ok(self):
        mock_providers = {
            "npu":        {"online": False, "models": [], "url": "http://localhost:8912"},
            "ollama":     {"online": False, "models": [], "url": "http://localhost:11434"},
            "nexa":       {"online": False, "models": [], "url": "http://localhost:18181"},
            "omnineural": {"online": False, "models": [], "url": "http://localhost:18183"},
            "claude":     {"online": False, "models": []},
            "groq":       {"online": False, "models": []},
            "openai":     {"online": False, "models": []},
            "openrouter": {"online": False, "models": []},
        }

        with patch("npu_routes.check_all_providers", new_callable=AsyncMock, return_value=mock_providers), \
             patch("npu_routes.is_npu_available", return_value={"available": False}, create=True):
            client = TestClient(_make_app())
            resp = client.get("/npu/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data

    def test_providers_endpoint(self):
        mock_providers = {
            "npu":    {"online": True,  "models": ["llama3.1-8b-qnn"]},
            "ollama": {"online": False, "models": []},
            "nexa":   {"online": False, "models": []},
            "omnineural": {"online": False, "models": []},
            "claude": {"online": False, "models": []},
            "groq":   {"online": False, "models": []},
            "openai": {"online": False, "models": []},
            "openrouter": {"online": False, "models": []},
        }
        with patch("npu_routes.check_all_providers", new_callable=AsyncMock, return_value=mock_providers):
            client = TestClient(_make_app())
            resp = client.get("/npu/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["npu"]["online"] is True


# ── /npu/transcribe ───────────────────────────────────────────────────────────

class TestNpuTranscribe:
    def _transcribe(self, mock_text="teszt átírás", status_code=200, audio_bytes=b"fake_wav"):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json.return_value = {"text": mock_text}
        mock_response.raise_for_status = MagicMock()

        with patch("npu_routes.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            client = TestClient(_make_app())
            resp = client.post(
                "/npu/transcribe",
                files={"file": ("recording.wav", audio_bytes, "audio/wav")},
                data={"language": "hu"},
            )
        return resp

    def test_transcribe_success(self):
        resp = self._transcribe(mock_text="Helló világ")
        assert resp.status_code == 200
        assert resp.json()["text"] == "Helló világ"

    def test_transcribe_backend_field(self):
        resp = self._transcribe(mock_text="teszt")
        assert resp.json()["backend"] == "nexa-parakeet"

    def test_transcribe_503_when_nexa_offline(self):
        with patch("npu_routes._transcribe_nexa", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
            client = TestClient(_make_app())
            resp = client.post(
                "/npu/transcribe",
                files={"file": ("recording.wav", b"fake", "audio/wav")},
                data={"language": "hu"},
            )
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["error"] == "nexa_offline"

    def test_transcribe_empty_audio_accepted(self):
        resp = self._transcribe(mock_text="szöveg", audio_bytes=b"\x00" * 100)
        assert resp.status_code == 200


# ── /npu/nexa/services ────────────────────────────────────────────────────────

class TestNexaServices:
    def test_services_status(self):
        mock_status = {
            "asr":        {"label": "Parakeet ASR", "model": "NexaAI/parakeet-tdt-0.6b-v3-npu", "port": 18181, "managed": False, "online": False},
            "llm":        {"label": "Qwen3-8B LLM",  "model": "NexaAI/Qwen3-8B-NPU",            "port": 18182, "managed": False, "online": False},
            "multimodal": {"label": "OmniNeural-4B",  "model": "NexaAI/OmniNeural-4B",           "port": 18183, "managed": False, "online": False},
        }
        with patch("npu_routes._nexa_status_all", new_callable=AsyncMock, return_value=mock_status), \
             patch("npu_routes._nexa_manager_ok", True):
            client = TestClient(_make_app())
            resp = client.get("/npu/nexa/services")
        assert resp.status_code == 200
        data = resp.json()
        assert "asr" in data
        assert "llm" in data
        assert "multimodal" in data

    def test_start_service_success(self):
        with patch("npu_routes._nexa_start", return_value={"ok": True, "pid": 12345, "message": "'asr' indítva (PID 12345)"}), \
             patch("npu_routes._nexa_manager_ok", True):
            client = TestClient(_make_app())
            resp = client.post("/npu/nexa/services/asr/start")
        assert resp.status_code == 200
        assert resp.json()["pid"] == 12345

    def test_start_service_unknown_returns_400(self):
        with patch("npu_routes._nexa_start", return_value={"ok": False, "pid": None, "message": "Ismeretlen szolgáltatás: 'xyz'"}), \
             patch("npu_routes._nexa_manager_ok", True):
            client = TestClient(_make_app())
            resp = client.post("/npu/nexa/services/xyz/start")
        assert resp.status_code == 400

    def test_stop_service(self):
        with patch("npu_routes._nexa_stop", return_value={"ok": True, "message": "'asr' leállítva"}), \
             patch("npu_routes._nexa_manager_ok", True):
            client = TestClient(_make_app())
            resp = client.post("/npu/nexa/services/asr/stop")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── /npu/omnineural/audio-summary ─────────────────────────────────────────────

class TestOmniNeuralAudioSummary:
    SAMPLE_TEXT = (
        "RÉSZTVEVŐK: Kovács J., Tóth A.\n"
        "ÖSSZEFOGLALÓ: Sprint planning meeting.\n"
        "HATÁRIDŐK: 2026-05-01\n"
        "DÖNTÉSEK: FastAPI marad.\n"
        "TEENDŐK: Deploy befejezése\n"
        "KÖVETKEZŐ LÉPÉSEK: Következő sprint\n"
    )

    def _call(self, resp_text=None, connect_error=False):
        if connect_error:
            with patch("npu_routes.httpx.AsyncClient") as mock_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
                mock_cls.return_value = mock_client
                client = TestClient(_make_app())
                return client.post(
                    "/npu/omnineural/audio-summary",
                    files={"file": ("test.wav", b"fake_wav", "audio/wav")},
                    data={"language": "hu"},
                )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": resp_text or self.SAMPLE_TEXT}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("npu_routes.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            client = TestClient(_make_app())
            return client.post(
                "/npu/omnineural/audio-summary",
                files={"file": ("test.wav", b"fake_wav", "audio/wav")},
                data={"language": "hu"},
            )

    def test_success_returns_summary(self):
        resp = self._call()
        assert resp.status_code == 200
        data = resp.json()
        assert "MeetingName" in data or "People" in data

    def test_offline_returns_503(self):
        resp = self._call(connect_error=True)
        assert resp.status_code == 503
        assert resp.json()["detail"]["error"] == "omnineural_offline"

    def test_people_extracted(self):
        resp = self._call()
        assert resp.status_code == 200
        people_blocks = resp.json().get("People", {}).get("blocks", [])
        content = " ".join(b["content"] for b in people_blocks)
        assert "Kovács" in content or "Tóth" in content
