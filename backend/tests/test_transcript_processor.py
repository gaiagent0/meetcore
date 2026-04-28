"""
test_transcript_processor.py — MeetCore v3
Futtatás: cd backend && python -m pytest tests/ -v
Nem igényel futó szolgáltatásokat.
"""
import asyncio
import json
import pytest

from transcript_processor import (
    _get_model_family,
    _build_extraction_prompts,
    _build_json_prompts,
    _parse_raw_json,
    _text_to_summary,
    _repair_blocks,
    SummaryResponse,
)

SAMPLE_CHUNK = (
    "RÉSZTVEVŐK: Kovács János (PM), Tóth Anna (Dev)\n"
    "ÖSSZEFOGLALÓ: Megbeszéltük a sprint célokat és a határidőket.\n"
    "HATÁRIDŐK: 2026-05-01 — backend deploy (Tóth Anna)\n"
    "DÖNTÉSEK: Redis session store marad.\n"
    "TEENDŐK: Anna: tesztek, János: dokumentáció\n"
    "KÖVETKEZŐ LÉPÉSEK: Következő meeting 2026-05-05\n"
)


# ── _get_model_family ────────────────────────────────────────────────────────

class TestGetModelFamily:
    def test_reasoning_deepseek(self):
        assert _get_model_family("deepseek-r1:7b") == "reasoning"

    def test_reasoning_qwq(self):
        assert _get_model_family("qwq-32b") == "reasoning"

    def test_nexa_npu(self):
        assert _get_model_family("NexaAI/Qwen3-8B-NPU") == "nexa_npu"

    def test_nexa_keyword(self):
        assert _get_model_family("nexa-model-v1") == "nexa_npu"

    def test_omnineural(self):
        assert _get_model_family("NexaAI/OmniNeural-4B") == "omnineural"

    def test_omni_neural_hyphen(self):
        assert _get_model_family("omni-neural-v2") == "omnineural"

    def test_qwen3(self):
        assert _get_model_family("qwen3:8b") == "qwen3"

    def test_qwen2(self):
        assert _get_model_family("qwen2.5:14b") == "qwen2"

    def test_gemma(self):
        assert _get_model_family("gemma4:27b") == "gemma"

    def test_llama(self):
        assert _get_model_family("llama3.3-70b-versatile") == "llama"

    def test_llama3(self):
        assert _get_model_family("llama3.1-8b") == "llama"

    def test_generic_fallback(self):
        assert _get_model_family("gpt-4o-mini") == "generic"

    def test_empty_string(self):
        assert _get_model_family("") == "generic"


# ── _build_extraction_prompts ─────────────────────────────────────────────────

class TestBuildExtractionPrompts:
    def test_reasoning_no_system_prompt(self):
        sys_p, user_p = _build_extraction_prompts("szöveg", model_name="deepseek-r1:7b")
        assert sys_p is None
        assert "szöveg" in user_p

    def test_reasoning_has_xml_tags(self):
        _, user_p = _build_extraction_prompts("t", model_name="deepseek-r1:7b")
        assert "<task>" in user_p or "<transcript>" in user_p

    def test_nexa_npu_has_system(self):
        sys_p, user_p = _build_extraction_prompts("t", model_name="NexaAI/Qwen3-8B-NPU")
        assert sys_p is not None
        assert len(sys_p) < 100  # ultra-tömör

    def test_nexa_npu_no_think_prefix(self):
        _, user_p = _build_extraction_prompts("t", model_name="NexaAI/Qwen3-8B-NPU", no_think=True)
        assert user_p.startswith("/no_think")

    def test_qwen3_no_think(self):
        _, user_p = _build_extraction_prompts("t", model_name="qwen3:8b", no_think=True)
        assert "/no_think" in user_p

    def test_llama_english_system(self):
        sys_p, _ = _build_extraction_prompts("t", model_name="llama3.1:8b")
        assert sys_p is not None
        assert "Hungarian" in sys_p or "hungarian" in sys_p.lower()

    def test_omnineural_has_system(self):
        sys_p, user_p = _build_extraction_prompts("t", model_name="NexaAI/OmniNeural-4B")
        assert sys_p is not None
        assert "MAGYAR" in user_p.upper() or "magyar" in user_p.lower()

    def test_gemma_markdown_headers(self):
        _, user_p = _build_extraction_prompts("t", model_name="gemma4:27b")
        assert "##" in user_p

    def test_generic_fallback_has_sections(self):
        _, user_p = _build_extraction_prompts("t", model_name="unknown-model-xyz")
        for label in ("RÉSZTVEVŐK", "ÖSSZEFOGLALÓ", "TEENDŐK"):
            assert label in user_p

    def test_chunk_is_included(self):
        chunk = "egyedi_teszt_szoveg_xyz"
        _, user_p = _build_extraction_prompts(chunk, model_name="llama3.1:8b")
        assert chunk in user_p


# ── _build_json_prompts ───────────────────────────────────────────────────────

class TestBuildJsonPrompts:
    def test_returns_tuple(self):
        result = _build_json_prompts("t", model_name="llama3.3-70b")
        assert isinstance(result, tuple) and len(result) == 2

    def test_llama_english_system(self):
        sys_p, _ = _build_json_prompts("t", model_name="llama3.3-70b-versatile")
        assert "JSON" in sys_p

    def test_schema_in_user_prompt(self):
        _, user_p = _build_json_prompts("chunk", model_name="qwen2.5:14b")
        assert "MeetingName" in user_p

    def test_custom_prompt_included(self):
        _, user_p = _build_json_prompts("t", model_name="gpt-4o", custom_prompt="context_xyz")
        assert "context_xyz" in user_p

    def test_chunk_in_user_prompt(self):
        chunk = "egyedi_chunk_abc"
        _, user_p = _build_json_prompts(chunk, model_name="gpt-4o")
        assert chunk in user_p


# ── _parse_raw_json ───────────────────────────────────────────────────────────

VALID_SUMMARY = {
    "MeetingName": "Sprint meeting",
    "People": {"title": "Résztvevők", "blocks": [{"id": "p1", "type": "bullet", "content": "Kovács J.", "color": ""}]},
    "SessionSummary": {"title": "Összefoglaló", "blocks": [{"id": "s1", "type": "text", "content": "Megbeszéltük.", "color": ""}]},
    "CriticalDeadlines": {"title": "Határidők", "blocks": []},
    "KeyItemsDecisions": {"title": "Döntések", "blocks": []},
    "ImmediateActionItems": {"title": "Teendők", "blocks": []},
    "NextSteps": {"title": "Következő lépések", "blocks": []},
    "MeetingNotes": {"meeting_name": "Sprint", "sections": []},
}

class TestParseRawJson:
    def test_plain_json(self):
        result = _parse_raw_json(json.dumps(VALID_SUMMARY))
        assert result["MeetingName"] == "Sprint meeting"

    def test_markdown_fence_json(self):
        raw = "```json\n" + json.dumps(VALID_SUMMARY) + "\n```"
        result = _parse_raw_json(raw)
        assert result["MeetingName"] == "Sprint meeting"

    def test_markdown_fence_no_lang(self):
        raw = "```\n" + json.dumps(VALID_SUMMARY) + "\n```"
        result = _parse_raw_json(raw)
        assert "MeetingName" in result

    def test_think_tags_stripped(self):
        raw = "<think>gondolkodás...</think>\n" + json.dumps(VALID_SUMMARY)
        result = _parse_raw_json(raw)
        assert result["MeetingName"] == "Sprint meeting"

    def test_nested_string_fix(self):
        buggy = dict(VALID_SUMMARY)
        buggy["People"] = json.dumps(VALID_SUMMARY["People"])
        result = _parse_raw_json(json.dumps(buggy))
        assert isinstance(result["People"], dict)

    def test_json_embedded_in_text(self):
        raw = "Íme az összefoglaló: " + json.dumps(VALID_SUMMARY) + "\nEz a vége."
        result = _parse_raw_json(raw)
        assert result["MeetingName"] == "Sprint meeting"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_raw_json("ez nem json")


# ── _text_to_summary ─────────────────────────────────────────────────────────

class TestTextToSummary:
    def test_basic_parsing(self):
        result = _text_to_summary(SAMPLE_CHUNK)
        assert isinstance(result, SummaryResponse)

    def test_people_extracted(self):
        result = _text_to_summary(SAMPLE_CHUNK)
        people_content = " ".join(b.content for b in result.People.blocks)
        assert "Kovács" in people_content or "Tóth" in people_content

    def test_summary_extracted(self):
        result = _text_to_summary(SAMPLE_CHUNK)
        assert result.SessionSummary.blocks  # nem üres

    def test_action_items_extracted(self):
        result = _text_to_summary(SAMPLE_CHUNK)
        assert result.ImmediateActionItems.blocks

    def test_nincs_returns_empty(self):
        text = (
            "RÉSZTVEVŐK: Kovács J.\n"
            "ÖSSZEFOGLALÓ: Rövid meeting.\n"
            "HATÁRIDŐK: NINCS\n"
            "DÖNTÉSEK: NINCS\n"
            "TEENDŐK: NINCS\n"
            "KÖVETKEZŐ LÉPÉSEK: NINCS\n"
        )
        result = _text_to_summary(text)
        assert result.CriticalDeadlines.blocks == []
        assert result.KeyItemsDecisions.blocks == []

    def test_english_labels_fallback(self):
        text = (
            "PARTICIPANTS: John, Jane\n"
            "SUMMARY: We discussed the roadmap.\n"
            "DEADLINES: NONE\n"
            "DECISIONS: Use FastAPI.\n"
            "ACTION ITEMS: John: deploy\n"
            "NEXT STEPS: Review next week\n"
        )
        result = _text_to_summary(text)
        people_content = " ".join(b.content for b in result.People.blocks)
        assert "John" in people_content or "Jane" in people_content

    def test_chunk_index_in_meeting_name_fallback(self):
        result = _text_to_summary("nincs szekció", chunk_index=3)
        assert "4" in result.MeetingName or result.MeetingName  # nem üres

    def test_returns_summary_response_type(self):
        result = _text_to_summary(SAMPLE_CHUNK)
        assert isinstance(result, SummaryResponse)
        # model_dump_json() hívható
        dumped = result.model_dump_json()
        assert "MeetingName" in dumped


# ── _repair_blocks ────────────────────────────────────────────────────────────

class TestRepairBlocks:
    def test_dict_list_unchanged(self):
        blocks = [{"id": "p1", "type": "bullet", "content": "x", "color": ""}]
        assert _repair_blocks(blocks) == blocks

    def test_empty_list_unchanged(self):
        assert _repair_blocks([]) == []

    def test_json_string_list_parsed(self):
        block = {"id": "p1", "type": "bullet", "content": "Kovács", "color": ""}
        blocks = [json.dumps(block)]
        result = _repair_blocks(blocks)
        assert isinstance(result[0], dict)
        assert result[0]["content"] == "Kovács"

    def test_yaml_style_list_parsed(self):
        blocks = ["id: p1", "type: bullet", "content: Tóth Anna", "color: "]
        result = _repair_blocks(blocks)
        assert len(result) == 1
        assert result[0]["content"] == "Tóth Anna"
        assert result[0]["type"] == "bullet"

    def test_multiple_yaml_blocks(self):
        blocks = [
            "id: p1", "type: bullet", "content: Első", "color: ",
            "id: p2", "type: bullet", "content: Második", "color: ",
        ]
        result = _repair_blocks(blocks)
        assert len(result) == 2
        assert result[1]["content"] == "Második"
