'use client';

/**
 * SummaryGeneratorPanel v2 — SSE live progress tracking
 * ───────────────────────────────────────────────────────
 * Valódi chunk-onkénti visszajelzés Server-Sent Events segítségével.
 * EventSource → /process-transcript-stream
 *
 * SSE események: init | chunk_start | chunk_done | chunk_error | saving | done | error
 */

import { useEffect, useState, useCallback, useRef } from 'react';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

// Modellek amelyek NEM alkalmasak összefoglalóra
const NON_LLM_PATTERNS = [
  'parakeet','embed','whisper','asr','depth','ocr',
  'yolo','vl-','vision','bge-','nomic-embed','EmbedNeural','paddleocr','depth-anything',
];
function isLLM(id: string) {
  return !NON_LLM_PATTERNS.some((p) => id.toLowerCase().includes(p.toLowerCase()));
}

const PROVIDER_META: Record<string, { label: string; icon: string; isCloud: boolean; defaultModel: string; hint: string }> = {
  ollama:     { label:'Ollama (lokális)',   icon:'🤖', isCloud:false, defaultModel:'qwen2.5:7b',             hint:'CPU/GPU · Offline · Lassabb' },
  nexa:       { label:'NexaAI NPU',         icon:'🦜', isCloud:false, defaultModel:'NexaAI/Qwen3-8B-NPU',   hint:'Qualcomm NPU · Offline · ~60s' },
  npu:        { label:'NPU (GenieAPI)',      icon:'🖥️', isCloud:false, defaultModel:'',                       hint:'Qualcomm Hexagon · <5W' },
  claude:     { label:'Claude (Anthropic)', icon:'🧠', isCloud:true,  defaultModel:'claude-3-5-haiku-20241022', hint:'API kulcs szükséges' },
  groq:       { label:'Groq',               icon:'⚡', isCloud:true,  defaultModel:'llama-3.3-70b-versatile', hint:'Nagyon gyors · API kulcs' },
  openai:     { label:'OpenAI',             icon:'🟢', isCloud:true,  defaultModel:'gpt-4o-mini',            hint:'API kulcs szükséges' },
  openrouter: { label:'OpenRouter',         icon:'🔀', isCloud:true,  defaultModel:'meta-llama/llama-3.3-70b-instruct', hint:'Aggregátor · API kulcs' },
};

const STATIC_MODELS: Record<string, string[]> = {
  npu:        ['llama3.1-8b-8380-qnn2.38'],
  claude:     ['claude-3-5-haiku-20241022','claude-3-5-sonnet-20241022'],
  groq:       ['llama-3.3-70b-versatile','llama-3.1-8b-instant'],
  openai:     ['gpt-4o-mini','gpt-4o'],
  openrouter: ['meta-llama/llama-3.3-70b-instruct','google/gemini-flash-1.5'],
};

// ── Progress lépések ─────────────────────────────────────────────────────────
type StepStatus = 'waiting' | 'active' | 'done' | 'error';
interface Step { id: string; label: string; status: StepStatus; detail?: string; }

interface Props {
  meetingId: string;
  transcript: string;
  hasSummary: boolean;
  onSummaryReady: (s: Record<string, unknown>) => void;
}

// ════════════════════════════════════════════════════════════════════════════
export default function SummaryGeneratorPanel({ meetingId, transcript, hasSummary, onSummaryReady }: Props) {
  const [providerInfo, setProviderInfo] = useState<Record<string, { online: boolean; models: string[] }>>({});
  const [provider, setProvider]         = useState('ollama');
  const [model, setModel]               = useState('');
  const [generating, setGenerating]     = useState(false);
  const [steps, setSteps]               = useState<Step[]>([]);
  const [elapsed, setElapsed]           = useState(0);
  const startTsRef                      = useRef<number>(0);
  const [errorMsg, setErrorMsg]         = useState('');

  // ── Provider lista betöltése ───────────────────────────────────────────────
  const loadProviders = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/npu/providers`, { signal: AbortSignal.timeout(6000) });
      if (r.ok) setProviderInfo(await r.json());
    } catch { /* silent */ }
  }, []);

  useEffect(() => { loadProviders(); }, [loadProviders]);

  // ── LLM modellek az adott providerhez ────────────────────────────────────
  const getLLMModels = (p: string): string[] => {
    if (p === 'ollama' || p === 'nexa') {
      const live = (providerInfo[p]?.models ?? []).filter(isLLM);
      return live.length > 0 ? live : [PROVIDER_META[p]?.defaultModel].filter(Boolean) as string[];
    }
    return STATIC_MODELS[p] ?? [PROVIDER_META[p]?.defaultModel].filter(Boolean) as string[];
  };

  // ── Elérhető providerek ───────────────────────────────────────────────────
  const available = Object.keys(PROVIDER_META).filter((p) => {
    const info = providerInfo[p];
    return PROVIDER_META[p].isCloud ? info?.online !== false : info?.online === true;
  });

  const handleProviderChange = (p: string) => {
    setProvider(p);
    const models = getLLMModels(p);
    setModel(models[0] ?? '');
    setErrorMsg('');
  };

  // ── Timer ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!generating) return;
    const iv = setInterval(() => setElapsed(Math.floor((Date.now() - startTsRef.current) / 1000)), 500);
    return () => clearInterval(iv);
  }, [generating]);

  const setStep = (id: string, status: StepStatus, detail?: string) =>
    setSteps((prev) => prev.map((s) => s.id === id ? { ...s, status, detail: detail ?? s.detail } : s));

  const markActiveError = (msg: string) => {
    setSteps((prev) => prev.map((s) => s.status === 'active' ? { ...s, status: 'error', detail: msg.slice(0, 120) } : s));
  };

  // ── SSE generálás ─────────────────────────────────────────────────────────
  const generate = async () => {
    if (!transcript.trim() || generating) return;
    setGenerating(true);
    setErrorMsg('');
    startTsRef.current = Date.now();
    setElapsed(0);

    // Kezdeti lépések (init előtt becsüljük)
    const initSteps: Step[] = [
      { id: 'init',    label: '📄 Előkészítés',  status: 'active'  },
      { id: 'send',    label: '🚀 Csatlakozás',   status: 'waiting' },
      { id: 'process', label: '🤖 Feldolgozás',   status: 'waiting' },
      { id: 'save',    label: '💾 Mentés',         status: 'waiting' },
      { id: 'done',    label: '✅ Kész',           status: 'waiting' },
    ];
    setSteps(initSteps);

    try {
      // SSE fetch (EventSource nem támogatja a POST-ot, fetch-et használunk)
      const resp = await fetch(`${BACKEND_URL}/process-transcript-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify({ meeting_id: meetingId, transcript_text: transcript, model: provider, model_name: model }),
      });

      if (!resp.ok || !resp.body) {
        const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
        throw new Error(err.detail ?? `HTTP ${resp.status}`);
      }

      setStep('init', 'done');
      setStep('send', 'active');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let chunkSteps: Step[] = [];
      let chunkInserted = false;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE üzenetek kinyerése
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ') && eventType) {
            try {
              const data = JSON.parse(line.slice(6));

              if (eventType === 'init') {
                setStep('send', 'done');
                // Chunk lépések beillesztése
                const total = data.chunks_estimated ?? 1;
                chunkSteps = Array.from({ length: total }, (_, i) => ({
                  id: `chunk_${i}`,
                  label: total > 1 ? `🤖 Chunk ${i+1}/${total}` : '🤖 Feldolgozás',
                  status: 'waiting' as StepStatus,
                  detail: `~${Math.round(len_estimate(provider) * 0.8)}s`,
                }));
                // Beillesztjük a process lépés elé
                setSteps((prev) => {
                  const filtered = prev.filter((s) => s.id !== 'process');
                  const processIdx = prev.findIndex((s) => s.id === 'process');
                  const before = filtered.slice(0, processIdx);
                  const after  = filtered.slice(processIdx);
                  return [...before, ...chunkSteps, ...after];
                });
                chunkInserted = true;
              }

              else if (eventType === 'chunk_start') {
                const idx = data.chunk - 1;
                setSteps((prev) => prev.map((s) =>
                  s.id === `chunk_${idx}` ? { ...s, status: 'active', detail: `${data.chunk_chars} kar` } : s
                ));
              }

              else if (eventType === 'chunk_done') {
                const idx = data.chunk - 1;
                setSteps((prev) => prev.map((s) =>
                  s.id === `chunk_${idx}` ? { ...s, status: 'done', detail: `✓` } : s
                ));
              }

              else if (eventType === 'chunk_error') {
                const idx = data.chunk - 1;
                setSteps((prev) => prev.map((s) =>
                  s.id === `chunk_${idx}` ? { ...s, status: 'error', detail: data.error } : s
                ));
              }

              else if (eventType === 'saving') {
                setStep('save', 'active');
              }

              else if (eventType === 'done') {
                setStep('save', 'done');
                const totalSecs = Math.floor((Date.now() - startTsRef.current) / 1000);
                setStep('done', 'done', `${totalSecs}s alatt`);
                if (data.summary && Object.keys(data.summary).length > 0) {
                  console.log('[SummaryPanel] done, summary keys:', Object.keys(data.summary));
                  onSummaryReady(data.summary);
                } else {
                  console.warn('[SummaryPanel] done de summary üres:', data.summary);
                }
              }

              else if (eventType === 'error') {
                throw new Error(data.detail ?? 'Ismeretlen hiba');
              }

            } catch (parseErr) {
              if (parseErr instanceof Error && parseErr.message !== 'Ismeretlen hiba') {
                // JSON parse hiba – ignoráljuk
              } else {
                throw parseErr;
              }
            }
            eventType = '';
          }
        }
      }

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      markActiveError(msg);
    } finally {
      setGenerating(false);
    }
  };

  // ── Sebesség becslés (mp/chunk) ───────────────────────────────────────────
  function len_estimate(p: string): number {
    return { ollama:45, nexa:70, npu:30, claude:10, groq:8, openai:10, openrouter:15 }[p] ?? 20;
  }

  // ── Lépés stílusok ───────────────────────────────────────────────────────
  const stepColor = (s: StepStatus) =>
    ({ waiting:'#e5e7eb', active:'#3b82f6', done:'#22c55e', error:'#ef4444' }[s]);
  const stepBg = (s: StepStatus) =>
    ({ waiting:'transparent', active:'#eff6ff', done:'#f0fdf4', error:'#fef2f2' }[s]);
  const stepTextColor = (s: StepStatus) =>
    ({ waiting:'#9ca3af', active:'#1d4ed8', done:'#166534', error:'#dc2626' }[s]);

  const localAvail  = available.filter((p) => !PROVIDER_META[p].isCloud);
  const cloudAvail  = available.filter((p) => PROVIDER_META[p].isCloud);
  const llmModels   = getLLMModels(provider);
  const currentMeta = PROVIDER_META[provider];

  return (
    <div style={{ marginTop:'1rem', padding:'1rem', backgroundColor:'#fff', borderRadius:'10px', border:'1px solid #e5e7eb' }}>

      {/* Fejléc */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'0.75rem' }}>
        <p style={{ margin:0, fontSize:'0.9rem', fontWeight:700, color:'#111827' }}>
          {hasSummary ? '♻️ Újragenerálás' : '✨ Összefoglaló generálása'}
        </p>
        {generating && (
          <span style={{ fontSize:'0.75rem', color:'#6b7280', fontVariantNumeric:'tabular-nums' }}>
            ⏱ {elapsed}s
          </span>
        )}
      </div>

      {/* Selector (csak ha nem generál) */}
      {!generating && (
        <div style={{ display:'flex', gap:'0.5rem', flexWrap:'wrap', marginBottom:'0.75rem' }}>

          {/* Provider */}
          <div>
            <label style={{ display:'block', fontSize:'0.68rem', fontWeight:700, color:'#6b7280', marginBottom:'0.2rem', textTransform:'uppercase' }}>
              Szolgáltató
            </label>
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              style={{ padding:'0.35rem 0.4rem', borderRadius:'6px', border:'1px solid #d1d5db', fontSize:'0.82rem', background:'#fff', cursor:'pointer' }}
            >
              {cloudAvail.length > 0 && (
                <optgroup label="☁️ Felhős">
                  {cloudAvail.map((p) => (
                    <option key={p} value={p}>{PROVIDER_META[p].icon} {PROVIDER_META[p].label}</option>
                  ))}
                </optgroup>
              )}
              {localAvail.length > 0 && (
                <optgroup label="🖥️ Lokális (offline)">
                  {localAvail.map((p) => (
                    <option key={p} value={p}>{PROVIDER_META[p].icon} {PROVIDER_META[p].label}</option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>

          {/* Modell */}
          <div style={{ flex:1, minWidth:'150px' }}>
            <label style={{ display:'block', fontSize:'0.68rem', fontWeight:700, color:'#6b7280', marginBottom:'0.2rem', textTransform:'uppercase' }}>
              Modell
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              style={{ width:'100%', padding:'0.35rem 0.4rem', borderRadius:'6px', border:'1px solid #d1d5db', fontSize:'0.8rem', fontFamily:'monospace', background:'#fff', cursor:'pointer' }}
            >
              {llmModels.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          {/* Gomb */}
          <div style={{ alignSelf:'flex-end' }}>
            <button
              onClick={generate}
              disabled={!transcript.trim()}
              style={{ padding:'0.38rem 1rem', borderRadius:'6px', backgroundColor:transcript.trim() ? '#3b82f6' : '#e5e7eb', color:transcript.trim() ? '#fff' : '#9ca3af', border:'none', cursor:transcript.trim() ? 'pointer' : 'not-allowed', fontSize:'0.85rem', fontWeight:700 }}
            >
              Generálás
            </button>
          </div>
        </div>
      )}

      {/* Provider info chip (generálás közben) */}
      {generating && currentMeta && (
        <div style={{ display:'flex', alignItems:'center', gap:'0.35rem', marginBottom:'0.75rem', padding:'0.3rem 0.6rem', backgroundColor:'#f8fafc', borderRadius:'6px', border:'1px solid #e2e8f0', fontSize:'0.8rem' }}>
          <span style={{ fontSize:'1rem' }}>{currentMeta.icon}</span>
          <span style={{ fontWeight:600 }}>{currentMeta.label}</span>
          <span style={{ color:'#94a3b8' }}>·</span>
          <code style={{ fontSize:'0.75rem', color:'#475569' }}>{model}</code>
          <span style={{ marginLeft:'auto', fontSize:'0.7rem', color:'#94a3b8' }}>{currentMeta.hint}</span>
        </div>
      )}

      {/* Provider hint (ha nem generál) */}
      {!generating && currentMeta && (
        <div style={{ fontSize:'0.72rem', color:'#9ca3af', marginBottom:'0.5rem', paddingLeft:'0.1rem' }}>
          {currentMeta.icon} {currentMeta.hint}
        </div>
      )}

      {/* Progress tracker */}
      {steps.length > 0 && (
        <div style={{ display:'flex', flexDirection:'column', gap:'0.25rem' }}>
          {steps.map((step) => (
            <div
              key={step.id}
              style={{
                display:'flex', alignItems:'center', gap:'0.5rem',
                padding:'0.28rem 0.5rem', borderRadius:'6px',
                backgroundColor: stepBg(step.status),
                transition:'background-color 0.25s',
              }}
            >
              {/* Státusz kör */}
              <div style={{
                width:'10px', height:'10px', borderRadius:'50%', flexShrink:0,
                backgroundColor: stepColor(step.status),
                boxShadow: step.status === 'active' ? `0 0 0 3px ${stepColor('active')}33` : 'none',
                transition:'all 0.3s',
              }} />

              {/* Label */}
              <span style={{ flex:1, fontSize:'0.82rem', fontWeight: step.status === 'active' ? 700 : 400, color: stepTextColor(step.status) }}>
                {step.label}
              </span>

              {/* Detail */}
              {step.detail && (
                <span style={{ fontSize:'0.7rem', color: step.status === 'error' ? '#ef4444' : '#9ca3af', maxWidth:'200px', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                  {step.detail}
                </span>
              )}

              {/* Spinner / check / x */}
              {step.status === 'active' && (
                <div style={{ width:'12px', height:'12px', borderRadius:'50%', border:'2px solid #bfdbfe', borderTopColor:'#3b82f6', animation:'spin 0.8s linear infinite', flexShrink:0 }} />
              )}
              {step.status === 'done'  && <span style={{ fontSize:'0.7rem', color:'#16a34a', flexShrink:0 }}>✓</span>}
              {step.status === 'error' && <span style={{ fontSize:'0.7rem', color:'#dc2626', flexShrink:0 }}>✗</span>}
            </div>
          ))}
        </div>
      )}

      {/* Hiba üzenet */}
      {errorMsg && !generating && (
        <div style={{ marginTop:'0.5rem', padding:'0.5rem 0.75rem', backgroundColor:'#fef2f2', borderRadius:'6px', border:'1px solid #fecdd3', fontSize:'0.8rem', color:'#dc2626' }}>
          ⚠️ {errorMsg}
        </div>
      )}

      {/* Retry gomb */}
      {!generating && steps.some((s) => s.status === 'error') && (
        <button
          onClick={generate}
          style={{ marginTop:'0.6rem', padding:'0.35rem 0.75rem', borderRadius:'6px', backgroundColor:'#3b82f6', color:'#fff', border:'none', cursor:'pointer', fontSize:'0.8rem', fontWeight:600 }}
        >
          🔄 Újrapróbálás
        </button>
      )}

      {/* Animációk */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
