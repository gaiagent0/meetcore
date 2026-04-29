"""
nexa_manager.py — MeetCore v3
NexaAI szerver processzek kezelése: start/stop/status.

Három kezelt szolgáltatás:
  asr        — parakeet-tdt-0.6b-v3-npu (:18181)
  llm        — Qwen3-8B-NPU (:18182)
  multimodal — OmniNeural-4B (:18183)
"""
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SERVICES: dict[str, dict] = {
    "asr": {
        "model": os.getenv("NEXA_ASR_MODEL", "NexaAI/parakeet-tdt-0.6b-v3-npu"),
        "port":  int(os.getenv("NEXA_ASR_PORT", "18181")),
        "label": "Parakeet ASR",
    },
    "llm": {
        "model": os.getenv("NEXA_LLM_MODEL", "NexaAI/Qwen3-8B-NPU"),
        "port":  int(os.getenv("NEXA_LLM_PORT", "18182")),
        "label": "Qwen3-8B LLM",
    },
    "multimodal": {
        "model": os.getenv("OMNINEURAL_MODEL", "NexaAI/OmniNeural-4B"),
        "port":  int(os.getenv("NEXA_MULTIMODAL_PORT", "18183")),
        "label": "OmniNeural-4B",
    },
}

_processes: dict[str, subprocess.Popen] = {}


def _find_nexa() -> Optional[str]:
    """nexa CLI keresés: PATH → Windows-specifikus helyek → None."""
    found = shutil.which("nexa")
    if found:
        return found

    if sys.platform == "win32":
        candidates: list[Path] = []
        for base_env in ("LOCALAPPDATA", "APPDATA", "USERPROFILE"):
            base = os.environ.get(base_env, "")
            if base:
                candidates += [
                    Path(base) / "Programs" / "Python" / "Scripts" / "nexa.exe",
                    Path(base) / "Python" / "Scripts" / "nexa.exe",
                    Path(base) / ".local" / "bin" / "nexa.exe",
                ]
        for pyver in ("Python312", "Python311", "Python310", "Python313"):
            candidates.append(Path(f"C:/{pyver}/Scripts/nexa.exe"))
        for c in candidates:
            if c.exists():
                return str(c)
    else:
        for prefix in ("/usr/local/bin", "/usr/bin", str(Path.home() / ".local/bin")):
            p = Path(prefix) / "nexa"
            if p.exists():
                return str(p)

    return None


async def _check_port_health(port: int, timeout: float = 3.0) -> bool:
    """HTTP /v1/models health check az adott porton."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"http://127.0.0.1:{port}/v1/models")
            return r.status_code < 500
    except Exception:
        return False


async def status_all() -> dict:
    """
    Minden szolgáltatás státusza.
    managed: általunk indított és még fut
    online: HTTP health check alapján (akárhogy indult)
    """
    results = {}
    for name, cfg in SERVICES.items():
        proc = _processes.get(name)
        managed = proc is not None and proc.poll() is None
        online = await _check_port_health(cfg["port"])
        results[name] = {
            "label":   cfg["label"],
            "model":   cfg["model"],
            "port":    cfg["port"],
            "managed": managed,
            "online":  online,
        }
    return results


def start_service(name: str, datadir: str | None = None) -> dict:
    """
    Nexa szerver indítása háttérben subprocessként.
    Visszatér: {"ok": bool, "pid": int|None, "message": str}
    """
    if name not in SERVICES:
        return {"ok": False, "pid": None, "message": f"Ismeretlen szolgáltatás: '{name}'"}

    cfg = SERVICES[name]

    proc = _processes.get(name)
    if proc is not None and proc.poll() is None:
        return {"ok": True, "pid": proc.pid, "message": f"'{name}' már fut (PID {proc.pid})"}

    nexa_bin = _find_nexa()
    if not nexa_bin:
        return {
            "ok": False, "pid": None,
            "message": "nexa CLI nem található. Telepítsd: pip install nexaai",
        }

    cmd = [nexa_bin, "serve", cfg["model"], "--port", str(cfg["port"])]
    logger.info(f"[NexaManager] Indítás: {' '.join(cmd)}")

    env = os.environ.copy()
    nexa_datadir = datadir or os.getenv("NEXA_DATADIR", r"E:\models-nexa")
    env["NEXA_DATADIR"] = nexa_datadir
    logger.info(f"[NexaManager] NEXA_DATADIR={nexa_datadir}")

    try:
        extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {}
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **extra)
        _processes[name] = proc
        logger.info(f"[NexaManager] '{name}' PID={proc.pid}")
        return {"ok": True, "pid": proc.pid, "message": f"'{name}' indítva (PID {proc.pid})"}
    except Exception as e:
        logger.error(f"[NexaManager] Indítási hiba ({name}): {e}")
        return {"ok": False, "pid": None, "message": str(e)}


def stop_service(name: str) -> dict:
    """
    Nexa szerver leállítása.
    Visszatér: {"ok": bool, "message": str}
    """
    if name not in SERVICES:
        return {"ok": False, "message": f"Ismeretlen szolgáltatás: '{name}'"}

    proc = _processes.pop(name, None)
    if proc is None or proc.poll() is not None:
        return {"ok": True, "message": f"'{name}' nem fut (vagy nem általunk lett indítva)"}

    try:
        proc.terminate()
        proc.wait(timeout=5)
        logger.info(f"[NexaManager] '{name}' leállítva")
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning(f"[NexaManager] '{name}' SIGKILL-el leállítva")
    except Exception as e:
        logger.error(f"[NexaManager] Stop hiba ({name}): {e}")

    return {"ok": True, "message": f"'{name}' leállítva"}
