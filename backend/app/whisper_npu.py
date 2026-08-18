"""
whisper_npu.py — Meetily Snapdragon
Whisper ASR két backenddel:

  1. qnn  (ALAPÉRTELMEZETT) — GenieX-stack Whisper-Base QNN
     qualcomm/Whisper-Base PRECOMPILED_QNN_ONNX (Snapdragon X Elite), futtatva
     onnxruntime-qnn + QNNExecutionProvider (htp = Hexagon NPU). Multilingual,
     magyarul is transkripál (language="hu"). Encoder ~49 ms, decoder ~3.5 ms NPU-n.
     Forrás: arm64-voice-npu skill (references/whisper-npu.md).

  2. cpp  — whisper.cpp ARM64 binary (whisper-cli.exe). Hibrid fallback.

DEVICE GUARD MEGJEGYZÉS:
  Az ARM64 Python C-extension DLL-ek (numpy, onnxruntime, librosa) BLOKKOLVA lehetnek
  Device Guard alatt. A numpy/onnxruntime traceback-öt Python import-rendszere írja
  stderr-re, mielőtt az exception eléri a mi try/except blokkjainkat. Ezért
  _stderr_suppressor()-ral fogjuk el import alatt (egyszer, app indulásnál, nem
  kérésenként). Megjegyzés: a windows-arm64-python skill szerint a "Device Guard"
  blokk gyakran valójában venv-shadowing (a Hermes venv szivárog a projekt .venv-ébe);
  tiszta, Hermes-python-3.11-gyel készített .venv + PYTHONPATH="" telepítéssel az
  onnxruntime-qnn betölthető.
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

# ── Backend választás ─────────────────────────────────────────────────────────
# "qnn"  = GenieX-stack Whisper-Base QNN (onnxruntime-qnn, Hexagon NPU)  [default]
# "cpp"  = whisper.cpp (whisper-cli.exe)
BACKEND = os.getenv("WHISPER_NPU_BACKEND", "qnn").lower()

# ── whisper.cpp (cpp backend) ─────────────────────────────────────────────────
CPP_EXE   = os.getenv("WHISPER_CPP_EXE",   "whisper-cli.exe")
CPP_MODEL = os.getenv("WHISPER_CPP_MODEL",  "models/ggml-base.bin")

# ── GenieX-stack Whisper-Base QNN (qnn backend) ───────────────────────────────
# qualcomm/Whisper-Base PRECOMPILED_QNN_ONNX (Snapdragon X Elite zip):
#   https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/models/whisper_base/...
#   whisper_base-precompiled_qnn_onnx-float-qualcomm_snapdragon_x_elite.zip
# Kicsomagolva: encoder.onnx, decoder.onnx + a multilingual tokenizer.json
# (openai/whisper-base tokenizer.json).
QNN_ENC_PATH = os.getenv("WHISPER_QNN_ENCODER",
                         r"E:\models-whisper\whisper_base\encoder.onnx")
QNN_DEC_PATH = os.getenv("WHISPER_QNN_DECODER",
                         r"E:\models-whisper\whisper_base\decoder.onnx")
QNN_TOK_PATH = os.getenv("WHISPER_QNN_TOKENIZER",
                         r"E:\models-whisper\whisper_base\tokenizer.json")
# Opcionális I/O név-felülírások — a letöltött bundle eltérő node-neveihez.
# Üresen hagyva a kód a session input/output nevei alapján detektál.
QNN_ENC_IN   = os.getenv("WHISPER_QNN_ENC_IN",   "")
QNN_ENC_OUT  = os.getenv("WHISPER_QNN_ENC_OUT",  "")
QNN_DEC_IN_T = os.getenv("WHISPER_QNN_DEC_IN_T", "")
QNN_DEC_IN_E = os.getenv("WHISPER_QNN_DEC_IN_E", "")
QNN_DEC_OUT  = os.getenv("WHISPER_QNN_DEC_OUT",  "")

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


# ── Audio segédek ─────────────────────────────────────────────────────────────

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


def _ensure_wav_16k_mono(audio_bytes: bytes) -> str:
    """WAV (16kHz mono) fájlútvonalat ad vissza; szükség esetén ffmpeg konvertálással."""
    src = _bytes_to_audio_file(audio_bytes)
    if src.endswith(".wav"):
        return src
    conv = _convert_to_wav(src)
    if conv:
        return conv
    # nincs ffmpeg → a librosa úgyis újratölti a megfelelő sr-rel; visszaadjuk az eredetit
    return src


# ── whisper.cpp backend ───────────────────────────────────────────────────────

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


# ── GenieX-stack Whisper-Base QNN backend ─────────────────────────────────────

def _load_qnn_sessions():
    """
    Betölti az encoder/decoder ONNX session-öket QNNExecutionProvider (htp) alatt.
    Visszaad: (encoder_sess, decoder_sess, enc_io, dec_io)
      enc_io = (in_name, out_name)
      dec_io = (tokens_in_name, encoder_in_name, logits_out_name)
    RuntimeError-ot dob, ha az onnxruntime/QNN EP, a modellfájl vagy az I/O nevek
    nem érhetők el.
    """
    ort_res = _try_import_onnxruntime()
    if not ort_res["available"]:
        raise RuntimeError(
            "onnxruntime nem tölthető be"
            + (f" (Device Guard? {ort_res['error']})" if ort_res["error"] else "")
            + " — telepítsd: pip install onnxruntime-qnn (Windows ARM64, Python 3.11)"
        )
    import onnxruntime as ort

    if not ort_res["qnn_ep"]:
        raise RuntimeError(
            "QNNExecutionProvider nem elérhető az onnxruntime-ben "
            "(szükséges: onnxruntime-qnn Windows ARM64 + Hexagon driver)"
        )

    enc_path, dec_path = Path(QNN_ENC_PATH), Path(QNN_DEC_PATH)
    if not enc_path.exists() or not dec_path.exists():
        raise RuntimeError(
            f"Whisper-Base QNN modellfájl hiányzik: {enc_path} / {dec_path}. "
            "Töltsd le a qualcomm/Whisper-Base PRECOMPILED_QNN_ONNX (Snapdragon X Elite) zip-et, "
            "csomagold ki, és állítsd be WHISPER_QNN_ENCODER / WHISPER_QNN_DECODER env változókat."
        )

    providers = [("QNNExecutionProvider", {"backend_type": "htp"})]
    enc_sess = ort.InferenceSession(str(enc_path), providers=providers)
    dec_sess = ort.InferenceSession(str(dec_path), providers=providers)

    # Encoder I/O nevek (detektálás vagy env-felülírás)
    enc_in = QNN_ENC_IN or enc_sess.get_inputs()[0].name
    enc_out = QNN_ENC_OUT or enc_sess.get_outputs()[0].name

    # Decoder I/O nevek: tokens vs encoder_embeddings vs (opcionális) past
    dec_inputs = dec_sess.get_inputs()
    tok_in = None
    enc_in_name = None
    for inp in dec_inputs:
        n = inp.name.lower()
        if "token" in n or "input_id" in n:
            tok_in = inp.name
        elif "encoder" in n or "embedding" in n or "hidden" in n or "cross" in n:
            enc_in_name = inp.name
    # ha a detektálás nem sikerült, az első két inputot használjuk (token, encoder)
    if tok_in is None or enc_in_name is None:
        if len(dec_inputs) >= 2:
            tok_in, enc_in_name = dec_inputs[0].name, dec_inputs[1].name
        else:
            raise RuntimeError(
                "Nem sikerült detektálni a decoder input neveit. Állítsd be "
                "WHISPER_QNN_DEC_IN_T / WHISPER_QNN_DEC_IN_E env változókat. "
                f"Decoder inputs: {[i.name for i in dec_inputs]}"
            )
    logits_out = QNN_DEC_OUT or dec_sess.get_outputs()[0].name

    return enc_sess, dec_sess, (enc_in, enc_out), (tok_in, enc_in_name, logits_out)


def _load_whisper_tokenizer():
    """
    Betölti a multilingual whisper-base tokenizer.json-t (openai/whisper-base).
    Visszaad: (tokenizers.Tokenizer, special_token_ids dict)
    """
    tok_path = Path(QNN_TOK_PATH)
    if not tok_path.exists():
        raise RuntimeError(
            f"Whisper tokenizer.json hiányzik: {tok_path}. "
            "Töltsd le az openai/whisper-base tokenizer.json-t, és állítsd be "
            "WHISPER_QNN_TOKENIZER env változót."
        )
    try:
        from tokenizers import Tokenizer
    except ImportError:
        raise RuntimeError(
            "A 'tokenizers' csomag szükséges a Whisper-Base QNN dekódolásához — "
            "telepítsd: pip install tokenizers"
        )
    tok = Tokenizer.from_file(str(tok_path))

    def tid(s):
        return tok.token_to_id(s)

    # Ismert Whisper special token id-k (fallback, ha a tokenizer.json nem tartalmazza)
    ids = {
        "sot":          tid("<|startoftranscript|>") or 50258,
        "transcribe":   tid("<|transcribe|>")         or 50259,
        "no_timestamps":tid("<|notimestamps|>")        or 50261,
        "eot":          tid("<|endoftext|>")          or 50257,
        "lang_hu":      tid("<|hu|>")                  or 50299,
    }
    if None in ids.values():
        raise RuntimeError("Whisper special token id-k nem találhatók a tokenizer.json-ben.")
    return tok, ids


def _compute_log_mel(wav_path: str) -> "np.ndarray":
    """Log-mel spectrogram Whisper-előkezeléssel (librosa). Vissza: (1, 80, 3000) float32."""
    try:
        import librosa
        import numpy as np
    except ImportError:
        raise RuntimeError(
            "A 'librosa' csomag szükséges a Whisper-Base QNN feature extraction-höz — "
            "telepítsd: pip install librosa (numpy 1.26.4+ szükséges)"
        )
    y, _ = librosa.load(wav_path, sr=16000, mono=True)
    mel = librosa.feature.melspectrogram(
        y=y, sr=16000, n_fft=400, hop_length=160, win_length=400, window="hann",
        n_mels=80, fmin=0.0, fmax=8000.0, power=2.0, center=True,
        pad_mode="reflect", norm=None, htk=False,
    )
    log_mel = np.log10(np.clip(mel, a_min=1e-10, a_max=None))
    # Whisper normalizálás: klónozás a frame-max - 8.0 alá, majd (x+4.2677393)/4.5689974
    log_mel = np.maximum(log_mel, log_mel.max(axis=-1, keepdims=True) - 8.0)
    log_mel = (log_mel + 4.2677393) / 4.5689974
    # (80, T) → rögzített 3000 frame (pad/truncate)
    T = log_mel.shape[-1]
    if T > 3000:
        log_mel = log_mel[:, :3000]
    elif T < 3000:
        log_mel = np.pad(log_mel, ((0, 0), (0, 3000 - T)), constant_values=0.0)
    return log_mel[np.newaxis, ...].astype(np.float32)  # (1, 80, 3000)


def _transcribe_onnx(audio_bytes: bytes, language: str) -> str:
    """
    Szinkron Whisper-Base QNN átírás (onnxruntime-qnn, Hexagon NPU).
    Standard Whisper decode loop: encoder → greedy decoder magyar forced token-okkal.
    """
    import numpy as np

    enc_sess, dec_sess, enc_io, dec_io = _load_qnn_sessions()
    tok, ids = _load_whisper_tokenizer()
    enc_in, enc_out = enc_io
    tok_in, enc_in_name, logits_out = dec_io

    wav_path = _ensure_wav_16k_mono(audio_bytes)
    tmp_files = [wav_path] if not wav_path.endswith(".wav") else []
    try:
        features = _compute_log_mel(wav_path)

        enc_out_val = enc_sess.run([enc_out], {enc_in: features})[0]

        # Forced decoder token-ok: <|startoftranscript|> <|hu|> <|transcribe|> <|notimestamps|>
        tokens = [ids["sot"], ids["lang_hu"], ids["transcribe"], ids["no_timestamps"]]
        generated: list[int] = []

        # Greedy decode (Whisper-Base kicsi → KV-cache nélkül is gyors NPU-n)
        for _ in range(448):
            logits = dec_sess.run(
                [logits_out],
                {tok_in: np.array([tokens], dtype=np.int64), enc_in_name: enc_out_val},
            )[0]
            next_id = int(np.argmax(logits[0, -1]))
            if next_id == ids["eot"]:
                break
            tokens.append(next_id)
            generated.append(next_id)

        text = tok.decode(generated).strip()
        if not text:
            raise ValueError("Whisper-Base QNN üres átírást adott (valószínűleg csend).")
        return text
    finally:
        for f in tmp_files:
            Path(f).unlink(missing_ok=True)


async def transcribe_qnn(audio_bytes: bytes, language: str = DEFAULT_LANG, filename: str = "recording.webm") -> str:
    """Async wrapper — GenieX-stack Whisper-Base QNN (Hexagon NPU)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _transcribe_onnx, audio_bytes, language)


async def transcribe_npu(audio_bytes: bytes, language: str = DEFAULT_LANG, filename: str = "recording.webm") -> str:
    """
    Async wrapper — backend kiválasztása WHISPER_NPU_BACKEND alapján
    ("qnn" = GenieX-stack Whisper-Base QNN [default], "cpp" = whisper.cpp).
    """
    if BACKEND == "cpp":
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _transcribe_cpp, audio_bytes, language)
    return await transcribe_qnn(audio_bytes, language, filename)


def is_npu_available() -> dict:
    """
    Hardver + függőség állapot összefoglaló.
    onnxruntime import EGYSZER próbálkozik és cacheeli az eredményt.
    Device Guard esetén: csak debug log, nem spam.
    """
    ort_info = _try_import_onnxruntime()
    qnn_ready = (
        ort_info["available"] and ort_info["qnn_ep"]
        and Path(QNN_ENC_PATH).exists() and Path(QNN_DEC_PATH).exists()
        and Path(QNN_TOK_PATH).exists()
    )
    return {
        "backend":               BACKEND,
        "cpp_exe_found":         Path(CPP_EXE).exists()   if BACKEND == "cpp"  else None,
        "cpp_model_found":       Path(CPP_MODEL).exists()  if BACKEND == "cpp"  else None,
        "qnn_encoder_found":     Path(QNN_ENC_PATH).exists(),
        "qnn_decoder_found":     Path(QNN_DEC_PATH).exists(),
        "qnn_tokenizer_found":   Path(QNN_TOK_PATH).exists(),
        "qnn_model_path":        str(QNN_ENC_PATH),
        "parakeet_model_found":  Path(PARAKEET_MODEL_PATH).exists(),
        "parakeet_model_path":   PARAKEET_MODEL_PATH,
        "onnxruntime_available": ort_info["available"],
        "qnn_ep_available":      ort_info["qnn_ep"],
        "qnn_ready":             qnn_ready,
        "available_providers":   ort_info["providers"],
        "device_guard_active":   ort_info.get("error") == "device_guard",
        "genie_api_url":         os.getenv("GENIE_BASE_URL", "http://127.0.0.1:18181/v1"),
    }
