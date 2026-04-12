'use client';

import { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

interface ProviderInfo {
  online: boolean;
  models: string[];
  url: string;
  error?: string;
}

interface NpuStatus {
  providers: Record<string, ProviderInfo>;
  genie_api: { url: string; online: boolean; models: string[] };
  whisper: {
    backend: string;
    cpp_exe_found: boolean | null;
    cpp_model_found: boolean | null;
    parakeet_model_found: boolean;
    qnn_ep_available: boolean;
  };
}

const PROVIDER_META: Record<string, { label: string; icon: string; isCloud?: boolean }> = {
  npu:        { label: 'GenieAPIService (NPU)', icon: '🖥️' },
  ollama:     { label: 'Ollama',                icon: '🤖' },
  nexa:       { label: 'NexaAI Parakeet',       icon: '🦜' },
  claude:     { label: 'Claude',                icon: '🧠', isCloud: true },
  groq:       { label: 'Groq',                  icon: '⚡', isCloud: true },
  openai:     { label: 'OpenAI',                icon: '🟢', isCloud: true },
  openrouter: { label: 'OpenRouter',            icon: '🔀', isCloud: true },
};

// Lokális providerek sorrendben a badge sorban
const LOCAL_PROVIDERS  = ['npu', 'ollama', 'nexa'];
const CLOUD_PROVIDERS  = ['claude', 'groq', 'openai', 'openrouter'];

export default function NPUStatus() {
  const [status, setStatus] = useState<NpuStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      setError(null);
      const res = await fetch(`${BACKEND_URL}/npu/status`, { signal: AbortSignal.timeout(8000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus(await res.json());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const iv = setInterval(fetchStatus, 15_000);
    return () => clearInterval(iv);
  }, [fetchStatus]);

  if (loading) return (
    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
      {LOCAL_PROVIDERS.map((p) => (
        <Pill key={p} icon={PROVIDER_META[p].icon} label={PROVIDER_META[p].label} online={null} />
      ))}
    </div>
  );

  if (error) return (
    <div style={{ fontSize: '0.8rem', color: '#dc2626', padding: '0.4rem 0.75rem', backgroundColor: '#fee2e2', borderRadius: '6px', display: 'inline-block' }}>
      Backend nem elérhető: {error}
    </div>
  );

  if (!status) return null;

  const whisper = status.whisper;
  const whisperOk = whisper?.cpp_exe_found && whisper?.cpp_model_found;
  const providers = status.providers ?? {};

  return (
    <div>
      {/* Lokális provider badge-ek */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.4rem' }}>
        {LOCAL_PROVIDERS.map((id) => {
          const info = providers[id];
          const meta = PROVIDER_META[id];
          return (
            <Pill
              key={id}
              icon={meta.icon}
              label={meta.label}
              online={info ? info.online : null}
              models={info?.models}
            />
          );
        })}

        {/* Elválasztó */}
        <span style={{ alignSelf: 'center', color: '#d1d5db', fontSize: '0.8rem' }}>·</span>

        {/* Felhős provider badge-ek */}
        {CLOUD_PROVIDERS.map((id) => {
          const info = providers[id];
          if (!info) return null;
          const meta = PROVIDER_META[id];
          return (
            <CloudPill
              key={id}
              icon={meta.icon}
              label={meta.label}
              online={info.online}
              models={info.models}
            />
          );
        })}
      </div>

      {/* Whisper ASR státusz */}
      <div style={{ fontSize: '0.75rem', color: '#6b7280', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: whisperOk ? '#22c55e' : '#f59e0b', display: 'inline-block' }} />
        <span>Whisper ASR ({whisper?.backend?.toUpperCase() ?? 'CPP'}): {whisperOk ? 'kész' : 'hiányzó bináris/modell'}</span>
        {whisper?.parakeet_model_found && (
          <span style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', backgroundColor: '#f0fdf4', color: '#166534', borderRadius: '4px' }}>
            Parakeet ✓
          </span>
        )}
        {whisper?.qnn_ep_available && (
          <span style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', backgroundColor: '#eff6ff', color: '#1d4ed8', borderRadius: '4px' }}>
            QNN EP
          </span>
        )}
      </div>
    </div>
  );
}

// Lokális provider badge
function Pill({ icon, label, online, models }: {
  icon: string; label: string; online: boolean | null; models?: string[];
}) {
  const color  = online === null ? '#9ca3af' : online ? '#22c55e' : '#ef4444';
  const bg     = online === null ? '#f3f4f6' : online ? '#f0fdf4' : '#fff1f2';
  const border = online === null ? '#e5e7eb' : online ? '#bbf7d0' : '#fecdd3';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.3rem 0.6rem', borderRadius: '6px', backgroundColor: bg, border: `1px solid ${border}`, fontSize: '0.78rem' }}>
      <span style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: color, flexShrink: 0 }} />
      <span>{icon} {label}</span>
      {online && models && models.length > 0 && (
        <span style={{ color: '#6b7280', fontFamily: 'monospace', fontSize: '0.7rem' }}>
          ({models.length} modell)
        </span>
      )}
    </div>
  );
}

// Felhős provider badge (kékkel ha van kulcs, sárgával ha nincs)
function CloudPill({ icon, label, online, models }: {
  icon: string; label: string; online: boolean; models?: string[];
}) {
  const bg     = online ? '#dbeafe' : '#fef3c7';
  const border = online ? '#93c5fd' : '#fcd34d';
  const color  = online ? '#1d4ed8' : '#92400e';
  const statusText = online ? '✓' : '—';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.3rem 0.6rem', borderRadius: '6px', backgroundColor: bg, border: `1px solid ${border}`, fontSize: '0.78rem', color }}>
      <span>{icon} {label}</span>
      {online && models && models.length > 0 && (
        <span style={{ fontFamily: 'monospace', fontSize: '0.7rem', opacity: 0.8 }}>
          ({models.length} modell)
        </span>
      )}
      <span style={{ fontSize: '0.65rem', fontWeight: 700 }}>{statusText}</span>
    </div>
  );
}
