"""
transcript_processor.py — MeetCore  v2.2
=========================================

v2.0 kétlépéses architektúra + v2.1 SSE callback + v2.2 DB-alapú API key kezelés.

ARCHITEKTÚRA:
  Lokális (ollama, nexa, npu): szöveges extrakció → Python konverzió
  Cloud (claude, groq, openai, openrouter): egylépéses JSON
    → API kulcsok: DB (settings tábla) > .env fallback

SSE CALLBACKS (v2.1):
  on_chunk_start(idx, total, chars)  – chunk feldolgozás kezdete
  on_chunk_done(idx, total, json)    – chunk sikeres
  on_chunk_error(idx, error)         – chunk hiba
"""

import asyncio
import json
import logging
import os
import re
import httpx
from typing import Callable, Awaitable, List, Literal, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()
logger = logging.getLogger(__name__)

# Callback típusok
ChunkStartCB = Optional[Callable[[int, int, int], Awaitable[None]]]
ChunkDoneCB  = Optional[Callable[[int, int, str], Awaitable[None]]]
ChunkErrorCB = Optional[Callable[[int, str], Awaitable[None]]]


def _normalize_url(raw: str, default: str) -> str:
    url = raw or default
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    url = url.replace("//0.0.0.0:", "//127.0.0.1:")
    return url.rstrip("/")


# ── Környezeti változók ──────────────────────────────────────────────────────
GENIE_BASE_URL = _normalize_url(os.getenv("GENIE_BASE_URL", ""), "http://127.0.0.1:8912/v1")
GENIE_MODEL    = os.getenv("GENIE_MODEL", "llama3.1-8b-8380-qnn2.38")
GENIE_TIMEOUT  = float(os.getenv("GENIE_TIMEOUT", "120"))

OLLAMA_HOST    = _normalize_url(os.getenv("OLLAMA_HOST", ""), "http://127.0.0.1:11434")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "600"))

NEXA_BASE_URL       = _normalize_url(os.getenv("NEXA_BASE_URL", ""), "http://127.0.0.1:18181/v1")
NEXA_TIMEOUT        = float(os.getenv("NEXA_TIMEOUT", "300"))
NEXA_LLM_MODEL      = os.getenv("NEXA_LLM_MODEL", "NexaAI/Qwen3-8B-NPU")
NEXA_MULTIMODAL_URL = _normalize_url(os.getenv("NEXA_MULTIMODAL_URL", ""), "http://127.0.0.1:18183/v1")
OMNINEURAL_MODEL    = os.getenv("OMNINEURAL_MODEL", "NexaAI/OmniNeural-4B")


CLAUDE_API_KEY     = os.getenv("CLAUDE_API_KEY", "")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


# ── Pydantic modellek ────────────────────────────────────────────────────────

class Block(BaseModel):
    id: str
    type: Literal["bullet", "heading1", "heading2", "text"]
    content: str
    color: str = ""

class Section(BaseModel):
    title: str
    blocks: List[Block]

class MeetingNotes(BaseModel):
    meeting_name: str
    sections: List[Section]

class People(BaseModel):
    title: str
    blocks: List[Block]

class SummaryResponse(BaseModel):
    MeetingName: str
    People: People
    SessionSummary: Section
    CriticalDeadlines: Section
    KeyItemsDecisions: Section
    ImmediateActionItems: Section
    NextSteps: Section
    MeetingNotes: MeetingNotes


# ── Prompt építők ────────────────────────────────────────────────────────────

def _get_model_family(model_name: str) -> str:
    """
    Modell-csalad azonosítása a prompt optimalizáláshoz.
    Kutatás alapján: minden LLM-családnak más a legjobb prompting stratégiája.
    """
    m = model_name.lower()
    if any(k in m for k in ("deepseek", "qwq")):
        return "reasoning"      # R1/QwQ: no system prompt, XML tags, temp=0.6
    if any(k in m for k in ("omnineural", "omni-neural")):
        return "omnineural"     # OmniNeural-4B: multimodális, tömör
    if any(k in m for k in ("npu", "nexa")):
        return "nexa_npu"       # Ultra-compact: every token is slow
    if any(k in m for k in ("qwen3", "qwen3.5", "qwq-plus")):
        return "qwen3"          # Qwen3: /no_think, temp=0.7 non-thinking
    if any(k in m for k in ("qwen2", "qwen-")):
        return "qwen2"          # Qwen2.5: structured, XML delimiters
    if "gemma" in m:
        return "gemma"          # Gemma: clear headers, labeled sections
    if "llama" in m:
        return "llama"          # Llama (Groq/Ollama): English sys, json keyword
    return "generic"


def _build_extraction_prompts(
    chunk: str, model_name: str = "", no_think: bool = False
) -> tuple:
    """
    Modell-specifikus prompt pár visszaadása: (system_or_None, user).

    Stratégiák:
      reasoning  – DeepSeek-R1, QwQ: nincs system prompt (ront a teljesítményen),
                   XML tag-ek, ultra-tömör utasítás, temperature=0.6
      nexa_npu   – Qwen3-8B-NPU: ultra-kompakt (minden token drága NPU-n),
                   /no_think prefix kötelező
      qwen3      – Qwen3 cloud/local: /no_think, tömör, magyar
      qwen2      – Qwen2.5: strukturált, XML delimiter, explicit szakaszok
      gemma      – Gemma4: fejléces, markdown-stílusú struktúra
      llama      – Llama 3.x: explicit szakasz-heading, tömör utasítás
      generic    – Általános fallback
    """
    family = _get_model_family(model_name)
    prefix = "/no_think\n" if no_think else ""

    if family == "reasoning":
        # ── DeepSeek-R1 / QwQ ────────────────────────────────────────────────
        # Kutatás: system prompt rontja a teljesítményt (Together AI, DeepSeek docs)
        # XML tag-ek segítik a struktúra megértését
        # Minimalista, közvetlen utasítás - a modell maga strukturálja a gondolkodást
        # temperature=0.6 ajánlott (R1 dokumentáció)
        return None, (
            "<task>Értekezlet-átirat tömör összefoglalása MAGYARUL</task>\n\n"
            "Töltsd ki ezt a 6 szakaszt az átírás alapján:\n"
            "RÉSZTVEVŐK: [nevek és szerepkörök]\n"
            "ÖSSZEFOGLALÓ: [2-3 mondat a tárgyalt témákról]\n"
            "HATÁRIDŐK: [konkrét határidők és felelősök, vagy NINCS]\n"
            "DÖNTÉSEK: [meghozott döntések, vagy NINCS]\n"
            "TEENDŐK: [ki mit csinál mikor, vagy NINCS]\n"
            "KÖVETKEZŐ LÉPÉSEK: [következő lépések, vagy NINCS]\n\n"
            f"<transcript>\n{chunk}\n</transcript>"
        )

    elif family == "nexa_npu":
        # ── NexaAI Qwen3-8B-NPU ───────────────────────────────────────────────
        # Kutatás: NPU-n minden generált token időbe kerül → ultra-tömör prompt
        # /no_think kötelező a thinking mode kikapcsolásához (Qwen3 doku)
        # max_predict=512 (a kódban) – rövid, tömör kimenetre optimalizálva
        return (
            "Meeting összefoglaló. Rövid, tömör válasz.",
            f"{prefix}Magyar összefoglaló az átírásból:\n\n"
            "RÉSZTVEVŐK:\n"
            "ÖSSZEFOGLALÓ:\n"
            "HATÁRIDŐK:\n"
            "DÖNTÉSEK:\n"
            "TEENDŐK:\n"
            "KÖVETKEZŐ LÉPÉSEK:\n\n"
            f"{chunk}"
        )

    elif family in ("qwen3", "qwen2"):
        # ── Qwen2.5 / Qwen3 lokális ───────────────────────────────────────────
        # Kutatás: Qwen modellek jól reagálnak explicit, XML-tagelt kontextusra
        # Strukturált szakaszok, egyértelmű utasítás
        # non-thinking mode esetén temperature=0.7 (Qwen3 HuggingFace doku)
        return (
            "Professzionális értekezlet-összefoglaló asszisztens vagy. "
            "Magyar nyelven dolgozol. Tömören és pontosan töltsd ki a szakaszokat.",
            f"{prefix}Összefoglald MAGYARUL az alábbi értekezlet-átírást.\n"
            "Töltsd ki mind a 6 szakaszt – ha nincs adat, írj NINCS-et:\n\n"
            "RÉSZTVEVŐK: (nevek és szerepkörök, vesszővel elválasztva)\n"
            "ÖSSZEFOGLALÓ: (2-3 mondat a tárgyalt témákról)\n"
            "HATÁRIDŐK: (konkrét határidők és felelős személyek, vagy: NINCS)\n"
            "DÖNTÉSEK: (meghozott döntések, vagy: NINCS)\n"
            "TEENDŐK: (ki mit csinál mikor, vagy: NINCS)\n"
            "KÖVETKEZŐ LÉPÉSEK: (következő feladatok/meeting, vagy: NINCS)\n\n"
            f"<átírás>\n{chunk}\n</átírás>\n\n"
            "Töltsd ki a szakaszokat!"
        )

    elif family == "gemma":
        # ── Gemma4 ───────────────────────────────────────────────────────────
        # Kutatás: Gemma modellek jól reagálnak Markdown-fejlécekre és
        # egyértelmű szekvenciális utasításokra
        return (
            "Te egy meeting összefoglaló asszisztens vagy. Magyar nyelven válaszolsz.",
            f"{prefix}## Feladat\nAz alábbi értekezlet-átírást foglald össze MAGYARUL.\n\n"
            "## Kimeneti formátum\n"
            "Töltsd ki pontosan ezt a 6 sort (ha nincs adat: NINCS):\n\n"
            "RÉSZTVEVŐK: [nevek, szerepkörök]\n"
            "ÖSSZEFOGLALÓ: [2-3 mondat]\n"
            "HATÁRIDŐK: [határidők, felelősök]\n"
            "DÖNTÉSEK: [döntések]\n"
            "TEENDŐK: [feladatok, felelősök]\n"
            "KÖVETKEZŐ LÉPÉSEK: [következő lépések]\n\n"
            f"## Átírás\n{chunk}\n\n"
            "## Összefoglaló"
        )

    elif family == "llama":
        # ── Llama 3.x (Ollama) ───────────────────────────────────────────────
        # Kutatás: Llama 3 jól reagál explicit, fejléces struktúrára
        # Tömör utasítás, egyértelmű output format
        return (
            "You are a professional meeting summarization assistant working in Hungarian.",
            f"{prefix}Summarize the following meeting transcript in HUNGARIAN.\n"
            "Fill in all 6 sections (write NINCS if no data):\n\n"
            "RÉSZTVEVŐK: [names and roles]\n"
            "ÖSSZEFOGLALÓ: [2-3 sentences about the discussion]\n"
            "HATÁRIDŐK: [deadlines and owners, or NINCS]\n"
            "DÖNTÉSEK: [decisions made, or NINCS]\n"
            "TEENDŐK: [action items with owners, or NINCS]\n"
            "KÖVETKEZŐ LÉPÉSEK: [next steps or meeting, or NINCS]\n\n"
            f"<transcript>\n{chunk}\n</transcript>"
        )

    elif family == "omnineural":
        # ── OmniNeural-4B ────────────────────────────────────────────────────
        # Multimodális modell: szöveges kontextusban is hatékony, tömör utasítás
        return (
            "Meeting összefoglaló asszisztens. Magyar nyelven, tömören.",
            f"Foglald össze MAGYARUL az alábbi meeting-átírást!\n\n"
            "RÉSZTVEVŐK:\nÖSSZEFOGLALÓ:\nHATÁRIDŐK:\nDÖNTÉSEK:\nTEENDŐK:\nKÖVETKEZŐ LÉPÉSEK:\n\n"
            f"{chunk}"
        )

    else:
        # ── Generic fallback ─────────────────────────────────────────────────
        return (
            "Professzionális értekezlet-összefoglaló asszisztens vagy. Magyar nyelven.",
            f"{prefix}Összefoglald MAGYARUL az alábbi átírást.\n\n"
            "RÉSZTVEVŐK:\nÖSSZEFOGLALÓ:\nHATÁRIDŐK:\nDÖNTÉSEK:\nTEENDŐK:\nKÖVETKEZŐ LÉPÉSEK:\n\n"
            f"{chunk}"
        )


def _build_json_prompts(
    chunk: str, model_name: str = "", custom_prompt: str = ""
) -> tuple:
    """
    Cloud provider JSON prompt pár: (system, user).
    Modell-specifikusan optimalizálva.
    """
    family = _get_model_family(model_name)
    context_line = f"\nKontextus: {custom_prompt}" if custom_prompt else ""

    if family in ("qwen3", "qwen2", "generic"):
        # ── Magyar JSON prompt (default/generic) ─────────────────────────────
        system = (
            "Te egy profi értekezlet-összefoglaló asszisztens vagy. "
            "KIZÁRÓLAG valid JSON objektumot adj vissza – semmilyen más szöveget, "
            "se magyarázatot, se markdown jelölőket, se bevezető sort."
        )
        user = (
            "Dolgozd fel MAGYARUL az alábbi értekezlet-átírást.\n"
            f"Add vissza KIZÁRÓLAG ezt a JSON struktúrát kitöltve:\n{_COMPACT_SCHEMA}\n\n"
            "Szabályok:\n"
            "• blocks=[] ha a szekció üres\n"
            "• Minden id egyedi legyen (p1,p2… s1… d1… k1… a1… n1…)\n"
            "• type értékek: text | bullet | heading1 | heading2\n"
            "• Minden tartalom MAGYARUL\n"
            f"{context_line}\n\n"
            f"<átírás>\n{chunk}\n</átírás>\n\n"
            "Csak a kitöltött JSON-t add vissza!"
        )

    elif family == "llama":
        # ── Llama (Groq llama-3.3-70b-versatile) ─────────────────────────────
        # Kutatás: Llama 3 jobban teljesít angol system prompttal
        # A "json" kulcsszó kötelező a JSON mode megbízható működéséhez (Groq doku)
        system = (
            "You are a professional meeting summarization assistant. "
            "Your task is to analyze meeting transcripts and return structured JSON summaries. "
            "Return ONLY valid JSON — no markdown code blocks, no explanation, no preamble."
        )
        user = (
            "Analyze the following meeting transcript and return a JSON summary in HUNGARIAN.\n\n"
            f"Fill this exact JSON structure:\n{_COMPACT_SCHEMA}\n\n"
            "Rules:\n"
            "- Return valid JSON only\n"
            "- blocks=[] for empty sections\n"
            "- Unique ids per section (p1,p2... s1... d1... k1... a1... n1...)\n"
            "- type values: text | bullet | heading1 | heading2\n"
            "- All content fields must be in Hungarian\n"
            f"{('- Context: ' + custom_prompt) if custom_prompt else ''}\n\n"
            f"<transcript>\n{chunk}\n</transcript>\n\n"
            "Return only the completed JSON object."
        )

    else:
        # ── OpenAI / OpenRouter / generic ─────────────────────────────────────
        system = (
            "You are a professional meeting summarization assistant. "
            "Respond ONLY with valid JSON — no markdown, no preamble, no explanation."
        )
        user = (
            f"Summarize the meeting transcript in HUNGARIAN. Fill the JSON structure:\n{_COMPACT_SCHEMA}\n\n"
            "Rules: blocks=[] if empty, unique ids, type: text|bullet|heading1|heading2, Hungarian content.\n"
            f"{('Context: ' + custom_prompt) if custom_prompt else ''}\n\n"
            f"Transcript:\n---\n{chunk}\n---\n\n"
            "Return only the JSON."
        )

    return system, user


def _build_anthropic_prompts(chunk: str, custom_prompt: str = "") -> tuple:
    """
    Claude-specifikus prompt pár XML tag-ekkel.
    Kutatás: Claude XML tag-ekkel strukturált promptokra a legjobban reagál.
    """
    system = (
        "You are an expert meeting summarization assistant. "
        "Analyze meeting transcripts and return precise structured JSON summaries in Hungarian. "
        "Return ONLY the raw JSON object — no markdown code blocks, no explanation whatsoever."
    )
    context_part = f"\n<context>{custom_prompt}</context>" if custom_prompt else ""
    user = (
        "<task>Summarize this meeting transcript and return structured JSON in Hungarian.</task>\n\n"
        f"<json_schema>\n{_COMPACT_SCHEMA}\n</json_schema>\n\n"
        "<rules>\n"
        "- blocks=[] for sections with no data\n"
        "- All block ids must be unique (p1,p2... s1... d1... k1... a1... n1...)\n"
        "- type values: text | bullet | heading1 | heading2\n"
        "- All content must be in Hungarian\n"
        "- MeetingName: concise (3-7 words)\n"
        "</rules>\n"
        f"{context_part}\n\n"
        f"<transcript>\n{chunk}\n</transcript>\n\n"
        "Return only the completed JSON object."
    )
    return system, user


# Backward-compat shim – a régi _build_extraction_prompt() hívások működjenek
def _build_extraction_prompt(chunk: str, no_think: bool = False) -> str:
    _, user = _build_extraction_prompts(chunk, model_name="generic", no_think=no_think)
    return user

# Backward-compat shim
def _build_json_prompt(chunk: str, custom_prompt: str = "") -> str:
    _, user = _build_json_prompts(chunk, model_name="qwen-generic", custom_prompt=custom_prompt)
    return user

# Legacy konstans – az _call_anthropic közvetlenül már _build_anthropic_prompts()-t hív
_SYSTEM_PROMPT_JSON = (
    "Te egy profi értekezlet-összefoglaló asszisztens vagy. "
    "CSAK valid JSON objektumot adj vissza – semmi mást."
)

_COMPACT_SCHEMA = (
    '{"MeetingName":"string","People":{"title":"Résztvevők","blocks":[{"id":"p1","type":"bullet","content":"név","color":""}]},'
    '"SessionSummary":{"title":"Összefoglaló","blocks":[{"id":"s1","type":"text","content":"összefoglaló","color":""}]},'
    '"CriticalDeadlines":{"title":"Kritikus határidők","blocks":[]},'
    '"KeyItemsDecisions":{"title":"Főbb döntések","blocks":[]},'
    '"ImmediateActionItems":{"title":"Teendők","blocks":[{"id":"a1","type":"bullet","content":"teendő","color":""}]},'
    '"NextSteps":{"title":"Következő lépések","blocks":[]},'
    '"MeetingNotes":{"meeting_name":"string","sections":[]}}'
)


# ── JSON parser ──────────────────────────────────────────────────────────────

def _repair_blocks(blocks: list) -> list:
    """
    Harom qwen-max bug-variant javitasa:
      1) Marjo: [{"id":"p1",...}]   → valtozatlan
      2) JSON-string lista: ['{"id":"p1",...}']  → json.loads minden elemre
      3) YAML-stilus lista: ["id: p1","type: bullet","content: x","color: "]
         → kulcs-ertek parak csoportositasa Block dict-te
    """
    if not blocks or isinstance(blocks[0], dict):
        return blocks  # (1) mar jo

    first = blocks[0]
    if isinstance(first, str) and first.strip().startswith("{"):
        # (2) JSON-serialized block stringek
        result = []
        for s in blocks:
            if not isinstance(s, str):
                continue
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    result.append(obj)
            except Exception:
                pass
        logger.debug(f"_repair_blocks(JSON-str): {len(blocks)} → {len(result)}")
        return result if result else blocks

    # (3) YAML-stilus: "id: p1", "type: bullet", "content: x", "color: "
    current: dict = {}
    result: list = []
    for item in blocks:
        if not isinstance(item, str):
            continue
        sep = ": " if ": " in item else (":" if ":" in item else None)
        if sep is None:
            continue
        k, _, v = item.partition(sep)
        k = k.strip().lower()
        v = v.strip()
        if k in ("id", "type", "content", "color"):
            current[k] = v
        if k == "color":  # utolso mezo → block lezarasa
            result.append({
                "id":      current.get("id",      f"r{len(result)+1}"),
                "type":    current.get("type",    "bullet"),
                "content": current.get("content", ""),
                "color":   current.get("color",   ""),
            })
            current = {}
    if current and "content" in current:
        result.append({
            "id":      current.get("id",      f"r{len(result)+1}"),
            "type":    current.get("type",    "bullet"),
            "content": current.get("content", ""),
            "color":   current.get("color",   ""),
        })
    logger.debug(f"_repair_blocks(YAML): {len(blocks)} str → {len(result)} block")
    return result if result else blocks


def _parse_raw_json(raw: str) -> dict:
    raw = raw.strip()
    if "<think>" in raw:
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        raw = "\n".join(lines).strip()
    if not raw.startswith("{"):
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
    parsed = json.loads(raw)
    # 1) Nested string → dict javitas (Qwen bug: mezo stringkent visszaadva)
    for field in ["People", "SessionSummary", "CriticalDeadlines", "KeyItemsDecisions",
                  "ImmediateActionItems", "NextSteps", "MeetingNotes"]:
        if field in parsed and isinstance(parsed[field], str):
            try:
                parsed[field] = json.loads(parsed[field])
            except Exception:
                pass
    # 2) YAML-stilus blocks string-lista → Block dict javitas (qwen-max bug)
    for field in ["People", "SessionSummary", "CriticalDeadlines", "KeyItemsDecisions",
                  "ImmediateActionItems", "NextSteps"]:
        section = parsed.get(field)
        if isinstance(section, dict) and isinstance(section.get("blocks"), list):
            section["blocks"] = _repair_blocks(section["blocks"])
    return parsed


# ── Szöveges → SummaryResponse konverzió (Python, nem LLM) ──────────────────

def _text_to_summary(extracted_text: str, chunk_index: int = 0) -> SummaryResponse:
    """
    Szoveges eksztrakciobol SummaryResponse epites.
    Robusztus section parser: lookahead regex helyett explicit hatarertelmezes.
    Megkeresi a cimkeket tobbszoros strategiaval (felso/also eset, angol fallback).
    """
    _ALL_LABELS = [
        "RESZTVEVOK", "OSSZEFOGLALO", "HATARIDK", "DONTESEK",
        "TEENDOK", "KOVETKEZO LEPESEK",
        "RESZTVEVŐK", "ÖSSZEFOGLALÓ", "HATÁRIDŐK", "DÖNTÉSEK",
        "TEENDŐK", "KÖVETKEZŐ LÉPÉSEK",
        "PARTICIPANTS", "SUMMARY", "DEADLINES", "DECISIONS",
        "ACTION ITEMS", "NEXT STEPS",
    ]

    def _find_section(label: str) -> str:
        """Megkeresi a label utani tartalmat a kovetkezo szekciocim elott."""
        text_u = extracted_text.upper()
        label_u = label.upper()

        start = text_u.find(label_u + ":")
        if start == -1:
            return ""

        content_start = start + len(label_u) + 1

        next_idx = len(extracted_text)
        for other in _ALL_LABELS:
            if other == label_u:
                continue
            pos = text_u.find(other + ":", content_start)
            if pos != -1 and pos < next_idx:
                next_idx = pos

        return extracted_text[content_start:next_idx].strip()

    _STRIP_CHARS = frozenset("-*\u2022.);:")

    def _strip_bullet(line: str) -> str:
        """Eltavolitja a sor elejerol a felsorolasjeleket — regex nelkul."""
        while line and (line[0] in _STRIP_CHARS or line[0].isdigit()):
            line = line[1:]
        return line.lstrip()

    def _parse_section(*labels) -> List[str]:
        """Probalkozik tobb cimkevel, visszaadja az elso sikeres parsolast."""
        for label in labels:
            content = _find_section(label)
            if not content:
                continue
            if content.upper().strip() in ("NINCS", "NONE", "N/A", "-", ""):
                return []
            items: List[str] = []
            for line in content.splitlines():
                line = _strip_bullet(line.strip())
                if line and len(line) > 2 and line.upper() not in ("NINCS", "NONE", "N/A"):
                    items.append(line)
            if not items and content:
                # Fallback: vesszo/pontosvesszo szeparalt lista — regex nelkul
                items = [
                    p.strip()
                    for p in content.replace(";", ",").split(",")
                    if p.strip() and len(p.strip()) > 2
                ]
            if items:
                return items[:10]
        return []

    def _make_bullet(items: List[str], title: str, prefix: str) -> Section:
        return Section(title=title, blocks=[
            Block(id=f"{prefix}{i+1}", type="bullet", content=item, color="")
            for i, item in enumerate(items)
        ])

    def _make_text(items: List[str], title: str, prefix: str) -> Section:
        if not items:
            return Section(title=title, blocks=[])
        return Section(title=title, blocks=[
            Block(id=f"{prefix}1", type="text", content=" ".join(items), color="")
        ])

    # Megbeszeles neve
    name_m = re.search(
        r"(?:MEETING NAME|MEGBESZEL[EÉ]S|[EÉ]RTEKEZLET)[:\s]+(.+?)[\n.]",
        extracted_text, re.IGNORECASE
    )
    meeting_name = name_m.group(1).strip() if name_m else f"Ertekezlet {chunk_index + 1}"

    people_items   = _parse_section("RÉSZTVEVŐK", "RESZTVEVOK", "PARTICIPANTS")
    summary_items  = _parse_section("ÖSSZEFOGLALÓ", "OSSZEFOGLALO", "SUMMARY")
    deadline_items = _parse_section("HATÁRIDŐK", "HATARIDK", "DEADLINES")
    decision_items = _parse_section("DÖNTÉSEK", "DONTESEK", "DECISIONS")
    action_items   = _parse_section("TEENDŐK", "TEENDOK", "ACTION ITEMS")
    next_items     = _parse_section("KÖVETKEZŐ LÉPÉSEK", "KOVETKEZO LEPESEK", "NEXT STEPS")

    logger.debug(
        f"  _text_to_summary: people={len(people_items)} summary={len(summary_items)} "
        f"deadlines={len(deadline_items)} decisions={len(decision_items)} "
        f"actions={len(action_items)} next={len(next_items)}"
    )

    people             = People(title="Resztvevok", blocks=[
        Block(id=f"p{i+1}", type="bullet", content=item, color="")
        for i, item in enumerate(people_items)
    ])
    session_summary    = _make_text  (summary_items,  "Osszefoglalo",        "s")
    critical_deadlines = _make_bullet(deadline_items, "Kritikus hataridk",   "d")
    key_decisions      = _make_bullet(decision_items, "Fobb dontesek",       "k")
    action_section     = _make_bullet(action_items,   "Teendok",             "a")
    next_steps         = _make_bullet(next_items,     "Kovetkezo lepesek",   "n")

    sections = [s for s in [session_summary, critical_deadlines, key_decisions,
                             action_section, next_steps] if s.blocks]
    meeting_notes = MeetingNotes(meeting_name=meeting_name, sections=sections)

    return SummaryResponse(
        MeetingName=meeting_name,
        People=people,
        SessionSummary=session_summary,
        CriticalDeadlines=critical_deadlines,
        KeyItemsDecisions=key_decisions,
        ImmediateActionItems=action_section,
        NextSteps=next_steps,
        MeetingNotes=meeting_notes,
    )




# ── Provider auto-detekció ───────────────────────────────────────────────────

async def _get_ollama_default_model() -> str:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_HOST}/api/tags")
            if r.status_code == 200:
                models = r.json().get("models", [])
                for pref in ["qwen2.5:14b","qwen2.5:7b","llama3.1:8b","gemma4:","llama3:"]:
                    for m in models:
                        if m.get("name","").startswith(pref):
                            return m["name"]
                if models:
                    return models[0].get("name","")
    except Exception:
        pass
    return ""

async def _get_nexa_default_model() -> str:
    _exclude = ("parakeet","embed","whisper","asr","depth","ocr","yolo","vl")
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{NEXA_BASE_URL}/models")
            if r.status_code == 200:
                models = r.json().get("data", [])
                for m in models:
                    if "Qwen3-8B-NPU" in m.get("id",""):
                        return m["id"]
                for m in models:
                    mid = m.get("id","")
                    if not any(x in mid.lower() for x in _exclude):
                        return mid
    except Exception:
        pass
    return ""

async def _get_cloud_api_key(provider: str, db=None) -> str:
    if db is not None:
        try:
            key = await db.get_api_key(provider)
            if key: return key
        except Exception:
            pass
    return {"claude":CLAUDE_API_KEY,"groq":GROQ_API_KEY,
            "openai":OPENAI_API_KEY,"openrouter":OPENROUTER_API_KEY}.get(provider,"")


# ══════════════════════════════════════════════════════════════════════════════
# TranscriptProcessor
# ══════════════════════════════════════════════════════════════════════════════

class TranscriptProcessor:

    def __init__(
        self,
        db=None,
        on_chunk_start: ChunkStartCB = None,
        on_chunk_done:  ChunkDoneCB  = None,
        on_chunk_error: ChunkErrorCB = None,
    ):
        self._db = db
        self._on_chunk_start = on_chunk_start
        self._on_chunk_done  = on_chunk_done
        self._on_chunk_error = on_chunk_error

    # ── Lokális: szöveges extrakció ───────────────────────────────────────────

    async def _extract_text_local(
        self, base_url, api_key, model_name, chunk, timeout, label,
        no_think=False, num_ctx=4096,
    ) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        system_prompt, user_prompt = _build_extraction_prompts(
            chunk, model_name=model_name, no_think=no_think
        )
        # DeepSeek-R1: system prompt kihagyjuk (rontja a teljesítményt)
        # NPU: ultra-rövid num_predict (512), standard: 1024
        family = _get_model_family(model_name)
        num_predict = 512 if family == "nexa_npu" else 1024
        temperature = 0.6 if family == "reasoning" else 0.2

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": num_predict,
            "options": {"num_ctx": num_ctx},
        }
        logger.info(f"[{label}] Extrakció: model={model_name} family={family} chunk={len(chunk)}kar")
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
        raw = resp.json().get("choices",[{}])[0].get("message",{}).get("content","")
        if "<think>" in raw:
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if not raw.strip():
            raise ValueError(f"[{label}] Üres extrakciós válasz")
        return raw

    async def _extract_text_ollama_native(self, model_name, chunk) -> str:
        try:
            from ollama import AsyncClient as OllamaClient
            client = OllamaClient(host=OLLAMA_HOST)
            family = _get_model_family(model_name)
            is_reasoning = family == "reasoning"
            no_think = is_reasoning  # nem szükséges Ollama R1-nél, de ártalmatlan

            system_prompt, user_prompt = _build_extraction_prompts(
                chunk, model_name=model_name, no_think=no_think
            )

            # DeepSeek-R1 kutatás: temperature=0.6, nincs system prompt
            # Qwen2.5: temperature=0.2 – konzisztensebb szöveges kimenet
            temperature = 0.6 if is_reasoning else 0.2
            num_predict = 2048 if is_reasoning else 1024  # R1 sokat gondolkozik

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

            logger.info(f"[Ollama] family={family} temp={temperature} predict={num_predict}")
            response = await client.chat(
                model=model_name,
                messages=messages,
                options={"temperature": temperature, "num_ctx": 4096, "num_predict": num_predict},
            )
            raw = response["message"]["content"]
            if "<think>" in raw:
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            return raw
        except ImportError:
            return await self._extract_text_local(
                base_url=f"{OLLAMA_HOST}/v1", api_key="ollama",
                model_name=model_name, chunk=chunk,
                timeout=OLLAMA_TIMEOUT, label="OllamaHTTP", num_ctx=4096,
            )

    # ── Cloud: egylépéses JSON ────────────────────────────────────────────────

    async def _call_json_api(
        self, base_url, api_key, model_name, chunk, custom_prompt,
        label, timeout, use_json_mode=True, extra_headers=None,
    ) -> SummaryResponse:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        # Modell-specifikus prompt + hőmérséklet
        system_prompt, user_prompt = _build_json_prompts(
            chunk, model_name=model_name, custom_prompt=custom_prompt
        )
        family = _get_model_family(model_name)
        # Kutatás: Qwen3 non-thinking=0.7, Llama/OpenAI=0.3 (JSON konzisztencia)
        temperature = 0.7 if "qwen" in model_name.lower() else 0.3

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": 4096,
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        logger.info(f"[{label}] JSON API: model={model_name} family={family} temp={temperature}")
        async with httpx.AsyncClient(timeout=timeout) as c:
            resp = await c.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        raw = resp.json().get("choices",[{}])[0].get("message",{}).get("content","")
        if not raw:
            raise ValueError(f"[{label}] Üres válasz")
        return SummaryResponse.model_validate(_parse_raw_json(raw))

    async def _call_anthropic(self, model_name, api_key, chunk, custom_prompt) -> SummaryResponse:
        # XML-tagelt prompt (Claude-specifikus optimum)
        system_prompt, user_prompt = _build_anthropic_prompts(chunk, custom_prompt)
        async with httpx.AsyncClient(timeout=120.0) as c:
            resp = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key":api_key,"anthropic-version":"2023-06-01","Content-Type":"application/json"},
                json={"model":model_name,"max_tokens":4096,"system":system_prompt,
                      "messages":[{"role":"user","content":user_prompt}]},
            )
            resp.raise_for_status()
        raw = resp.json().get("content",[{}])[0].get("text","")
        return SummaryResponse.model_validate(_parse_raw_json(raw))

    # ── Fő belépési pont ──────────────────────────────────────────────────────

    async def process_transcript(
        self, text, model, model_name,
        chunk_size=0, overlap=0, custom_prompt=""
    ) -> Tuple[int, List[str]]:
        provider = model.lower().strip()

        cloud_api_key = ""
        if provider in ("claude","groq","openai","openrouter"):
            cloud_api_key = await _get_cloud_api_key(provider, self._db)
            if not cloud_api_key:
                raise ValueError(f"[{provider.upper()}] API kulcs nem található.")

        LOCAL_CHUNK = 2000
        CLOUD_CHUNK = 8000

        PROVIDER_CFG = {
            "ollama": {
                "mode":"local_twostep","chunk_size":LOCAL_CHUNK,"overlap":200,
                "model":model_name,"timeout":OLLAMA_TIMEOUT,"no_think":False,
            },
            "nexa": {
                "mode":"local_twostep","chunk_size":LOCAL_CHUNK,"overlap":200,
                "base_url":NEXA_BASE_URL,"api_key":"local",
                "model":model_name or NEXA_LLM_MODEL,
                "timeout":NEXA_TIMEOUT,"label":"NexaLLM","no_think":True,"num_ctx":8192,
            },
            "omnineural": {
                "mode":"local_twostep","chunk_size":LOCAL_CHUNK,"overlap":200,
                "base_url":NEXA_MULTIMODAL_URL,"api_key":"local",
                "model":model_name or OMNINEURAL_MODEL,
                "timeout":NEXA_TIMEOUT,"label":"OmniNeural","no_think":False,"num_ctx":4096,
            },
            "npu": {
                "mode":"local_twostep","chunk_size":LOCAL_CHUNK,"overlap":200,
                "base_url":GENIE_BASE_URL,"api_key":"local",
                "model":model_name or GENIE_MODEL,
                "timeout":GENIE_TIMEOUT,"label":"GenieNPU","no_think":False,"num_ctx":4096,
            },
            "claude": {
                "mode":"claude","chunk_size":10000,"overlap":500,
                "api_key":cloud_api_key,"model":model_name or "claude-3-5-haiku-20241022","timeout":120.0,
            },
            "groq": {
                "mode":"cloud_json","chunk_size":6000,"overlap":400,
                "base_url":"https://api.groq.com/openai/v1","api_key":cloud_api_key,
                "model":model_name or "llama-3.3-70b-versatile",
                "timeout":60.0,"label":"Groq","json_mode":True,
            },
            "openai": {
                "mode":"cloud_json","chunk_size":CLOUD_CHUNK,"overlap":500,
                "base_url":"https://api.openai.com/v1","api_key":cloud_api_key,
                "model":model_name or "gpt-4o-mini",
                "timeout":60.0,"label":"OpenAI","json_mode":True,
            },
            "openrouter": {
                "mode":"cloud_json","chunk_size":CLOUD_CHUNK,"overlap":500,
                "base_url":"https://openrouter.ai/api/v1","api_key":cloud_api_key,
                "model":model_name or "meta-llama/llama-3.3-70b-instruct",
                "timeout":90.0,"label":"OpenRouter","json_mode":False,
                "extra_headers":{"HTTP-Referer":"https://meetily-snapdragon.local","X-Title":"Meetily"},
            },
        }

        if provider not in PROVIDER_CFG:
            raise ValueError(f"Ismeretlen provider: '{provider}'")

        if provider == "omnineural" and not cfg.get("model"):
            cfg["model"] = OMNINEURAL_MODEL

        cfg = PROVIDER_CFG[provider]

        if provider == "ollama" and not cfg.get("model"):
            cfg["model"] = await _get_ollama_default_model()
            if not cfg["model"]:
                raise ValueError("Ollama: nincs modell. Futtasd: ollama pull qwen2.5:7b")
        if provider == "nexa" and not cfg.get("model"):
            cfg["model"] = await _get_nexa_default_model()
            if not cfg["model"]:
                raise ValueError("NexaAI: nincs LLM modell.")

        eff_chunk = cfg["chunk_size"]
        eff_overlap = cfg.get("overlap", 200)
        step = max(eff_chunk - eff_overlap, 100)
        chunks = [text[i: i + eff_chunk] for i in range(0, len(text), step)]

        mode = cfg["mode"]
        logger.info(f"[TP] provider={provider} model={cfg.get('model')} mode={mode} chunks={len(chunks)}")

        all_json: List[str] = []

        for i, chunk in enumerate(chunks):
            # SSE callback: chunk feldolgozás kezdete
            if self._on_chunk_start:
                await self._on_chunk_start(i, len(chunks), len(chunk))

            logger.info(f"  → Chunk {i+1}/{len(chunks)} ({len(chunk)} kar)")
            try:
                if mode == "local_twostep":
                    if provider == "ollama":
                        extracted = await self._extract_text_ollama_native(cfg["model"], chunk)
                    else:
                        extracted = await self._extract_text_local(
                            base_url=cfg["base_url"], api_key=cfg["api_key"],
                            model_name=cfg["model"], chunk=chunk,
                            timeout=cfg["timeout"], label=cfg.get("label", provider),
                            no_think=cfg.get("no_think", False),
                            num_ctx=cfg.get("num_ctx", 4096),
                        )
                    logger.debug(f"  Extracted text preview: {extracted[:300]}")
                    result = _text_to_summary(extracted, chunk_index=i)
                    logger.debug(f"  Result preview: {result.model_dump_json()[:300]}")

                elif mode == "claude":
                    result = await self._call_anthropic(cfg["model"], cfg["api_key"], chunk, custom_prompt)

                else:  # cloud_json
                    result = await self._call_json_api(
                        base_url=cfg["base_url"], api_key=cfg["api_key"],
                        model_name=cfg["model"], chunk=chunk,
                        custom_prompt=custom_prompt,
                        label=cfg.get("label", provider),
                        timeout=cfg["timeout"],
                        use_json_mode=cfg.get("json_mode", True),
                        extra_headers=cfg.get("extra_headers"),
                    )

                result_json = result.model_dump_json()
                all_json.append(result_json)
                logger.info(f"  ✓ Chunk {i+1} kész")

                # SSE callback: chunk sikeres
                if self._on_chunk_done:
                    await self._on_chunk_done(i, len(chunks), result_json)

            except Exception as e:
                logger.error(f"  ✗ Chunk {i+1}: {e}", exc_info=True)
                # SSE callback: chunk hiba
                if self._on_chunk_error:
                    await self._on_chunk_error(i, str(e))

        logger.info(f"[TP] KÉSZ: {len(all_json)}/{len(chunks)}")
        return len(chunks), all_json

    def cleanup(self):
        pass


# ── Health checks ─────────────────────────────────────────────────────────────

async def check_genie_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{GENIE_BASE_URL}/models")
            if r.status_code == 200:
                return {"online":True,"models":[m["id"] for m in r.json().get("data",[])],"url":GENIE_BASE_URL}
    except Exception as e:
        return {"online":False,"error":str(e),"url":GENIE_BASE_URL}
    return {"online":False,"url":GENIE_BASE_URL}

async def check_ollama_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_HOST}/api/tags")
            if r.status_code == 200:
                return {"online":True,"models":[m["name"] for m in r.json().get("models",[])],"url":OLLAMA_HOST}
    except Exception as e:
        return {"online":False,"error":str(e),"url":OLLAMA_HOST}
    return {"online":False,"url":OLLAMA_HOST}

async def check_nexa_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{NEXA_BASE_URL}/models")
            if r.status_code == 200:
                return {"online":True,"models":[m["id"] for m in r.json().get("data",[])],"url":NEXA_BASE_URL}
    except Exception as e:
        return {"online":False,"error":str(e),"url":NEXA_BASE_URL}
    return {"online":False,"url":NEXA_BASE_URL}

async def check_omnineural_health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{NEXA_MULTIMODAL_URL}/models")
            if r.status_code == 200:
                return {"online": True, "models": [m["id"] for m in r.json().get("data", [])], "url": NEXA_MULTIMODAL_URL}
    except Exception as e:
        return {"online": False, "error": str(e), "url": NEXA_MULTIMODAL_URL}
    return {"online": False, "url": NEXA_MULTIMODAL_URL}

async def check_all_providers() -> dict:
    genie, ollama, nexa, omnineural = await asyncio.gather(
        check_genie_health(), check_ollama_health(), check_nexa_health(), check_omnineural_health(),
        return_exceptions=True)
    def _s(r): return {"online":False,"error":str(r)} if isinstance(r,Exception) else r
    return {
        "npu":        _s(genie),
        "ollama":     _s(ollama),
        "nexa":       _s(nexa),
        "omnineural": _s(omnineural),
        "claude":     {"online":bool(CLAUDE_API_KEY),"models":["claude-3-5-haiku-20241022","claude-3-5-sonnet-20241022"],"url":"https://api.anthropic.com"},
        "groq":       {"online":bool(GROQ_API_KEY),"models":["llama-3.3-70b-versatile","llama-3.1-8b-instant"],"url":"https://api.groq.com"},
        "openai":     {"online":bool(OPENAI_API_KEY),"models":["gpt-4o-mini","gpt-4o"],"url":"https://api.openai.com"},
        "openrouter": {"online":bool(OPENROUTER_API_KEY),"models":["meta-llama/llama-3.3-70b-instruct"],"url":"https://openrouter.ai"},
    }
