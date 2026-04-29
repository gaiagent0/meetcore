'use client';

import { useState, useEffect, useRef, use } from 'react';
import SummaryGeneratorPanel from '@/components/SummaryGeneratorPanel';
import TtsPlayer from '@/components/TtsPlayer';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

interface Block { id: string; type: string; content: string; color?: string; }
interface SummarySection { title: string; blocks: Block[]; }
type SummaryData = Record<string, SummarySection | { meeting_name: string; sections: any[] }>;

interface ChatMessage { role: 'user' | 'assistant'; content: string; }

const SUMMARY_SECTIONS: { key: string; icon: string }[] = [
  { key: 'People',               icon: '👥' },
  { key: 'SessionSummary',       icon: '📝' },
  { key: 'CriticalDeadlines',    icon: '⏰' },
  { key: 'KeyItemsDecisions',    icon: '🎯' },
  { key: 'ImmediateActionItems', icon: '✅' },
  { key: 'NextSteps',            icon: '→'  },
];

const CHAT_PROVIDERS = [
  { value: 'ollama',     label: 'Ollama' },
  { value: 'npu',        label: 'NPU' },
  { value: 'nexa',       label: 'NexaAI' },
  { value: 'groq',       label: 'Groq' },
  { value: 'openai',     label: 'OpenAI' },
  { value: 'claude',     label: 'Claude' },
  { value: 'openrouter', label: 'OpenRouter' },
];

export default function MeetingDetailPage({ params }: { params: Promise<{ locale: string; id: string }> }) {
  const { locale, id: meetingId } = use(params);
  const [meeting, setMeeting]           = useState<any>(null);
  const [summaryData, setSummaryData]   = useState<SummaryData | null>(null);
  const [transcript, setTranscript]     = useState('');
  const [loading, setLoading]           = useState(true);
  const [showTranscript, setShowTranscript] = useState(false);

  const [chatHistory, setChatHistory]   = useState<ChatMessage[]>([]);
  const [question, setQuestion]         = useState('');
  const [chatLoading, setChatLoading]   = useState(false);
  const [chatProvider, setChatProvider] = useState('ollama');
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadMeeting(meetingId);
  }, [meetingId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  const loadMeeting = async (id: string) => {
    try {
      const r = await fetch(`${BACKEND_URL}/get-summary/${id}`);
      if (!r.ok) { setLoading(false); return; }
      const data = await r.json();
      setMeeting(data);
      if (data.summary?.summary_json) {
        try { setSummaryData(JSON.parse(data.summary.summary_json)); } catch { /* invalid JSON */ }
      }
      const texts = (data.transcripts ?? []).map((t: any) => t.text).filter(Boolean);
      setTranscript(texts.join('\n\n'));
    } catch { /* silent */ }
    setLoading(false);
  };

  const sendChat = async () => {
    if (!question.trim() || chatLoading) return;
    const q = question.trim();
    setQuestion('');
    setChatLoading(true);
    const updated: ChatMessage[] = [...chatHistory, { role: 'user', content: q }];
    setChatHistory(updated);

    try {
      const r = await fetch(`${BACKEND_URL}/chat/${meetingId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, provider: chatProvider, history: chatHistory }),
      });
      if (r.ok) {
        const data = await r.json();
        setChatHistory([...updated, { role: 'assistant', content: data.answer }]);
      } else {
        const err = await r.json().catch(() => ({}));
        setChatHistory([...updated, { role: 'assistant', content: `❌ Hiba: ${err.detail ?? r.status}` }]);
      }
    } catch (e: any) {
      setChatHistory([...updated, { role: 'assistant', content: `❌ ${e.message}` }]);
    }
    setChatLoading(false);
  };

  const renderSection = (key: string, icon: string) => {
    const section = summaryData?.[key] as SummarySection | undefined;
    if (!section?.blocks?.length) return null;
    return (
      <div key={key} style={{ marginBottom: '0.75rem', padding: '0.85rem 1rem', backgroundColor: '#f9fafb', borderRadius: '10px', border: '1px solid #e5e7eb' }}>
        <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.875rem', fontWeight: 700, color: '#374151' }}>
          {icon} {section.title}
        </h3>
        <ul style={{ margin: 0, paddingLeft: '1.15rem', display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          {section.blocks.map(b => (
            <li key={b.id} style={{ fontSize: '0.85rem', color: '#4b5563', lineHeight: 1.5 }}>{b.content}</li>
          ))}
        </ul>
      </div>
    );
  };

  const formatDate = (s: string) => {
    try { return new Date(s).toLocaleString('hu-HU'); } catch { return s; }
  };

  const summaryText = summaryData
    ? SUMMARY_SECTIONS
        .flatMap(({ key }) => ((summaryData[key] as SummarySection)?.blocks ?? []).map(b => b.content))
        .join('. ')
    : '';

  if (loading) {
    return (
      <main style={{ fontFamily: 'system-ui', padding: '2rem', textAlign: 'center', color: '#6b7280' }}>
        Betöltés...
      </main>
    );
  }

  if (!meeting) {
    return (
      <main style={{ fontFamily: 'system-ui', padding: '2rem', textAlign: 'center' }}>
        <p style={{ color: '#ef4444', marginBottom: '1rem' }}>Meeting nem található.</p>
        <a href={`/${locale}/meetings`} style={{ color: '#3b82f6', fontSize: '0.9rem' }}>← Vissza a listához</a>
      </main>
    );
  }

  return (
    <main style={{ fontFamily: 'system-ui, -apple-system, sans-serif', padding: '1.5rem', maxWidth: '960px', margin: '0 auto' }}>

      {/* Header */}
      <header style={{ marginBottom: '1.5rem', borderBottom: '2px solid #e5e7eb', paddingBottom: '1rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h1 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {meeting.title || 'Névtelen meeting'}
            </h1>
            <p style={{ margin: '0.2rem 0 0', color: '#9ca3af', fontSize: '0.8rem' }}>
              {formatDate(meeting.created_at)}
              {meeting.summary?.provider && (
                <span style={{ marginLeft: '0.5rem' }}>
                  · {meeting.summary.provider}{meeting.summary.model_name ? `/${meeting.summary.model_name}` : ''}
                </span>
              )}
            </p>
          </div>
          <a
            href={`/${locale}/meetings`}
            style={{ fontSize: '0.85rem', color: '#3b82f6', textDecoration: 'none', padding: '0.35rem 0.75rem', border: '1px solid #93c5fd', borderRadius: '6px', flexShrink: 0 }}>
            ← Lista
          </a>
        </div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 330px', gap: '1.5rem', alignItems: 'start' }}>

        {/* Bal: összefoglaló + generátor + átirat */}
        <div>

          {/* Összefoglaló szekciók */}
          {summaryData ? (
            <section style={{ marginBottom: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <h2 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700 }}>Összefoglaló</h2>
                {summaryText && <TtsPlayer text={summaryText} backendUrl={BACKEND_URL} />}
              </div>
              {SUMMARY_SECTIONS.map(({ key, icon }) => renderSection(key, icon))}

              {/* MeetingNotes */}
              {(() => {
                const notes = summaryData.MeetingNotes as { meeting_name?: string; sections?: any[] } | undefined;
                if (!notes?.sections?.length) return null;
                return (
                  <div style={{ marginBottom: '0.75rem', padding: '0.85rem 1rem', backgroundColor: '#f9fafb', borderRadius: '10px', border: '1px solid #e5e7eb' }}>
                    <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.875rem', fontWeight: 700, color: '#374151' }}>
                      📒 Megbeszélés jegyzetek
                    </h3>
                    {notes.sections.map((s: any, i: number) => (
                      <div key={i} style={{ marginBottom: '0.4rem' }}>
                        {s.title && <p style={{ margin: '0 0 0.15rem', fontWeight: 600, fontSize: '0.8rem', color: '#374151' }}>{s.title}</p>}
                        {s.content && <p style={{ margin: 0, fontSize: '0.8rem', color: '#6b7280', lineHeight: 1.5 }}>{s.content}</p>}
                      </div>
                    ))}
                  </div>
                );
              })()}
            </section>
          ) : (
            <div style={{ padding: '1.25rem', backgroundColor: '#fffbeb', border: '1px solid #fde68a', borderRadius: '10px', marginBottom: '1.25rem', color: '#92400e', fontSize: '0.875rem' }}>
              Ehhez a meetinghez még nincs összefoglaló — generálj egyet lent!
            </div>
          )}

          {/* Összefoglaló generátor */}
          <SummaryGeneratorPanel
            meetingId={meetingId}
            transcript={transcript}
            hasSummary={!!summaryData}
            onSummaryReady={(s) => {
              setSummaryData(s as SummaryData);
              loadMeeting(meetingId);
            }}
          />

          {/* Átirat (összecsukható) */}
          {transcript && (
            <section style={{ marginTop: '1.25rem', padding: '1rem', backgroundColor: '#fff', borderRadius: '10px', border: '1px solid #e5e7eb' }}>
              <button
                onClick={() => setShowTranscript(v => !v)}
                style={{ display: 'flex', justifyContent: 'space-between', width: '100%', background: 'none', border: 'none', cursor: 'pointer', padding: 0, alignItems: 'center' }}>
                <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 600, color: '#374151' }}>📄 Átirat</h2>
                <span style={{ fontSize: '0.78rem', color: '#9ca3af' }}>{showTranscript ? '▲ Összecsuk' : '▼ Kibont'}</span>
              </button>
              {showTranscript && (
                <div style={{ marginTop: '0.75rem', padding: '0.75rem', backgroundColor: '#f9fafb', borderRadius: '8px', fontSize: '0.82rem', lineHeight: 1.65, color: '#374151', maxHeight: '320px', overflowY: 'auto', whiteSpace: 'pre-wrap' }}>
                  {transcript}
                </div>
              )}
            </section>
          )}
        </div>

        {/* Jobb: Chat panel */}
        <div style={{ position: 'sticky', top: '1rem' }}>
          <div style={{ padding: '1rem', backgroundColor: '#fff', borderRadius: '12px', border: '1px solid #e5e7eb' }}>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
              <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>💬 Chat</h2>
              <select
                value={chatProvider}
                onChange={e => setChatProvider(e.target.value)}
                style={{ padding: '0.25rem 0.4rem', borderRadius: '5px', border: '1px solid #d1d5db', fontSize: '0.75rem', color: '#374151', backgroundColor: '#fff' }}>
                {CHAT_PROVIDERS.map(p => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>

            {/* Előzmény */}
            <div style={{ height: '340px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '0.75rem', padding: '0.5rem', backgroundColor: '#f9fafb', borderRadius: '8px', border: '1px solid #e5e7eb' }}>
              {chatHistory.length === 0 && (
                <p style={{ color: '#9ca3af', fontSize: '0.78rem', textAlign: 'center', margin: 'auto', lineHeight: 1.5 }}>
                  Kérdezz a meetingről!<br />
                  <span style={{ fontSize: '0.72rem' }}>pl. &ldquo;Ki vett részt?&rdquo;, &ldquo;Mik a teendők?&rdquo;</span>
                </p>
              )}
              {chatHistory.map((msg, i) => (
                <div
                  key={i}
                  style={{
                    padding: '0.45rem 0.65rem',
                    borderRadius: '8px',
                    backgroundColor: msg.role === 'user' ? '#eff6ff' : '#f0fdf4',
                    border: `1px solid ${msg.role === 'user' ? '#bfdbfe' : '#bbf7d0'}`,
                    fontSize: '0.8rem',
                    lineHeight: 1.55,
                    alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '95%',
                    color: '#111827',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}>
                  {msg.content}
                </div>
              ))}
              {chatLoading && (
                <div style={{ padding: '0.45rem 0.65rem', borderRadius: '8px', backgroundColor: '#f0fdf4', border: '1px solid #bbf7d0', fontSize: '0.78rem', color: '#6b7280', alignSelf: 'flex-start' }}>
                  ⏳ Válasz generálása…
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Input */}
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <textarea
                value={question}
                onChange={e => setQuestion(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
                placeholder="Kérdés… (Enter küld, Shift+Enter új sor)"
                rows={2}
                disabled={chatLoading}
                style={{ flex: 1, padding: '0.5rem', borderRadius: '7px', border: '1px solid #d1d5db', fontSize: '0.8rem', resize: 'none', fontFamily: 'inherit', outline: 'none' }}
              />
              <button
                onClick={sendChat}
                disabled={chatLoading || !question.trim()}
                style={{
                  padding: '0 0.85rem',
                  borderRadius: '7px',
                  backgroundColor: chatLoading || !question.trim() ? '#e5e7eb' : '#2563eb',
                  color: chatLoading || !question.trim() ? '#9ca3af' : '#fff',
                  border: 'none',
                  cursor: chatLoading || !question.trim() ? 'not-allowed' : 'pointer',
                  fontWeight: 700,
                  fontSize: '1rem',
                }}>
                →
              </button>
            </div>

            {chatHistory.length > 0 && (
              <button
                onClick={() => setChatHistory([])}
                style={{ marginTop: '0.5rem', fontSize: '0.72rem', color: '#9ca3af', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                Előzmény törlése
              </button>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
