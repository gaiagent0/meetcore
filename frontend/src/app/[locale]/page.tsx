'use client';

import { useTranslations } from 'next-intl';
import NPUStatus from '@/components/NPUStatus';
import LocaleSwitcher from '@/components/LocaleSwitcher';
import HelpModal from '@/components/HelpModal';
import TranscriptView from '@/components/TranscriptView';
import AudioLevelMeter from '@/components/AudioLevelMeter';
import ProviderSelector from '@/components/ProviderSelector';
import ApiKeySettings from '@/components/ApiKeySettings';
import { useState, useRef, useCallback, useEffect } from 'react';

type RecordingState = 'idle' | 'recording' | 'paused' | 'processing';

interface TranscriptSegment {
  id: string;
  text: string;
  timestamp: string;
  audioStartTime: number;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

// ASR (átírás) provider: mindig Nexa Parakeet (NPU) ha elérhető
// Ha nem fut, a backend 503-at ad → a user kap egy hasznos üzenetet
const ASR_URL = `${BACKEND_URL}/npu/transcribe`;

export default function Home() {
  const t  = useTranslations('common');
  const tr = useTranslations('recording');
  const ts = useTranslations('summary');
  const tn = useTranslations('npu');
  const th = useTranslations('home');
  const tt = useTranslations('transcript');

  const [recordingState, setRecordingState]       = useState<RecordingState>('idle');
  const [uploadStatus, setUploadStatus]           = useState<string | null>(null);
  const [transcriptSegments, setTranscriptSegments] = useState<TranscriptSegment[]>([]);
  const [errorMessage, setErrorMessage]           = useState<string | null>(null);
  const [selectedProvider, setSelectedProvider]   = useState<string>('ollama');
  const [selectedModel, setSelectedModel]         = useState<string>('');
  const [elapsed, setElapsed]                     = useState(0);
  const [savedMeetingId, setSavedMeetingId]       = useState<string | null>(null);
  const [showHelp, setShowHelp]                   = useState(false);
  const [summaryStatus, setSummaryStatus]         = useState<string | null>(null);
  // Átirat kész → összefoglaló manuálisan indítható
  const [transcriptReady, setTranscriptReady]     = useState(false);
  const [summaryGenerating, setSummaryGenerating] = useState(false);
  const pendingTranscriptRef = useRef<string>('');
  const pendingMeetingIdRef  = useRef<string>('');

  const mediaRecorderRef  = useRef<MediaRecorder | null>(null);
  const chunksRef         = useRef<Blob[]>([]);
  const fileInputRef      = useRef<HTMLInputElement | null>(null);
  const streamRef         = useRef<MediaStream | null>(null);
  const timerRef          = useRef<ReturnType<typeof setInterval> | null>(null);
  const recordingStartRef = useRef<number>(0);

  useEffect(() => {
    if (recordingState === 'recording') {
      timerRef.current = setInterval(() =>
        setElapsed(Math.floor((Date.now() - recordingStartRef.current) / 1000)), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [recordingState]);

  const startRecording = useCallback(async () => {
    try {
      setErrorMessage(null);
      setSavedMeetingId(null);
      setSummaryStatus(null);
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        await transcribeAudio(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      recordingStartRef.current = Date.now();
      setRecordingState('recording');
    } catch (e: any) {
      setErrorMessage(`Mikrofon hiba: ${e.message}`);
    }
  }, []);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && recordingState === 'recording') {
      mediaRecorderRef.current.stop();
      setRecordingState('processing');
    }
  }, [recordingState]);

  const handleFileUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadStatus('Fájl feldolgozása...');
    setErrorMessage(null);
    setSavedMeetingId(null);
    setSummaryStatus(null);
    try {
      await transcribeAudio(file);
    } catch (e: any) {
      setErrorMessage(e.message);
    } finally {
      setUploadStatus(null);
    }
  }, [selectedProvider, selectedModel]);

  // ── 1+2: Átírás + mentés (auto, felvétel/upload után) ───────────────────────
  const transcribeAudio = async (audioBlob: Blob) => {
    try {
      setTranscriptReady(false);
      setSummaryStatus('🎙️ Átírás folyamatban (Parakeet NPU)...');
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.webm');
      formData.append('language', 'hu');

      const transResp = await fetch(ASR_URL, { method: 'POST', body: formData });

      if (!transResp.ok) {
        const errData = await transResp.json().catch(() => ({}));
        const errDetail = errData.detail || `HTTP ${transResp.status}`;
        if (transResp.status === 500 || transResp.status === 503) {
          setErrorMessage(
            `⚠️ Átírás sikertelen: ${errDetail}\n` +
            `Megoldás: nexa serve NexaAI/parakeet-tdt-0.6b-v3-npu`
          );
          setRecordingState('idle');
          return;
        }
        throw new Error(`Átírási hiba: ${errDetail}`);
      }

      const transData = await transResp.json();
      const transcript = transData.text ?? transData.transcript ?? '';

      if (!transcript.trim()) {
        setErrorMessage('Az átírás üres eredményt adott. Ellenőrizd a mikrofont.');
        setRecordingState('idle');
        return;
      }

      const segment: TranscriptSegment = {
        id: `t-${Date.now()}`,
        text: transcript,
        timestamp: new Date().toLocaleTimeString(),
        audioStartTime: recordingStartRef.current ? (Date.now() - recordingStartRef.current) / 1000 : 0,
      };
      setTranscriptSegments((prev) => [...prev, segment]);
      setSummaryStatus(`✅ Átírás kész (${transcript.length} karakter) – Mentés...`);

      // ── 2. Mentés ────────────────────────────────────────────────────────
      const saveResp = await fetch(`${BACKEND_URL}/save-transcript`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Új megbeszélés', transcript }),
      });

      const saved = saveResp.ok ? await saveResp.json() : { meeting_id: `local-${Date.now()}` };
      setSavedMeetingId(saved.meeting_id);
      pendingTranscriptRef.current = transcript;
      pendingMeetingIdRef.current  = saved.meeting_id;

      // Átírás kész → felhasználó választ providert és indítja manuálisan
      setSummaryStatus(`✅ Átírás mentve. Válassz providert és kattints az Összefoglaló generálása gombra.`);
      setTranscriptReady(true);

    } catch (e: any) {
      setErrorMessage(`Hiba: ${e.message}`);
      setSummaryStatus(null);
    } finally {
      setRecordingState('idle');
    }
  };

  // ── 3: Összefoglaló generálás (manuális gomb) ─────────────────────────────
  const generateSummary = async () => {
    if (!pendingTranscriptRef.current || summaryGenerating) return;
    setSummaryGenerating(true);
    setErrorMessage(null);
    setSummaryStatus(`☁️ Összefoglaló generálása (${selectedProvider} / ${selectedModel || 'auto'})...`);
    try {
      const sumResp = await fetch(`${BACKEND_URL}/process-transcript`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          meeting_id: pendingMeetingIdRef.current,
          transcript_text: pendingTranscriptRef.current,
          title: 'Új megbeszélés',
          model: selectedProvider,
          model_name: selectedModel,
        }),
      });

      if (!sumResp.ok) {
        const errData = await sumResp.json().catch(() => ({}));
        setSummaryStatus(`❌ Összefoglaló hiba: ${errData.detail || sumResp.status}`);
        setErrorMessage(
          `Összefoglaló generálás sikertelen (${selectedProvider}).\n` +
          `Hiba: ${errData.detail || 'Ismeretlen hiba'}\n` +
          `Válassz másik providert és próbáld újra.`
        );
        return;
      }

      const sumData = await sumResp.json();
      if (sumData.results?.length > 0) {
        await fetch(`${BACKEND_URL}/save-meeting-summary`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            meeting_id: pendingMeetingIdRef.current,
            summary: JSON.parse(sumData.results[0]),
          }),
        });
        setSummaryStatus(`✅ Összefoglaló kész! (${sumData.chunks_ok}/${sumData.chunks_total} chunk)`);
        setTranscriptReady(false);
      } else {
        setSummaryStatus('⚠️ Összefoglaló üres eredményt adott. Próbálj másik providert.');
      }
    } catch (e: any) {
      setErrorMessage(`Hiba: ${e.message}`);
      setSummaryStatus(null);
    } finally {
      setSummaryGenerating(false);
    }
  };

  const fmtTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;

  return (
    <main style={{ fontFamily: 'system-ui, -apple-system, sans-serif', padding: '1.5rem', maxWidth: '960px', margin: '0 auto' }}>

      {/* Header */}
      <header style={{ marginBottom: '1.5rem', borderBottom: '2px solid #e5e7eb', paddingBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.8rem', fontWeight: 700 }}>{th('title')}</h1>
          <p style={{ margin: '0.2rem 0 0', color: '#6b7280', fontSize: '0.875rem' }}>{th('subtitle')}</p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <a href="/hu/meetings" style={{ fontSize: '0.85rem', color: '#3b82f6', textDecoration: 'none', padding: '0.35rem 0.75rem', border: '1px solid #93c5fd', borderRadius: '6px' }}>
            📋 {th('meetingsLink')}
          </a>
          <button onClick={() => setShowHelp(true)}
            style={{ fontSize: '0.85rem', color: '#374151', padding: '0.35rem 0.75rem', border: '1px solid #d1d5db', borderRadius: '6px', backgroundColor: '#fff', cursor: 'pointer' }}>
            ❓ Útmutató
          </button>
          <LocaleSwitcher />
        </div>
      </header>

      {/* Provider státusz */}
      <section style={{ marginBottom: '1.5rem' }}>
        <NPUStatus />
      </section>

      {/* Fő layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '1.5rem', alignItems: 'start' }}>

        {/* Bal: felvétel + átirat */}
        <div>
          {/* Felvétel */}
          <section style={{ marginBottom: '1.5rem', padding: '1.25rem', borderRadius: '12px', backgroundColor: '#f9fafb', border: '1px solid #e5e7eb' }}>
            <h2 style={{ marginTop: 0, fontSize: '1.1rem' }}>{th('recordingSection')}</h2>

            <p style={{ color: '#6b7280', marginBottom: '0.75rem', fontSize: '0.9rem' }}>
              {recordingState === 'idle' ? 'Nincs aktív felvétel' :
               recordingState === 'recording' ? `Felvétel folyamatban... ${fmtTime(elapsed)}` :
               recordingState === 'processing' ? '⏳ Feldolgozás...' : ''}
            </p>

            {recordingState === 'recording' && streamRef.current && (
              <div style={{ marginBottom: '0.75rem', padding: '0.75rem', backgroundColor: '#fff', borderRadius: '8px', border: '1px solid #e5e7eb' }}>
                <AudioLevelMeter stream={streamRef.current} isActive barCount={24} />
              </div>
            )}

            {/* Státusz üzenet */}
            {summaryStatus && (
              <div style={{ marginBottom: '0.75rem', padding: '0.6rem 0.9rem', backgroundColor: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: '8px', fontSize: '0.85rem', color: '#0369a1', whiteSpace: 'pre-line' }}>
                {summaryStatus}
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
              {recordingState === 'idle' && (
                <button onClick={startRecording}
                  style={{ padding: '0.65rem 1.25rem', borderRadius: '8px', backgroundColor: '#dc2626', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600 }}>
                  🎙️ {tr('start')}
                </button>
              )}
              {recordingState === 'recording' && (
                <button onClick={stopRecording}
                  style={{ padding: '0.65rem 1.25rem', borderRadius: '8px', backgroundColor: '#4b5563', color: '#fff', border: 'none', cursor: 'pointer' }}>
                  ⏹ {tr('stop')}
                </button>
              )}
              {recordingState === 'processing' && (
                <span style={{ padding: '0.65rem 1.25rem', color: '#6b7280' }}>⏳ {ts('generating')}</span>
              )}
            </div>

            {/* Fájl feltöltés */}
            <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid #e5e7eb' }}>
              <p style={{ marginBottom: '0.4rem', fontWeight: 600, fontSize: '0.875rem' }}>{th('uploadLabel')}</p>
              <input ref={fileInputRef} type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg,.webm" onChange={handleFileUpload} />
              {uploadStatus && <p style={{ color: '#6b7280', marginTop: '0.4rem', fontSize: '0.85rem' }}>{uploadStatus}</p>}
            </div>
          </section>

          {/* Összefoglaló gomb — átirat kész, de generálás még nem indult */}
          {transcriptReady && (
            <div style={{ marginBottom: '1rem', padding: '1rem', backgroundColor: '#fffbeb', border: '1px solid #fde68a', borderRadius: '10px' }}>
              <p style={{ margin: '0 0 0.75rem', fontSize: '0.875rem', color: '#92400e', fontWeight: 600 }}>
                📄 Átirat kész — válassz AI providert (jobb oldal), majd indítsd el:
              </p>
              <button
                onClick={generateSummary}
                disabled={summaryGenerating}
                style={{
                  padding: '0.65rem 1.4rem', borderRadius: '8px', border: 'none', cursor: summaryGenerating ? 'not-allowed' : 'pointer',
                  backgroundColor: summaryGenerating ? '#9ca3af' : '#2563eb', color: '#fff', fontWeight: 700, fontSize: '0.95rem',
                  transition: 'background-color 0.15s',
                }}>
                {summaryGenerating
                  ? '⏳ Generálás...'
                  : `✨ Összefoglaló generálása — ${selectedProvider}${selectedModel ? ` / ${selectedModel}` : ''}`}
              </button>
            </div>
          )}

          {/* Sikeres mentés */}
          {savedMeetingId && !transcriptReady && (
            <div style={{ marginBottom: '1rem', padding: '0.75rem 1rem', backgroundColor: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#166534', fontSize: '0.875rem' }}>✅ Meeting összefoglalva</span>
              <a href={`/hu/meetings/${savedMeetingId}`} style={{ fontSize: '0.8rem', color: '#15803d', fontWeight: 600, textDecoration: 'none' }}>
                Megnyitás →
              </a>
            </div>
          )}

          {/* Hibaüzenet */}
          {errorMessage && (
            <div style={{ marginBottom: '1rem', padding: '0.75rem 1rem', backgroundColor: '#fff1f2', border: '1px solid #fecdd3', borderRadius: '8px', color: '#9f1239', fontSize: '0.85rem', whiteSpace: 'pre-line' }}>
              <strong>Hiba:</strong> {errorMessage}
            </div>
          )}

          {/* Átirat */}
          <section style={{ padding: '1.25rem', borderRadius: '12px', backgroundColor: '#fff', border: '1px solid #e5e7eb' }}>
            <h2 style={{ marginTop: 0, fontSize: '1.1rem' }}>{tt('title')}</h2>
            <TranscriptView
              segments={transcriptSegments}
              isRecording={recordingState === 'recording'}
              isPaused={recordingState === 'paused'}
              isProcessing={recordingState === 'processing'}
            />
          </section>
        </div>

        {/* Jobb: Provider választó + API kulcsok */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <ProviderSelector
            onProviderChange={setSelectedProvider}
            onModelChange={(_, m) => setSelectedModel(m)}
          />
          <ApiKeySettings />
        </div>
      </div>

      {/* Footer */}
      <footer style={{ marginTop: '2rem', paddingTop: '1rem', borderTop: '1px solid #e5e7eb', fontSize: '0.8rem', color: '#9ca3af' }}>
        Backend: <a href={`${BACKEND_URL}/docs`} target="_blank" rel="noopener noreferrer" style={{ color: '#6b7280' }}>API docs</a>
        &nbsp;·&nbsp; NPU API: http://localhost:8912
        &nbsp;·&nbsp; ASR: Nexa Parakeet :18181
        &nbsp;·&nbsp; LLM: {selectedProvider} / {selectedModel}
      </footer>

      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
    </main>
  );
}
