"""
whisper_npu.py — Meetily Snapdragon
Whisper ASR: whisper.cpp ARM64 binary (cpp backend, default)
             ONNX Runtime + QNN EP (onnx backend, Device Guard blokkolja ARM64-en)

DEVICE GUARD MEGJEGYZÉS:
  Az ARM64 Python C-extension DLL-ek (numpy, onnxruntime) BLOKKOLVA vannak.
  A numpy traceback-et Python import-rendszere írja stderr-re, mielőtt az
  exception eléri a mi try/except blokkokat. Ezért _stderr_suppressor()-ral
  fogjuk el import alatt – ez egyszer fut app indulásnál, nem kérésenként.
"""
import asyncio
import contextlib
import io
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND     = os.getenv("WHISPER_NPU_BACKEND", "cpp").lower()
CPP_EXE     = os.getenv("WHISPER_CPP_EXE",   "whisper-cli.exe")
CPP_MODEL   = os.getenv("WHISPER_CPP_MODEL",  "models/ggml-base.bin")
ONNX_MODEL  = os.getenv("WHISPER_ONNX_MODEL", "models/whisper-base.onnx")
PARAKEET_MODEL_PATH = os.getenv(
    "PARAKEET_MODEL_PATH",
    r"E:\models-nexa\models\NexaAI\parakeet-tdt-0.6b-v3-npu"
)
DEFAULT_LANG = os.getenv("WHISPER_LANGUAGE", "hu")

# ── Cachelés: csak egyszer próbálja importálni ─────────────────────────────
_ONNXRT_RESULT: dict | None = None  # None = nem próbálta még


@contextlib.contextmanager
def _stderr_suppressor():
    """Elfojtja Python stderr kimenetét – numpy DLL traceback elnyeléséhez."""
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stderr = old_stderr


def _try_import_onnxruntime() -> dict:
    """
    Megpróbálja importálni az onnxruntime-ot.
    stderr elfojtva → numpy ARM64 DLL traceback NEM jelenik meg a logban.
    Eredmény cachelve – csak egyszer fut le.
    """
    global _ONNXRT_RESULT
    if _ONNXRT_RESULT is not None:
        return _ONNXRT_RESULT

    result = {"available": False, "qnn_ep": False, "providers": [], "error": None}
    try:
        with _stderr_suppressor():
            import onnxruntime as ort
        result["available"] = True
        eps = [p[0] for p in ort.get_available_providers()]
        result["providers"] = eps
        result["qnn_ep"] = "QNNExecutionProvider" in eps
        logger.info(f"[whisper_npu] onnxruntime OK, providers: {eps}")
    except Exception as e:
        err = str(e)
        if "házirend" in err or "policy" in err.lower() or "DLL load" in err:
            result["error"] = "device_guard"
            logger.debug("[whisper_npu] onnxruntime: Device Guard blokkolja (ARM64 DLL)")
        else:
            result["error"] = err[:120]
            logger.debug(f"[whisper_npu] onnxruntime import sikertelen: {err[:80]}")

    _ONNXRT_RESULT = result
    return result


def _detect_audio_ext(audio_bytes: bytes) -> str:
    if audio_bytes[:4] == b'RIFF':
        return ".wav"
    if len(audio_bytes) > 4 and audio_bytes[4:8] == b'ftyp':
        return ".m4a"
    if audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
        return ".mp3"
    if audio_bytes[:4] == b'\x1aE\xdf\xa3':
        return ".webm"
    return ".webm"


def _bytes_to_audio_file(audio_bytes: bytes) -> str:
    ext = _detect_audio_ext(audio_bytes)
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(audio_bytes)
    tmp.close()
    return tmp.name


def _convert_to_wav(src_path: str) -> str | None:
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    dst_path = src_path.rsplit(".", 1)[0] + "_conv.wav"
    r = subprocess.run(
        [ffmpeg, "-y", "-i", src_path, "-ar", "16000", "-ac", "1", "-f", "wav", dst_path],
        capture_output=True, timeout=60,
    )
    return dst_path if r.returncode == 0 and Path(dst_path).exists() else None


def _transcribe_cpp(audio_bytes: bytes, language: str) -> str:
    """whisper.cpp CLI-vel végez átírást."""
    if not Path(CPP_EXE).exists():
        raise FileNotFoundError(
            f"whisper-cli.exe nem található: {CPP_EXE}\n"
            "Töltsd le: https://github.com/ggml-org/whisper.cpp/releases (ARM64)\n"
            "Majd állítsd be a WHISPER_CPP_EXE env változót."
        )
    if not Path(CPP_MODEL).exists():
        raise FileNotFoundError(
            f"Whisper modell nem található: {CPP_MODEL}\n"
            "Töltsd le: https://huggingface.co/ggerganov/whisper.cpp\n"
            "Majd állítsd be a WHISPER_CPP_MODEL env változót."
        )

    src = _bytes_to_audio_file(audio_bytes)
    wav = (_convert_to_wav(src) or src) if not src.endswith(".wav") else src
    tmp_files = list({src, wav})

    try:
        cmd = [CPP_EXE, "-m", CPP_MODEL, "-f", wav,
               "--language", language, "--no-timestamps", "-otxt"]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=180, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            raise RuntimeError(f"whisper-cli hiba (kód {result.returncode}): {result.stderr[:300]}")
        txt_path = wav + ".txt"
        if Path(txt_path).exists():
            t = Path(txt_path).read_text(encoding="utf-8", errors="replace").strip()
            Path(txt_path).unlink(missing_ok=True)
            return t
        return result.stdout.strip()
    finally:
        for f in tmp_files:
            Path(f).unlink(missing_ok=True)


async def transcribe_npu(audio_bytes: bytes, language: str = DEFAULT_LANG) -> str:
    """Hangfájl átírása whisper.cpp-vel (async wrapper)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_cpp, audio_bytes, language)


def is_npu_available() -> dict:
    """
    Hardver + függőség állapot összefoglaló.
    onnxruntime import EGYSZER próbálkozik és cacheeli az eredményt.
    Device Guard esetén: csak debug log, nem spam.
    """
    ort_info = _try_import_onnxruntime()
    return {
        "backend":              BACKEND,
        "cpp_exe_found":        Path(CPP_EXE).exists()   if BACKEND == "cpp"  else None,
        "cpp_model_found":      Path(CPP_MODEL).exists()  if BACKEND == "cpp"  else None,
        "onnx_model_found":     Path(ONNX_MODEL).exists() if BACKEND == "onnx" else None,
        "parakeet_model_found": Path(PARAKEET_MODEL_PATH).exists(),
        "parakeet_model_path":  PARAKEET_MODEL_PATH,
        "onnxruntime_available": ort_info["available"],
        "qnn_ep_available":     ort_info["qnn_ep"],
        "available_providers":  ort_info["providers"],
        "device_guard_active":  ort_info.get("error") == "device_guard",
        "genie_api_url":        os.getenv("GENIE_BASE_URL", "http://127.0.0.1:8912/v1"),
    }
