'use client';

import { useCallback, useEffect, useState } from 'react';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

interface ServiceStatus {
  label: string;
  model: string;
  port: number;
  managed: boolean;
  online: boolean;
}

type ServicesState = Record<string, ServiceStatus>;
type ActionState   = Record<string, 'starting' | 'stopping' | null>;

const SERVICE_ICONS: Record<string, string> = {
  asr:        '🎙️',
  llm:        '🧠',
  multimodal: '👁️',
};

export default function NexaServicePanel() {
  const [services,  setServices]  = useState<ServicesState | null>(null);
  const [actions,   setActions]   = useState<ActionState>({});
  const [error,     setError]     = useState<string | null>(null);
  const [open,      setOpen]      = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetch(`${BACKEND_URL}/npu/nexa/services`, { signal: AbortSignal.timeout(6000) });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setServices(await r.json());
      setError(null);
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 10_000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  const handleAction = async (name: string, action: 'start' | 'stop') => {
    setActions(a => ({ ...a, [name]: action === 'start' ? 'starting' : 'stopping' }));
    try {
      await fetch(`${BACKEND_URL}/npu/nexa/services/${name}/${action}`, { method: 'POST', signal: AbortSignal.timeout(8000) });
      // Kis várakozás, utána frissítjük a státuszt
      setTimeout(fetchStatus, 1500);
    } catch { /* silent — fetchStatus majd jelzi */ }
    setActions(a => ({ ...a, [name]: null }));
  };

  const onlineCount = services ? Object.values(services).filter(s => s.online).length : 0;
  const totalCount  = services ? Object.keys(services).length : 3;

  return (
    <div style={{ marginTop: '0.75rem' }}>
      {/* Összecsukható fejléc */}
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.5rem',
          background: 'none', border: 'none', cursor: 'pointer',
          padding: '0.3rem 0', fontSize: '0.8rem', color: '#374151',
        }}
      >
        <span style={{ fontSize: '0.65rem', color: '#9ca3af' }}>{open ? '▲' : '▼'}</span>
        <span style={{ fontWeight: 600 }}>⚡ Nexa Services</span>
        {services && (
          <span style={{
            padding: '0.1rem 0.45rem', borderRadius: '10px', fontSize: '0.7rem', fontWeight: 700,
            backgroundColor: onlineCount > 0 ? '#f0fdf4' : '#f9fafb',
            color:           onlineCount > 0 ? '#166534'  : '#9ca3af',
            border:          `1px solid ${onlineCount > 0 ? '#bbf7d0' : '#e5e7eb'}`,
          }}>
            {onlineCount}/{totalCount}
          </span>
        )}
      </button>

      {open && (
        <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          {error && (
            <div style={{ fontSize: '0.75rem', color: '#dc2626', padding: '0.35rem 0.6rem', backgroundColor: '#fee2e2', borderRadius: '6px' }}>
              {error}
            </div>
          )}

          {!services && !error && (
            <div style={{ fontSize: '0.75rem', color: '#9ca3af' }}>Betöltés...</div>
          )}

          {services && Object.entries(services).map(([name, svc]) => {
            const busy = actions[name];
            const icon = SERVICE_ICONS[name] ?? '🔧';
            const isOn = svc.online;

            return (
              <div
                key={name}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.6rem',
                  padding: '0.5rem 0.75rem', borderRadius: '8px',
                  backgroundColor: isOn ? '#f0fdf4' : '#f9fafb',
                  border: `1px solid ${isOn ? '#bbf7d0' : '#e5e7eb'}`,
                }}
              >
                {/* Status dot */}
                <span style={{
                  width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
                  backgroundColor: isOn ? '#22c55e' : '#d1d5db',
                }} />

                {/* Info */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#111827' }}>
                    {icon} {svc.label}
                    {svc.managed && isOn && (
                      <span style={{ marginLeft: '0.4rem', fontSize: '0.65rem', padding: '0.1rem 0.35rem', backgroundColor: '#eff6ff', color: '#1d4ed8', borderRadius: '4px', border: '1px solid #bfdbfe' }}>
                        managed
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.72rem', color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    :{svc.port} · {svc.model}
                  </div>
                </div>

                {/* Start / Stop gomb */}
                {isOn ? (
                  <button
                    onClick={() => handleAction(name, 'stop')}
                    disabled={!!busy}
                    style={btnStyle('#fee2e2', '#ef4444', '#fecdd3', !!busy)}
                  >
                    {busy === 'stopping' ? '⏳' : '■ Stop'}
                  </button>
                ) : (
                  <button
                    onClick={() => handleAction(name, 'start')}
                    disabled={!!busy}
                    style={btnStyle('#eff6ff', '#2563eb', '#bfdbfe', !!busy)}
                  >
                    {busy === 'starting' ? '⏳' : '▶ Start'}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function btnStyle(bg: string, color: string, border: string, disabled: boolean): React.CSSProperties {
  return {
    padding: '0.25rem 0.6rem', borderRadius: '6px', fontSize: '0.75rem', fontWeight: 600,
    backgroundColor: disabled ? '#f3f4f6' : bg,
    color:           disabled ? '#9ca3af'  : color,
    border:          `1px solid ${disabled ? '#e5e7eb' : border}`,
    cursor:          disabled ? 'not-allowed' : 'pointer',
    flexShrink:      0,
    whiteSpace:      'nowrap',
  };
}
