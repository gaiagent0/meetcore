"""
chat_routes.py — MeetCore v3
Interaktív chat meeting összefoglalóval.
POST /chat/{meeting_id}         → JSON válasz
POST /chat/{meeting_id}/stream  → SSE streaming
"""
import json
import logging
import os
import time
import uuid
from typing import AsyncGenerator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from rag_service import get_meeting_context

logger = logging.getLogger(__name__)

chat_router = APIRouter(prefix="/chat", tags=["Chat"])

DEFAULT_SYSTEM = (
    "Te egy meeting asszisztens vagy. "
    "A felhasználó kérdéseire a megadott meeting kontextus alapján válaszolj. "
    "Magyar nyelven, tömören és pontosan. Ha a kontextusban nincs válasz, azt jelezd."
)

SUPPORTED_CHAT_PROVIDERS = {"npu", "ollama", "nexa", "claude", "groq", "openai", "openrouter"}


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    provider: str = Field(default="ollama")
    model_name: str = Field(default="")
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    meeting_id: str
    provider: str
    model: str
    context_used: bool
    response_ms: int


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _call_llm(
    question: str,
    context: str,
    provider: str,
    model_name: str,
    history: list[dict],
    db=None,
) -> str:
    from transcript_processor import (
        GENIE_BASE_URL, OLLAMA_HOST, NEXA_BASE_URL,
        GENIE_MODEL, NEXA_LLM_MODEL, NEXA_TIMEOUT, OLLAMA_TIMEOUT, GENIE_TIMEOUT,
        _get_cloud_api_key,
    )

    context_block = f"\n\nMEETING KONTEXTUS:\n{context}" if context else ""
    user_content = f"{question}{context_block}"

    messages = []
    for h in history[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            messages.append({"role": h["role"], "content": str(h.get("content", ""))})
    messages.append({"role": "user", "content": user_content})

    local_cfg: dict[str, tuple] = {
        "npu":    (GENIE_BASE_URL,         "local",  model_name or GENIE_MODEL,    GENIE_TIMEOUT),
        "nexa":   (NEXA_BASE_URL,          "local",  model_name or NEXA_LLM_MODEL, NEXA_TIMEOUT),
        "ollama": (OLLAMA_HOST + "/v1",    "ollama", model_name,                   OLLAMA_TIMEOUT),
    }

    if provider in local_cfg:
        base_url, api_key, model, timeout = local_cfg[provider]
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": DEFAULT_SYSTEM}] + messages,
            "temperature": 0.4,
            "max_tokens": 1024,
        }
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # Claude — Anthropic API
    if provider == "claude":
        key = await _get_cloud_api_key("claude", db)
        if not key:
            raise ValueError("Claude API kulcs hiányzik")
        async with httpx.AsyncClient(timeout=60.0) as c:
            resp = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json={
                    "model": model_name or "claude-3-5-haiku-20241022",
                    "max_tokens": 1024,
                    "system": DEFAULT_SYSTEM,
                    "messages": messages,
                },
            )
            resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    # OpenAI-kompatibilis felhős providerek
    cloud_cfg: dict[str, tuple] = {
        "groq":       ("https://api.groq.com/openai/v1",   model_name or "llama-3.3-70b-versatile",            60.0),
        "openai":     ("https://api.openai.com/v1",        model_name or "gpt-4o-mini",                        60.0),
        "openrouter": ("https://openrouter.ai/api/v1",     model_name or "meta-llama/llama-3.3-70b-instruct",  90.0),
    }
    if provider not in cloud_cfg:
        raise ValueError(f"Ismeretlen provider: '{provider}'")

    key = await _get_cloud_api_key(provider, db)
    if not key:
        raise ValueError(f"{provider} API kulcs hiányzik")

    base_url, model, timeout = cloud_cfg[provider]
    async with httpx.AsyncClient(timeout=timeout) as c:
        resp = await c.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": DEFAULT_SYSTEM}] + messages,
                "temperature": 0.4,
                "max_tokens": 1024,
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@chat_router.post("/{meeting_id}", response_model=ChatResponse)
async def chat_with_meeting(meeting_id: str, req: ChatRequest):
    """
    Kérdés egy meeting összefoglalójáról.
    A meeting kontextusa (összefoglaló + átírás) automatikusan bekerül a promptba.
    """
    try:
        from db import DatabaseManager
        db = DatabaseManager()
    except Exception:
        db = None

    if req.provider not in SUPPORTED_CHAT_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Ismeretlen provider: '{req.provider}'")

    context = await get_meeting_context(db, meeting_id) if db else ""
    if not context and db:
        # meeting nem létezik
        meeting_check = await db.get_meeting(meeting_id) if db else None
        if not meeting_check:
            raise HTTPException(status_code=404, detail=f"Meeting '{meeting_id}' nem található")

    t0 = time.perf_counter()
    try:
        answer = await _call_llm(
            question=req.question,
            context=context,
            provider=req.provider,
            model_name=req.model_name,
            history=req.history,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[Chat] LLM hiba ({req.provider}): {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))

    elapsed = int((time.perf_counter() - t0) * 1000)
    return ChatResponse(
        answer=answer,
        meeting_id=meeting_id,
        provider=req.provider,
        model=req.model_name or req.provider,
        context_used=bool(context),
        response_ms=elapsed,
    )


@chat_router.post("/{meeting_id}/stream")
async def chat_stream(meeting_id: str, req: ChatRequest):
    """
    SSE streaming chat.
    Eseménytípusok: start | token | done | error
    """
    try:
        from db import DatabaseManager
        db = DatabaseManager()
    except Exception:
        db = None

    if req.provider not in SUPPORTED_CHAT_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Ismeretlen provider: '{req.provider}'")

    context = await get_meeting_context(db, meeting_id) if db else ""

    async def _generate() -> AsyncGenerator[str, None]:
        yield _sse("start", {"meeting_id": meeting_id, "provider": req.provider})
        try:
            answer = await _call_llm(
                question=req.question,
                context=context,
                provider=req.provider,
                model_name=req.model_name,
                history=req.history,
                db=db,
            )
            # Token-szintű streaming helyett a teljes választ küldjük egy darabban
            # (a lokális modelleknek nincs streaming interfészük ebben az implementációban)
            for i in range(0, len(answer), 20):
                yield _sse("token", {"text": answer[i:i+20]})
            yield _sse("done", {"full": answer, "meeting_id": meeting_id})
        except Exception as e:
            logger.error(f"[ChatStream] {e}")
            yield _sse("error", {"detail": str(e)[:300]})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
