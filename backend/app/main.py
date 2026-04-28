"""
main.py — MeetCore FastAPI backend  v2.0.0
SSE streaming + API key management.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Meetily Snapdragon API",
    version="1.4.0",
    description="Meeting összefoglaló — SSE streaming + lokális/felhős providerek",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routerek ─────────────────────────────────────────────────────────────────
try:
    from npu_routes import npu_router
    app.include_router(npu_router, prefix="/npu", tags=["NPU & Local Providers"])
    logger.info("✓ NPU router betöltve")
except ImportError as e:
    logger.warning(f"NPU routes nem elérhető: {e}")

try:
    from live_asr import live_router
    app.include_router(live_router, tags=["LiveASR"])
    logger.info("✓ LiveASR router betöltve")
except ImportError as e:
    logger.warning(f"LiveASR routes nem elérhető: {e}")

try:
    from tts_routes import tts_router
    app.include_router(tts_router)
    logger.info("✓ TTS router betöltve")
except ImportError as e:
    logger.warning(f"TTS routes nem elérhető: {e}")

try:
    from chat_routes import chat_router
    app.include_router(chat_router)
    logger.info("✓ Chat router betöltve")
except ImportError as e:
    logger.warning(f"Chat routes nem elérhető: {e}")

# ── DB ────────────────────────────────────────────────────────────────────────
try:
    from db import DatabaseManager
    db = DatabaseManager()
    logger.info("✓ SQLite DB inicializálva")
except Exception as e:
    db = None
    logger.warning(f"db.py nem elérhető: {e}")

SUPPORTED_PROVIDERS = {"npu", "ollama", "nexa", "omnineural", "claude", "groq", "openai", "openrouter"}
CLOUD_PROVIDERS     = {"claude", "groq", "openai", "openrouter"}

# ── Request modellek ──────────────────────────────────────────────────────────

class ProcessTranscriptRequest(BaseModel):
    transcript_text: str = Field(..., min_length=1)
    meeting_id:  str = Field(default="")
    title:       str = Field(default="Névtelen meeting")
    model:       str = Field(default="ollama")
    model_name:  str = Field(default="")
    chunk_size:  int = Field(default=0)
    overlap:     int = Field(default=0)
    custom_prompt: str = Field(default="")

class SaveTranscriptRequest(BaseModel):
    meeting_id: str = Field(default="")
    title:      str = Field(default="Névtelen meeting")
    transcript: str = Field(...)
    summary:    str = Field(default="")
    model:      str = Field(default="ollama")
    model_name: str = Field(default="")

class UpdateSummaryRequest(BaseModel):
    meeting_id: str
    summary: dict = Field(...)


# ── SSE segédfüggvény ─────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    """Formáz egy SSE üzenetet."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _db_setup(meeting_id: str, title: str, transcript: str,
                    provider: str, model_name: str, chunk_size: int, overlap: int):
    """DB előkészítés (meeting + process + transcript mentése)."""
    if db is None:
        return
    try:
        await db.save_meeting(meeting_id, title)
    except Exception as e:
        if "already exists" not in str(e):
            logger.warning(f"save_meeting: {e}")
    try:
        await db.create_process(meeting_id)
    except Exception as e:
        logger.warning(f"create_process: {e}")
    try:
        await db.save_transcript(
            meeting_id=meeting_id, transcript_text=transcript,
            model=provider, model_name=model_name or provider,
            chunk_size=chunk_size or 2000, overlap=overlap or 200,
        )
    except Exception as e:
        logger.warning(f"save_transcript: {e}")


async def _db_save_result(meeting_id: str, results: list, provider: str, model_name: str):
    """Összefoglaló eredmény mentése DB-be."""
    if db is None or not results:
        return
    try:
        result_obj = json.loads(results[0]) if len(results) == 1 else \
                     {"chunks": [json.loads(r) for r in results]}
        await db.update_process(
            meeting_id=meeting_id, status="COMPLETED",
            result=result_obj, chunk_count=len(results),
            metadata={"provider": provider, "model_name": model_name},
        )
    except Exception as e:
        logger.error(f"Összefoglaló mentési hiba: {e}")


def _merge_summaries(results: list) -> dict:
    """
    Több chunk összefoglalóját összevonja egyetlen SummaryResponse-ba.
    - People: az összes chunk résztvevői (deduplikálva)
    - SessionSummary: összefűzve
    - Többi szekció: az összes blokk összegyűjtve (deduplikálva)
    """
    if not results:
        return {}
    if len(results) == 1:
        try:
            return json.loads(results[0])
        except Exception:
            return {}

    parsed_list = []
    for r in results:
        try:
            parsed_list.append(json.loads(r))
        except Exception:
            continue

    if not parsed_list:
        return {}

    merged = dict(parsed_list[0])  # alap struktúra

    def _collect_blocks(field: str) -> list:
        seen = set()
        out = []
        for p in parsed_list:
            section = p.get(field, {})
            for b in (section.get("blocks") or []):
                content = b.get("content", "").strip()
                if content and content not in seen:
                    seen.add(content)
                    out.append(b)
        # Újra sorszámozzuk az id-ket
        prefix = field[0].lower()
        for i, b in enumerate(out):
            b["id"] = f"{prefix}{i+1}"
        return out

    # People merge
    people_blocks = _collect_blocks("People")
    merged["People"] = {"title": "Résztvevők", "blocks": people_blocks}

    # SessionSummary: összefűzve
    summaries = []
    for p in parsed_list:
        for b in (p.get("SessionSummary", {}).get("blocks") or []):
            c = b.get("content", "").strip()
            if c:
                summaries.append(c)
    merged["SessionSummary"] = {
        "title": "Összefoglaló",
        "blocks": ([{"id": "s1", "type": "text", "content": " ".join(summaries), "color": ""}]
                   if summaries else [])
    }

    # Többi szekció: deduplikált blokkok
    for field in ("CriticalDeadlines", "KeyItemsDecisions", "ImmediateActionItems", "NextSteps"):
        merged[field] = {
            "title": parsed_list[0].get(field, {}).get("title", field),
            "blocks": _collect_blocks(field),
        }

    # MeetingNotes: első chunk alapján
    merged["MeetingNotes"] = parsed_list[0].get("MeetingNotes", {"meeting_name": "Értekezlet", "sections": []})

    return merged


# ── SSE streaming processor ───────────────────────────────────────────────────

async def _stream_process(req: ProcessTranscriptRequest) -> AsyncGenerator[str, None]:
    """
    SSE generator: chunk-onként küld progress eseményeket.

    Eseménytípusok:
      init      – indulás, chunk szám, provider info
      chunk_start – chunk feldolgozás kezdete
      chunk_done  – chunk sikeres
      chunk_error – chunk hiba
      saving    – DB mentés folyamatban
      done      – minden kész, tartalmazza az összefoglalót
      error     – fatális hiba
    """
    from transcript_processor import TranscriptProcessor

    provider = req.model.lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        yield _sse("error", {"detail": f"Ismeretlen provider: '{provider}'"})
        return

    meeting_id = req.meeting_id.strip() or str(uuid.uuid4())
    await _db_setup(
        meeting_id, req.title, req.transcript_text,
        provider, req.model_name, req.chunk_size, req.overlap
    )

    # Chunk szám becslése (a processor belső logikájával szinkronban)
    chunk_size = 2000 if provider in ("ollama", "nexa", "npu") else 8000
    overlap    = 200  if provider in ("ollama", "nexa", "npu") else 500
    step       = max(chunk_size - overlap, 100)
    estimated_chunks = max(1, len(req.transcript_text) // step + (1 if len(req.transcript_text) % step else 0))

    yield _sse("init", {
        "meeting_id":       meeting_id,
        "provider":         provider,
        "model":            req.model_name or provider,
        "chunks_estimated": estimated_chunks,
        "transcript_chars": len(req.transcript_text),
    })

    all_results: list = []
    chunks_done = 0

    # Callback: a processor hívja vissza chunk-onként
    async def on_chunk_start(chunk_idx: int, chunks_total: int, chunk_len: int):
        yield _sse("chunk_start", {
            "chunk": chunk_idx + 1,
            "chunks_total": chunks_total,
            "chunk_chars": chunk_len,
        })

    async def on_chunk_done(chunk_idx: int, chunks_total: int, result_json: str):
        nonlocal chunks_done
        chunks_done += 1
        all_results.append(result_json)
        yield _sse("chunk_done", {
            "chunk":        chunk_idx + 1,
            "chunks_total": chunks_total,
            "chunks_done":  chunks_done,
        })

    async def on_chunk_error(chunk_idx: int, error: str):
        yield _sse("chunk_error", {
            "chunk": chunk_idx + 1,
            "error": error[:200],
        })

    # Mivel a generator nem lehet közvetlenül callback-ből yield-elni,
    # asyncio Queue-t használunk az esemény puffereléshez
    q: asyncio.Queue = asyncio.Queue()

    async def cb_chunk_start(idx, total, chars):
        await q.put(_sse("chunk_start", {"chunk": idx+1, "chunks_total": total, "chunk_chars": chars}))

    async def cb_chunk_done(idx, total, result_json):
        nonlocal chunks_done
        chunks_done += 1
        all_results.append(result_json)
        await q.put(_sse("chunk_done", {"chunk": idx+1, "chunks_total": total, "chunks_done": chunks_done}))

    async def cb_chunk_error(idx, error):
        await q.put(_sse("chunk_error", {"chunk": idx+1, "error": str(error)[:200]}))

    async def run_processor():
        """Background task: futtatja a processort és Queue-ba teszi az eseményeket."""
        try:
            processor = TranscriptProcessor(
                db=db,
                on_chunk_start=cb_chunk_start,
                on_chunk_done=cb_chunk_done,
                on_chunk_error=cb_chunk_error,
            )
            await processor.process_transcript(
                text=req.transcript_text,
                model=provider,
                model_name=req.model_name,
                chunk_size=req.chunk_size,
                overlap=req.overlap,
                custom_prompt=req.custom_prompt,
            )
        except Exception as e:
            await q.put(_sse("error", {"detail": str(e)[:300]}))
        finally:
            await q.put(None)  # Sentinel – vége

    # Processzor indítása background taskban
    task = asyncio.create_task(run_processor())

    # SSE események küldése amíg queue-ból érkeznek
    try:
        while True:
            item = await asyncio.wait_for(q.get(), timeout=350.0)
            if item is None:
                break
            yield item
    except asyncio.TimeoutError:
        yield _sse("error", {"detail": "Timeout: a processor nem válaszolt 350 másodpercen belül"})
        task.cancel()
        return

    if not all_results:
        if db:
            try: await db.update_process(meeting_id, "FAILED", error="Nincs eredmény")
            except: pass
        yield _sse("error", {"detail": f"A '{provider}' provider nem adott vissza eredményt"})
        return

    # Mentés
    yield _sse("saving", {"meeting_id": meeting_id})
    await _db_save_result(meeting_id, all_results, provider, req.model_name)

    # Kész – elküldjük a merged összefoglalót (az összes chunk egybesítve)
    summary_parsed = _merge_summaries(all_results)

    yield _sse("done", {
        "meeting_id":   meeting_id,
        "provider":     provider,
        "model":        req.model_name or provider,
        "chunks_total": chunks_done,
        "chunks_ok":    len(all_results),
        "summary":      summary_parsed,
        "results":      all_results,
    })


# ── Végpontok ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": "1.4.0"}


@app.post("/process-transcript-stream", tags=["Summary"])
async def process_transcript_stream(req: ProcessTranscriptRequest):
    """
    SSE streaming összefoglaló generálás.
    Chunk-onként küld progress eseményeket a frontendnek.
    Content-Type: text/event-stream
    """
    return StreamingResponse(
        _stream_process(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/process-transcript", tags=["Summary"])
async def process_transcript(req: ProcessTranscriptRequest):
    """Hagyományos (nem-streaming) összefoglaló generálás. Visszafelé kompatibilis."""
    from transcript_processor import TranscriptProcessor

    provider = req.model.lower().strip()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Ismeretlen provider: '{provider}'")
    if not req.transcript_text.strip():
        raise HTTPException(status_code=400, detail="Az átírás szövege üres.")

    meeting_id = req.meeting_id.strip() or str(uuid.uuid4())
    await _db_setup(meeting_id, req.title, req.transcript_text,
                    provider, req.model_name, req.chunk_size, req.overlap)

    try:
        processor = TranscriptProcessor(db=db)
        chunks_count, results = await processor.process_transcript(
            text=req.transcript_text, model=provider, model_name=req.model_name,
            chunk_size=req.chunk_size, overlap=req.overlap, custom_prompt=req.custom_prompt,
        )
    except ValueError as e:
        if db: await db.update_process(meeting_id, "FAILED", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"process_transcript [{provider}]: {e}", exc_info=True)
        if db: await db.update_process(meeting_id, "FAILED", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    if not results:
        if db: await db.update_process(meeting_id, "FAILED", error="Nincs eredmény")
        raise HTTPException(status_code=502, detail=f"'{provider}' nem adott vissza eredményt")

    await _db_save_result(meeting_id, results, provider, req.model_name)

    return {
        "success": True, "meeting_id": meeting_id, "provider": provider,
        "model_name": req.model_name, "chunks_total": chunks_count,
        "chunks_ok": len(results), "results": results,
    }


@app.post("/save-transcript", tags=["Meetings"])
async def save_transcript(req: SaveTranscriptRequest):
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    meeting_id = req.meeting_id.strip() or str(uuid.uuid4())
    try:
        await db.save_meeting(meeting_id, req.title)
    except Exception as e:
        if "already exists" not in str(e):
            raise HTTPException(status_code=500, detail=str(e))
    try:
        await db.save_transcript(
            meeting_id=meeting_id, transcript_text=req.transcript,
            model=req.model, model_name=req.model_name or req.model,
            chunk_size=5000, overlap=1000,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    try:
        from datetime import datetime as _dt
        await db.save_meeting_transcript(
            meeting_id=meeting_id, transcript=req.transcript,
            timestamp=_dt.utcnow().isoformat(),
        )
    except Exception as e:
        logger.warning(f"save_meeting_transcript: {e}")
    if req.summary:
        try:
            sd = json.loads(req.summary) if req.summary.strip().startswith("{") else {"text": req.summary}
            await db.update_meeting_summary(meeting_id, sd)
        except Exception as e:
            logger.warning(f"summary mentés: {e}")
    return {"success": True, "meeting_id": meeting_id}


@app.get("/search-meetings", tags=["Meetings"])
async def search_meetings(q: str, limit: int = 5):
    """BM25 keresés a meeting összefoglalók felett."""
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    from rag_service import search_meetings as _search
    results = await _search(db, q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/get-meetings", tags=["Meetings"])
async def get_meetings():
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    meetings = await db.get_all_meetings()
    return {"meetings": meetings}


@app.get("/get-summary/{meeting_id}", tags=["Meetings"])
async def get_summary(meeting_id: str):
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    meeting = await db.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail=f"Meeting '{meeting_id}' nem található")
    return meeting


@app.post("/save-meeting-summary", tags=["Meetings"])
async def save_meeting_summary(req: UpdateSummaryRequest):
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    await db.update_meeting_summary(req.meeting_id, req.summary)
    return {"success": True}


@app.delete("/delete-meeting/{meeting_id}", tags=["Meetings"])
async def delete_meeting(meeting_id: str):
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    ok = await db.delete_meeting(meeting_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Meeting '{meeting_id}' nem található")
    return {"success": True, "deleted_id": meeting_id}


# ── API Key management ────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    provider: str
    api_key:  str = Field(..., min_length=1)

@app.get("/settings/api-keys", tags=["Settings"])
async def get_api_keys_status():
    """
    Returns which cloud providers have an API key configured.
    Does NOT return the actual key values.
    """
    if db is None:
        # Fall back to env vars
        return {
            "claude":      bool(os.getenv("CLAUDE_API_KEY", "")),
            "groq":        bool(os.getenv("GROQ_API_KEY", "")),
            "openai":      bool(os.getenv("OPENAI_API_KEY", "")),
            "openrouter":  bool(os.getenv("OPENROUTER_API_KEY", "")),
        }
    return await db.get_all_api_keys_status()

@app.post("/settings/api-keys", tags=["Settings"])
async def save_api_key(req: ApiKeyRequest):
    """Save an API key for a cloud provider."""
    if req.provider not in CLOUD_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Ismeretlen provider: '{req.provider}'")
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    await db.save_api_key(req.api_key.strip(), req.provider)
    return {"success": True, "provider": req.provider}

@app.delete("/settings/api-keys/{provider}", tags=["Settings"])
async def clear_api_key(provider: str):
    """Remove the API key for a cloud provider."""
    if provider not in CLOUD_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Ismeretlen provider: '{provider}'")
    if db is None:
        raise HTTPException(status_code=503, detail="Adatbázis nem elérhető")
    await db.clear_api_key(provider)
    return {"success": True, "provider": provider}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT", "5167"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
