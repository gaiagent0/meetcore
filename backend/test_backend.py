"""
test_backend.py — Meetily Snapdragon backend teszt v2
Futtatás: python test_backend.py
"""
import asyncio, ast, json, os, re, sys, uuid, gc
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/app")
sys.path.insert(0, os.getcwd())

PASS, FAIL = [], []

def ok(name): PASS.append(name); print(f"  ✓ {name}")
def err(name, e=""): FAIL.append(name); print(f"  ✗ {name}" + (f": {e}" if e else ""))

print("\n" + "="*55)
print("MEETILY SNAPDRAGON — BACKEND TESZT v2")
print("="*55)

# ── 1. SZINTAXIS ─────────────────────────────────────────
print("\n[1] SZINTAXIS")
for f in ["main.py","npu_routes.py","transcript_processor.py","db.py","whisper_npu.py"]:
    try:
        ast.parse(open(f, encoding="utf-8").read())
        ok(f)
    except SyntaxError as e:
        err(f, str(e))
    except FileNotFoundError:
        err(f, "nem található")

# ── 2. IMPORT ─────────────────────────────────────────────
print("\n[2] IMPORT")
try:
    from transcript_processor import (
        TranscriptProcessor, SummaryResponse,
        _parse_raw_json, _build_user_prompt,
        check_all_providers, check_genie_health,
        check_ollama_health, check_nexa_health,
        GENIE_BASE_URL, OLLAMA_HOST, NEXA_BASE_URL,
        _normalize_url,
    )
    ok("transcript_processor — minden szimbólum")
except Exception as e:
    err("transcript_processor", e)

try:
    from npu_routes import npu_router
    ok("npu_routes")
except Exception as e:
    err("npu_routes", e)

try:
    from db import DatabaseManager
    ok("db.DatabaseManager")
except Exception as e:
    err("db.DatabaseManager", e)

try:
    from whisper_npu import is_npu_available, BACKEND
    ok(f"whisper_npu (backend={BACKEND})")
except Exception as e:
    err("whisper_npu", e)

# ── 3. URL NORMALIZÁLÁS ──────────────────────────────────
print("\n[3] URL NORMALIZÁLÁS (_normalize_url)")
cases = [
    ("127.0.0.1:11434",        "http://127.0.0.1:11434"),
    ("localhost:11434",        "http://localhost:11434"),
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://127.0.0.1:11434/","http://127.0.0.1:11434"),
    ("",                       "http://127.0.0.1:11434"),
]
for raw, expected in cases:
    result = _normalize_url(raw, "http://127.0.0.1:11434")
    if result == expected:
        ok(f'"{raw}" → "{result}"')
    else:
        err(f'"{raw}"', f"várt: {expected}, kapott: {result}")

print(f"\n  Aktív URL-ek:")
print(f"    GENIE_BASE_URL = {GENIE_BASE_URL}")
print(f"    OLLAMA_HOST    = {OLLAMA_HOST}")
print(f"    NEXA_BASE_URL  = {NEXA_BASE_URL}")

# ── 4. PYDANTIC MODELLEK ──────────────────────────────────
print("\n[4] PYDANTIC MODELLEK")
test_data = {
    "MeetingName": "Teszt meeting",
    "People": {"title": "Résztvevők", "blocks": [{"id":"p1","type":"bullet","content":"Kovács J.","color":""}]},
    "SessionSummary": {"title": "Összefoglaló", "blocks": [{"id":"s1","type":"text","content":"Megbeszéltük.","color":""}]},
    "CriticalDeadlines": {"title": "Határidők", "blocks": []},
    "KeyItemsDecisions": {"title": "Döntések", "blocks": []},
    "ImmediateActionItems": {"title": "Teendők", "blocks": []},
    "NextSteps": {"title": "Következő lépések", "blocks": []},
    "MeetingNotes": {"meeting_name": "Teszt", "sections": []},
}
try:
    r = SummaryResponse.model_validate(test_data)
    ok(f"SummaryResponse.model_validate → {r.MeetingName}")
except Exception as e:
    err("SummaryResponse", e)

for label, raw in [
    ("plain JSON",      json.dumps(test_data)),
    ("markdown fence",  "```json\n" + json.dumps(test_data) + "\n```"),
]:
    try:
        SummaryResponse.model_validate(_parse_raw_json(raw))
        ok(f"_parse_raw_json ({label})")
    except Exception as e:
        err(f"_parse_raw_json {label}", e)

try:
    buggy = dict(test_data); buggy["People"] = json.dumps(test_data["People"])
    assert isinstance(_parse_raw_json(json.dumps(buggy))["People"], dict)
    ok("_parse_raw_json (nested-string fix)")
except Exception as e:
    err("_parse_raw_json nested-string", e)

# ── 5. DB INTERFÉSZ ───────────────────────────────────────
print("\n[5] DB INTERFÉSZ")
try:
    db = DatabaseManager()
    ok("DatabaseManager() példányosítás")
    for m in ["save_meeting","save_transcript","create_process","update_process",
              "get_meeting","get_all_meetings","update_meeting_summary","delete_meeting"]:
        if hasattr(db, m): ok(f"  db.{m}()")
        else: err(f"  db.{m}()", "hiányzik")
except Exception as e:
    err("DatabaseManager", e)

# ── 6. PROVIDER KONFIG ────────────────────────────────────
print("\n[6] PROVIDER KONFIG")
src = open("transcript_processor.py", encoding="utf-8").read()
for p in ["npu","ollama","nexa"]:
    if f'"{p}"' in src or f"'{p}'" in src: ok(p)
    else: err(p, "hiányzik a PROVIDER_CONFIG-ból")

# ── 7. PROVIDER HEALTH (live) ────────────────────────────
print("\n[7] PROVIDER HEALTH (live)")
async def run_health():
    results = await check_all_providers()
    for name, info in results.items():
        status = "ONLINE" if info.get("online") else "offline"
        models = info.get("models", [])
        suffix = f" → modellek: {models[:3]}" if models else (f" ({info.get('error','')})" if not info.get("online") else "")
        print(f"  [{status}] {name}{suffix}")

asyncio.run(run_health())

# ── 8. FASTAPI ENDPOINTS ──────────────────────────────────
print("\n[8] FASTAPI ENDPOINTS")
try:
    import main as m_mod
    routes = {r.path for r in m_mod.app.routes if hasattr(r,"path")}
    for ep in ["/health","/process-transcript","/save-transcript","/get-meetings",
               "/get-summary/{meeting_id}","/save-meeting-summary","/delete-meeting/{meeting_id}"]:
        if ep in routes: ok(ep)
        else: err(ep, "hiányzó endpoint")
except Exception as e:
    err("FastAPI app import", e)

# ── 9. DB ASYNC TESZT (Windows-safe cleanup) ──────────────
print("\n[9] DB ASYNC MŰVELETEK")
TEST_DB = "test_temp_v2.db"

async def run_db_test():
    db2 = None
    try:
        db2 = DatabaseManager(db_path=TEST_DB)
        mid = str(uuid.uuid4())

        await db2.save_meeting(mid, "Teszt meeting")
        ok("save_meeting()")

        await db2.save_transcript(mid, "Ez egy teszt átírás szöveg.", "npu", "Qwen3", 5000, 1000)
        ok("save_transcript()")

        await db2.create_process(mid)
        ok("create_process()")

        await db2.update_process(mid, "COMPLETED", result={"test": True}, chunk_count=1)
        ok("update_process()")

        m = await db2.get_meeting(mid)
        assert m and m["id"] == mid
        ok(f"get_meeting() → '{m['title']}'")

        all_m = await db2.get_all_meetings()
        assert any(x["id"] == mid for x in all_m)
        ok(f"get_all_meetings() → {len(all_m)} meeting")

        await db2.update_meeting_summary(mid, {"MeetingName": "Teszt", "summary": "ok"})
        ok("update_meeting_summary()")

        deleted = await db2.delete_meeting(mid)
        assert deleted
        ok("delete_meeting()")

    except Exception as e:
        err("DB async teszt", e)
        import traceback; traceback.print_exc()
    finally:
        # Windows: aiosqlite lezárása előtt GC kell a handle felszabadításához
        db2 = None
        gc.collect()
        await asyncio.sleep(0.2)
        try:
            if os.path.exists(TEST_DB):
                os.unlink(TEST_DB)
                ok("test_temp.db takarítás")
        except Exception as e:
            print(f"  (temp DB törlés sikertelen, manuálisan törölhető: {TEST_DB})")

asyncio.run(run_db_test())

# ── 10. FELHŐS SDK ────────────────────────────────────────
print("\n[10] FELHŐS SDK (nem szabad importálva lenni)")
for sdk in ["anthropic","groq","pydantic_ai","openai"]:
    if sdk in sys.modules: err(sdk, "be van töltve!")
    else: ok(f"{sdk} — nincs betöltve")

# ── ÖSSZESÍTÉS ────────────────────────────────────────────
print("\n" + "="*55)
total = len(PASS) + len(FAIL)
print(f"EREDMÉNY: {len(PASS)}/{total} SIKERES")
if FAIL:
    print(f"HIBÁK ({len(FAIL)}):"); [print(f"  ✗ {f}") for f in FAIL]
else:
    print("MINDEN TESZT SIKERES ✓")
print("="*55)
