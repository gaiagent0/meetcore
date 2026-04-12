'use client';

import { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

interface ProviderDef {
  id: string;
  label: string;
  icon: string;
  placeholder: string;
  helpUrl: string;
}

const PROVIDERS: ProviderDef[] = [
  {
    id:          'claude',
    label:       'Claude (Anthropic)',
    icon:        '🧠',
    placeholder: 'sk-ant-api03-...',
    helpUrl:     'https://console.anthropic.com/settings/keys',
  },
  {
    id:          'groq',
    label:       'Groq',
    icon:        '⚡',
    placeholder: 'gsk_...',
    helpUrl:     'https://console.groq.com/keys',
  },
  {
    id:          'openai',
    label:       'OpenAI',
    icon:        '🟢',
    placeholder: 'sk-proj-...',
    helpUrl:     'https://platform.openai.com/api-keys',
  },
  {
    id:          'openrouter',
    label:       'OpenRouter',
    icon:        '🔀',
    placeholder: 'sk-or-v1-...',
    helpUrl:     'https://openrouter.ai/settings/keys',
  },
];

interface KeyState {
  value:   string;
  saved:   boolean;   // key is configured in DB
  visible: boolean;   // show plaintext
  loading: boolean;
  flash:   'idle' | 'ok' | 'error';
}

function initialKeyState(): KeyState {
  return { value: '', saved: false, visible: false, loading: false, flash: 'idle' };
}

export default function ApiKeySettings() {
  const [keys, setKeys] = useState<Record<string, KeyState>>(
    Object.fromEntries(PROVIDERS.map((p) => [p.id, initialKeyState()]))
  );
  const [globalLoading, setGlobalLoading] = useState(true);

  // Load which providers have keys configured
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/settings/api-keys`);
      if (!res.ok) return;
      const data: Record<string, boolean> = await res.json();
      setKeys((prev) => {
        const next = { ...prev };
        for (const [id, configured] of Object.entries(data)) {
          if (next[id]) next[id] = { ...next[id], saved: configured };
        }
        return next;
      });
    } catch { /* backend not running */ }
    finally { setGlobalLoading(false); }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const update = (id: string, patch: Partial<KeyState>) =>
    setKeys((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));

  const handleSave = async (provider: ProviderDef) => {
    const key = keys[provider.id].value.trim();
    if (!key) return;
    update(provider.id, { loading: true, flash: 'idle' });
    try {
      const res = await fetch(`${BACKEND_URL}/settings/api-keys`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ provider: provider.id, api_key: key }),
      });
      if (res.ok) {
        update(provider.id, { loading: false, saved: true, value: '', flash: 'ok' });
        setTimeout(() => update(provider.id, { flash: 'idle' }), 2000);
      } else {
        const err = await res.json().catch(() => ({}));
        console.error('save api key error', err);
        update(provider.id, { loading: false, flash: 'error' });
        setTimeout(() => update(provider.id, { flash: 'idle' }), 2000);
      }
    } catch {
      update(provider.id, { loading: false, flash: 'error' });
      setTimeout(() => update(provider.id, { flash: 'idle' }), 2000);
    }
  };

  const handleClear = async (provider: ProviderDef) => {
    update(provider.id, { loading: true });
    try {
      await fetch(`${BACKEND_URL}/settings/api-keys/${provider.id}`, { method: 'DELETE' });
      update(provider.id, { loading: false, saved: false, value: '', flash: 'idle' });
    } catch {
      update(provider.id, { loading: false });
    }
  };

  if (globalLoading) {
    return (
      <div style={styles.card}>
        <p style={{ color: '#6b7280', fontSize: '0.85rem' }}>API kulcsok betöltése...</p>
      </div>
    );
  }

  return (
    <div style={styles.card}>
      <div style={{ marginBottom: '1rem' }}>
        <h3 style={styles.title}>API kulcsok</h3>
        <p style={styles.subtitle}>
          A kulcsok titkosítva tárolódnak a helyi adatbázisban. Nem kerülnek ki a gépedről.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {PROVIDERS.map((provider) => {
          const state = keys[provider.id];
          return (
            <ProviderRow
              key={provider.id}
              provider={provider}
              state={state}
              onValueChange={(v) => update(provider.id, { value: v })}
              onToggleVisible={() => update(provider.id, { visible: !state.visible })}
              onSave={() => handleSave(provider)}
              onClear={() => handleClear(provider)}
            />
          );
        })}
      </div>

      <p style={{ marginTop: '1rem', fontSize: '0.72rem', color: '#9ca3af' }}>
        Kulcsok nélkül is használható az alkalmazás helyi (NPU / Ollama / NexaAI) providerekkel.
      </p>
    </div>
  );
}

// ── ProviderRow ────────────────────────────────────────────────────────────────

interface ProviderRowProps {
  provider:        ProviderDef;
  state:           KeyState;
  onValueChange:   (v: string) => void;
  onToggleVisible: () => void;
  onSave:          () => void;
  onClear:         () => void;
}

function ProviderRow({ provider, state, onValueChange, onToggleVisible, onSave, onClear }: ProviderRowProps) {
  const flashBg = state.flash === 'ok' ? '#dcfce7' : state.flash === 'error' ? '#fee2e2' : '#f9fafb';

  return (
    <div style={{ ...styles.row, backgroundColor: flashBg }}>
      {/* Provider info */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <span style={{ fontSize: '1.1rem' }}>{provider.icon}</span>
        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{provider.label}</span>
        <span style={{
          fontSize: '0.65rem', fontWeight: 700, padding: '0.1rem 0.45rem',
          borderRadius: '999px', textTransform: 'uppercase',
          backgroundColor: state.saved ? '#dcfce7' : '#f3f4f6',
          color:           state.saved ? '#15803d' : '#6b7280',
        }}>
          {state.saved ? 'Beállítva' : 'Nincs kulcs'}
        </span>
        <a
          href={provider.helpUrl}
          target="_blank"
          rel="noopener noreferrer"
          style={{ marginLeft: 'auto', fontSize: '0.7rem', color: '#3b82f6', textDecoration: 'none' }}
        >
          Kulcs megszerzése →
        </a>
      </div>

      {/* Input sor */}
      <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
        <div style={{ position: 'relative', flex: 1 }}>
          <input
            type={state.visible ? 'text' : 'password'}
            value={state.value}
            onChange={(e) => onValueChange(e.target.value)}
            placeholder={state.saved ? '••••••••••••  (cserélni: új kulcsot írj ide)' : provider.placeholder}
            onKeyDown={(e) => e.key === 'Enter' && state.value.trim() && onSave()}
            style={styles.input}
          />
          <button
            onClick={onToggleVisible}
            title={state.visible ? 'Elrejtés' : 'Megjelenítés'}
            style={styles.eyeBtn}
          >
            {state.visible ? '🙈' : '👁️'}
          </button>
        </div>

        <button
          onClick={onSave}
          disabled={!state.value.trim() || state.loading}
          style={{
            ...styles.btn,
            backgroundColor: state.flash === 'ok' ? '#22c55e' : '#3b82f6',
            opacity: !state.value.trim() || state.loading ? 0.5 : 1,
            cursor:  !state.value.trim() || state.loading ? 'not-allowed' : 'pointer',
          }}
        >
          {state.loading ? '...' : state.flash === 'ok' ? 'Mentve!' : 'Mentés'}
        </button>

        {state.saved && (
          <button
            onClick={onClear}
            disabled={state.loading}
            style={{ ...styles.btn, backgroundColor: '#ef4444', fontSize: '0.75rem' }}
            title="Kulcs törlése"
          >
            Törlés
          </button>
        )}
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = {
  card: {
    border:          '1px solid #e5e7eb',
    borderRadius:    '12px',
    padding:         '1.25rem',
    backgroundColor: '#fff',
  } as React.CSSProperties,

  title: {
    margin:     '0 0 0.25rem',
    fontSize:   '1rem',
    fontWeight: 600,
  } as React.CSSProperties,

  subtitle: {
    margin:    0,
    fontSize:  '0.78rem',
    color:     '#6b7280',
  } as React.CSSProperties,

  row: {
    border:          '1px solid #f0f0f0',
    borderRadius:    '8px',
    padding:         '0.75rem',
    transition:      'background-color 0.3s',
  } as React.CSSProperties,

  input: {
    width:           '100%',
    padding:         '0.45rem 2.2rem 0.45rem 0.65rem',
    border:          '1px solid #d1d5db',
    borderRadius:    '6px',
    fontSize:        '0.82rem',
    fontFamily:      'monospace',
    backgroundColor: '#fafafa',
    boxSizing:       'border-box',
  } as React.CSSProperties,

  eyeBtn: {
    position:        'absolute',
    right:           '0.4rem',
    top:             '50%',
    transform:       'translateY(-50%)',
    background:      'none',
    border:          'none',
    cursor:          'pointer',
    fontSize:        '0.85rem',
    padding:         '0.1rem',
  } as React.CSSProperties,

  btn: {
    padding:         '0.45rem 0.85rem',
    border:          'none',
    borderRadius:    '6px',
    color:           '#fff',
    fontWeight:      600,
    fontSize:        '0.82rem',
    cursor:          'pointer',
    whiteSpace:      'nowrap',
    transition:      'background-color 0.2s',
  } as React.CSSProperties,
} as const;
