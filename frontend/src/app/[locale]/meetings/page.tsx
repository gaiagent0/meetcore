'use client';

import { useState, useEffect, useCallback, use } from 'react';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

interface Meeting {
  id: string;
  title: string;
  created_at: string;
}

interface SearchResult extends Meeting {
  matchContext?: string;
}

export default function MeetingsPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    loadMeetings();
  }, []);

  const loadMeetings = async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/get-meetings`);
      if (r.ok) {
        const data = await r.json();
        setMeetings(data.meetings ?? []);
      }
    } catch { /* silent */ }
    setLoading(false);
  };

  const handleSearch = useCallback(async () => {
    if (!searchQ.trim()) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const r = await fetch(`${BACKEND_URL}/search-meetings?q=${encodeURIComponent(searchQ)}`);
      if (r.ok) {
        const data = await r.json();
        setSearchResults(data.results ?? []);
      }
    } catch { /* silent */ }
    setSearching(false);
  }, [searchQ]);

  const handleDelete = async (id: string) => {
    if (!confirm('Biztosan törlöd ezt a meetinget? Az összes kapcsolódó adat törlődik.')) return;
    setDeleting(id);
    try {
      const r = await fetch(`${BACKEND_URL}/delete-meeting/${id}`, { method: 'DELETE' });
      if (r.ok) {
        setMeetings(prev => prev.filter(m => m.id !== id));
        setSearchResults(prev => prev.filter(m => m.id !== id));
      }
    } catch { /* silent */ }
    setDeleting(null);
  };

  const formatDate = (s: string) => {
    try { return new Date(s).toLocaleString('hu-HU'); } catch { return s; }
  };

  const displayed: SearchResult[] = searchQ.trim() ? searchResults : meetings;

  return (
    <main style={{ fontFamily: 'system-ui, -apple-system, sans-serif', padding: '1.5rem', maxWidth: '800px', margin: '0 auto' }}>

      <header style={{ marginBottom: '1.5rem', borderBottom: '2px solid #e5e7eb', paddingBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '1.6rem', fontWeight: 700 }}>📋 Meetingek</h1>
          <p style={{ margin: '0.2rem 0 0', color: '#6b7280', fontSize: '0.875rem' }}>Korábbi megbeszélések és összefoglalók</p>
        </div>
        <a href={`/${locale}`} style={{ fontSize: '0.85rem', color: '#3b82f6', textDecoration: 'none', padding: '0.35rem 0.75rem', border: '1px solid #93c5fd', borderRadius: '6px' }}>
          ← Főoldal
        </a>
      </header>

      {/* Keresés */}
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem' }}>
        <input
          value={searchQ}
          onChange={e => setSearchQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="Keresés az összefoglalókban..."
          style={{ flex: 1, padding: '0.55rem 0.75rem', borderRadius: '8px', border: '1px solid #d1d5db', fontSize: '0.9rem', outline: 'none' }}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{ padding: '0.55rem 1rem', borderRadius: '8px', backgroundColor: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem', opacity: searching ? 0.7 : 1 }}>
          {searching ? '...' : '🔍 Keresés'}
        </button>
        {searchQ && (
          <button
            onClick={() => { setSearchQ(''); setSearchResults([]); }}
            style={{ padding: '0.55rem 0.75rem', borderRadius: '8px', border: '1px solid #d1d5db', backgroundColor: '#fff', cursor: 'pointer', fontSize: '0.85rem' }}>
            ✕
          </button>
        )}
      </div>

      {/* Találatok száma kereséskor */}
      {searchQ.trim() && !searching && (
        <p style={{ marginBottom: '0.75rem', fontSize: '0.8rem', color: '#6b7280' }}>
          {searchResults.length} találat: &ldquo;{searchQ}&rdquo;
        </p>
      )}

      {/* Lista */}
      {loading && (
        <p style={{ color: '#6b7280', textAlign: 'center', padding: '2rem' }}>Betöltés...</p>
      )}

      {!loading && displayed.length === 0 && (
        <div style={{ padding: '2.5rem', textAlign: 'center', color: '#9ca3af', backgroundColor: '#f9fafb', borderRadius: '12px', border: '1px dashed #e5e7eb' }}>
          {searchQ.trim() ? 'Nincs találat a keresésre.' : 'Még nincs mentett meeting. Rögzíts vagy tölts fel hangfelvételt a főoldalon!'}
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
        {displayed.map((m) => (
          <div
            key={m.id}
            style={{ padding: '1rem 1.25rem', borderRadius: '10px', backgroundColor: '#fff', border: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', transition: 'border-color 0.15s' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <a
                href={`/${locale}/meetings/${m.id}`}
                style={{ fontWeight: 600, fontSize: '0.95rem', color: '#111827', textDecoration: 'none', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {m.title || 'Névtelen meeting'}
              </a>
              <span style={{ fontSize: '0.775rem', color: '#9ca3af' }}>{formatDate(m.created_at)}</span>
              {m.matchContext && (
                <p style={{ margin: '0.3rem 0 0', fontSize: '0.775rem', color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  …{m.matchContext}…
                </p>
              )}
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', flexShrink: 0 }}>
              <a
                href={`/${locale}/meetings/${m.id}`}
                style={{ fontSize: '0.8rem', color: '#3b82f6', textDecoration: 'none', padding: '0.3rem 0.7rem', border: '1px solid #93c5fd', borderRadius: '6px' }}>
                Megnyitás →
              </a>
              <button
                onClick={() => handleDelete(m.id)}
                disabled={deleting === m.id}
                style={{ fontSize: '0.8rem', color: '#ef4444', padding: '0.3rem 0.6rem', border: '1px solid #fecaca', borderRadius: '6px', backgroundColor: '#fff', cursor: deleting === m.id ? 'not-allowed' : 'pointer', opacity: deleting === m.id ? 0.5 : 1 }}>
                {deleting === m.id ? '...' : '🗑'}
              </button>
            </div>
          </div>
        ))}
      </div>

    </main>
  );
}
