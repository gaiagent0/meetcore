"""
rag_service.py — MeetCore v3
BM25 keresés meeting összefoglalók felett (SQLite, nincs külső vektoros függőség).
Opcionálisan ChromaDB + sentence-transformers dense embedding, ha telepítve.
"""
import json
import logging
import re
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

# ── BM25 ─────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    avg_doc_len: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    dl = len(doc_tokens)
    if dl == 0:
        return 0.0
    freq = Counter(doc_tokens)
    score = 0.0
    for qt in query_tokens:
        tf = freq.get(qt, 0)
        if tf == 0:
            continue
        score += (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_doc_len))
    return score


# ── Meeting szöveg kinyerés ───────────────────────────────────────────────────

def _summary_to_text(summary: dict | str) -> str:
    """SummaryResponse dict → kereshető plain text."""
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except Exception:
            return summary
    if not isinstance(summary, dict):
        return ""
    parts = [summary.get("MeetingName", "")]
    for field in ("SessionSummary", "People", "CriticalDeadlines",
                  "KeyItemsDecisions", "ImmediateActionItems", "NextSteps"):
        section = summary.get(field, {})
        if isinstance(section, dict):
            for b in section.get("blocks", []):
                if isinstance(b, dict):
                    parts.append(b.get("content", ""))
    notes = summary.get("MeetingNotes")
    if isinstance(notes, dict):
        for s in notes.get("sections", []):
            if isinstance(s, dict):
                for b in s.get("blocks", []):
                    if isinstance(b, dict):
                        parts.append(b.get("content", ""))
    return " ".join(p for p in parts if p)


def _meeting_text(meeting: dict) -> str:
    """Meeting dict → kereshető szöveg (summary + transcript + title)."""
    parts = [meeting.get("title", "")]
    summary = meeting.get("summary") or {}
    parts.append(_summary_to_text(summary))
    transcript = meeting.get("transcript") or ""
    parts.append(transcript[:2000])  # BM25-höz csak az első 2000 kar
    return " ".join(p for p in parts if p)


# ── Fő API ────────────────────────────────────────────────────────────────────

async def search_meetings(db, query: str, limit: int = 5) -> list[dict]:
    """
    BM25 keresés az összes meeting felett.
    Visszaad max `limit` találatot relevancia szerint rendezve.
    db: DatabaseManager példány
    """
    meetings = await db.get_all_meetings()
    if not meetings:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return meetings[:limit]

    doc_token_lists = [_tokenize(_meeting_text(m)) for m in meetings]
    avg_len = sum(len(d) for d in doc_token_lists) / max(len(doc_token_lists), 1)

    scored = [
        (_bm25_score(query_tokens, dt, avg_len), m)
        for dt, m in zip(doc_token_lists, meetings)
    ]
    scored.sort(key=lambda x: -x[0])
    return [m for score, m in scored[:limit] if score > 0] or meetings[:limit]


async def get_meeting_context(db, meeting_id: str) -> str:
    """
    Chat kontextus összeállítása egy meetinghez.
    Visszaad strukturált szöveget: összefoglaló főbb részei + átírás eleje.
    """
    meeting = await db.get_meeting(meeting_id)
    if not meeting:
        return ""

    parts: list[str] = []

    summary = meeting.get("summary") or {}
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except Exception:
            summary = {}

    if isinstance(summary, dict) and summary:
        name = summary.get("MeetingName", meeting.get("title", ""))
        if name:
            parts.append(f"MEGBESZÉLÉS: {name}")

        for field, label in [
            ("People",               "RÉSZTVEVŐK"),
            ("SessionSummary",       "ÖSSZEFOGLALÓ"),
            ("CriticalDeadlines",    "HATÁRIDŐK"),
            ("KeyItemsDecisions",    "DÖNTÉSEK"),
            ("ImmediateActionItems", "TEENDŐK"),
            ("NextSteps",            "KÖVETKEZŐ LÉPÉSEK"),
        ]:
            section = summary.get(field, {})
            if isinstance(section, dict):
                blocks = section.get("blocks", [])
                if blocks:
                    items = [b.get("content", "") for b in blocks if isinstance(b, dict) and b.get("content")]
                    if items:
                        parts.append(f"{label}:\n" + "\n".join(f"- {i}" for i in items))

    transcript = meeting.get("transcript") or ""
    if transcript:
        excerpt = transcript[:2500]
        if len(transcript) > 2500:
            excerpt += "\n[... átírás folytatódik]"
        parts.append(f"ÁTÍRÁS RÉSZLET:\n{excerpt}")

    return "\n\n".join(parts)
