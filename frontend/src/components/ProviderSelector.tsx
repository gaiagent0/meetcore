'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState, useCallback } from 'react';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:5167';

export interface ProviderConfig {
  id: string;
  label: string;
  icon: string;
  description: string;
  models: string[];
  online?: boolean;
  isCloud?: boolean;
}

const BASE_PROVIDERS: Omit<ProviderConfig, 'models' | 'online'>[] = [
  // ── Lokális ──────────────────────────────────────────────────────────────
  { id: 'npu',        label: 'NPU (GenieAPI)',     icon: '🖥️', description: 'Qualcomm Hexagon NPU — offline, <5W',      isCloud: false },
  { id: 'ollama',     label: 'Ollama (CPU/GPU)',   icon: '🤖', description: 'Helyi Ollama — offline, CPU/GPU',           isCloud: false },
  { id: 'nexa',       label: 'NexaAI',             icon: '🦜', description: 'NexaAI szerver — NPU modellek',            isCloud: false },
  { id: 'omnineural', label: 'OmniNeural-4B',     icon: '🧠', description: 'Multimodális NPU — szöveg + hang (:18183)', isCloud: false },
  // ── Felhős ───────────────────────────────────────────────────────────────
  { id: 'claude',     label: 'Claude (Anthropic)', icon: '🧠', description: 'Anthropic Claude — API kulcs kell',        isCloud: true  },
  { id: 'groq',       label: 'Groq',               icon: '⚡', description: 'Groq gyors inferencia — API kulcs kell',  isCloud: true  },
  { id: 'openai',     label: 'OpenAI',             icon: '🟢', description: 'OpenAI GPT-4o — API kulcs kell',          isCloud: true  },
  { id: 'openrouter', label: 'OpenRouter',         icon: '🔀', description: 'OpenRouter aggregátor — API kulcs kell',  isCloud: true  },
];

const NPU_MODELS = ['llama3.1-8b-8380-qnn2.38'];

const CLAUDE_MODELS    = ['claude-3-5-haiku-20241022', 'claude-3-5-sonnet-20241022', 'claude-opus-4-5'];
const GROQ_MODELS      = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768'];
const OPENAI_MODELS    = ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'];
const OR_MODELS        = ['meta-llama/llama-3.3-70b-instruct', 'google/gemini-flash-1.5', 'anthropic/claude-3.5-haiku'];

const OMNINEURAL_MODELS = ['NexaAI/OmniNeural-4B'];

const STATIC_MODELS: Record<string, string[]> = {
  npu: NPU_MODELS, claude: CLAUDE_MODELS,
  groq: GROQ_MODELS, openai: OPENAI_MODELS, openrouter: OR_MODELS,
  omnineural: OMNINEURAL_MODELS,
};

interface ProviderSelectorProps {
  onProviderChange?: (providerId: string) => void;
  onModelChange?: (providerId: string, model: string) => void;
}

export default function ProviderSelector({ onProviderChange, onModelChange }: ProviderSelectorProps) {
  const tp = useTranslations('providerSelector');

  const [providers, setProviders] = useState<ProviderConfig[]>(
    BASE_PROVIDERS.map((p) => ({
      ...p,
      models: STATIC_MODELS[p.id] ?? [],
      online: undefined,
    }))
  );
  const [selectedProvider, setSelectedProvider] = useState<string>('ollama');
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [saveFlash, setSaveFlash] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchProviders = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/npu/providers`, { signal: AbortSignal.timeout(8000) });
      if (!res.ok) return;
      const data: Record<string, { online: boolean; models?: string[] }> = await res.json();
      setProviders((prev) =>
        prev.map((p) => {
          const info = data[p.id];
          if (!info) return p;
          const models =
            (p.id === 'ollama' || p.id === 'nexa') && info.models && info.models.length > 0
              ? info.models
              : (STATIC_MODELS[p.id] ?? p.models);
          return { ...p, online: info.online ?? false, models };
        })
      );
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchProviders();
    const iv = setInterval(fetchProviders, 20_000);
    return () => clearInterval(iv);
  }, [fetchProviders]);

  useEffect(() => {
    const current = providers.find((p) => p.id === selectedProvider);
    if (current && current.models.length > 0 && !selectedModel) {
      const m = current.models[0];
      setSelectedModel(m);
      onModelChange?.(selectedProvider, m);
    }
  }, [providers, selectedProvider]);

  const handleProviderSelect = (id: string) => {
    const prov = providers.find((p) => p.id === id);
    const model = prov?.models?.[0] ?? '';
    setSelectedProvider(id);
    setSelectedModel(model);
    setIsDropdownOpen(false);
    onProviderChange?.(id);
    onModelChange?.(id, model);
  };

  const handleModelChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const model = e.target.value;
    setSelectedModel(model);
    onModelChange?.(selectedProvider, model);
  };

  const handleSave = () => {
    setSaveFlash(true);
    setTimeout(() => setSaveFlash(false), 1500);
  };

  const current = providers.find((p) => p.id === selectedProvider);

  const onlineBadge = (online?: boolean, isCloud?: boolean) => {
    if (online === undefined) return { bg: '#f3f4f6', text: '#6b7280', label: '...' };
    if (isCloud && online)  return { bg: '#dbeafe', text: '#1d4ed8', label: tp('cloudReady') };
    if (isCloud && !online) return { bg: '#fef3c7', text: '#92400e', label: tp('noKey') };
    return online
      ? { bg: '#dcfce7', text: '#166534', label: tp('online') }
      : { bg: '#fee2e2', text: '#991b1b', label: tp('offline') };
  };

  const currentBadge = onlineBadge(current?.online, current?.isCloud);
  const localProviders = providers.filter((p) => !p.isCloud);
  const cloudProviders = providers.filter((p) => p.isCloud);

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: '12px', padding: '1.25rem', backgroundColor: '#fff' }}>
      <div style={{ marginBottom: '1rem' }}>
        <h3 style={{ margin: '0 0 0.25rem', fontSize: '1rem', fontWeight: 600 }}>{tp('title')}</h3>
        <p style={{ margin: 0, fontSize: '0.8rem', color: '#6b7280' }}>{tp('subtitle')}</p>
      </div>

      {/* Aktív provider badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem', padding: '0.5rem 0.75rem', backgroundColor: '#f9fafb', borderRadius: '8px', border: '1px solid #f3f4f6' }}>
        <span style={{ fontSize: '1.25rem' }}>{current?.icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{current?.label}</div>
          <div style={{ fontSize: '0.75rem', color: '#6b7280' }}>{current?.description}</div>
        </div>
        <span style={{ fontSize: '0.7rem', fontWeight: 600, padding: '0.15rem 0.5rem', borderRadius: '999px', backgroundColor: currentBadge.bg, color: currentBadge.text, textTransform: 'uppercase' }}>
          {currentBadge.label}
        </span>
      </div>

      {/* Provider dropdown */}
      <div style={{ marginBottom: '0.75rem' }}>
        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.35rem', color: '#374151' }}>
          {tp('selectLabel')}
        </label>
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            style={{ width: '100%', padding: '0.5rem 0.75rem', border: '1px solid #d1d5db', borderRadius: '8px', backgroundColor: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', textAlign: 'left' }}
          >
            <span>{current?.icon}</span>
            <span style={{ flex: 1 }}>{current?.label}</span>
            <span style={{ fontSize: '0.7rem', color: '#9ca3af' }}>▼</span>
          </button>

          {isDropdownOpen && (
            <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: '0.25rem', backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', zIndex: 50, maxHeight: '340px', overflowY: 'auto' }}>
              {/* Lokális csoport */}
              <div style={{ padding: '0.35rem 0.75rem 0.2rem', fontSize: '0.68rem', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', backgroundColor: '#f9fafb', borderBottom: '1px solid #f0f0f0' }}>
                {tp('localGroup')}
              </div>
              {localProviders.map((p) => {
                const badge = onlineBadge(p.online, false);
                return (
                  <button key={p.id} onClick={() => handleProviderSelect(p.id)}
                    style={{ width: '100%', padding: '0.55rem 0.75rem', border: 'none', backgroundColor: p.id === selectedProvider ? '#f0f9ff' : 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', textAlign: 'left', borderBottom: '1px solid #f9fafb' }}>
                    <span style={{ fontSize: '1rem' }}>{p.icon}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: p.id === selectedProvider ? 600 : 400, fontSize: '0.85rem' }}>{p.label}</div>
                      <div style={{ fontSize: '0.7rem', color: '#6b7280' }}>{p.description}</div>
                    </div>
                    <span style={{ fontSize: '0.62rem', fontWeight: 600, padding: '0.1rem 0.4rem', borderRadius: '999px', backgroundColor: badge.bg, color: badge.text, whiteSpace: 'nowrap' }}>
                      {badge.label}
                    </span>
                  </button>
                );
              })}

              {/* Felhős csoport */}
              <div style={{ padding: '0.35rem 0.75rem 0.2rem', fontSize: '0.68rem', fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', backgroundColor: '#f9fafb', borderTop: '1px solid #e5e7eb', borderBottom: '1px solid #f0f0f0' }}>
                {tp('cloudGroup')}
              </div>
              {cloudProviders.map((p) => {
                const badge = onlineBadge(p.online, true);
                return (
                  <button key={p.id} onClick={() => handleProviderSelect(p.id)}
                    style={{ width: '100%', padding: '0.55rem 0.75rem', border: 'none', backgroundColor: p.id === selectedProvider ? '#eff6ff' : 'transparent', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', textAlign: 'left', borderBottom: '1px solid #f9fafb' }}>
                    <span style={{ fontSize: '1rem' }}>{p.icon}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: p.id === selectedProvider ? 600 : 400, fontSize: '0.85rem' }}>{p.label}</div>
                      <div style={{ fontSize: '0.7rem', color: '#6b7280' }}>{p.description}</div>
                    </div>
                    <span style={{ fontSize: '0.62rem', fontWeight: 600, padding: '0.1rem 0.4rem', borderRadius: '999px', backgroundColor: badge.bg, color: badge.text, whiteSpace: 'nowrap' }}>
                      {badge.label}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Modell választó */}
      {current && current.models.length > 0 && (
        <div style={{ marginBottom: '0.75rem' }}>
          <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.35rem', color: '#374151' }}>
            {tp('modelLabel')}
          </label>
          {loading && (current.id === 'ollama' || current.id === 'nexa') ? (
            <div style={{ fontSize: '0.8rem', color: '#6b7280', padding: '0.4rem 0' }}>Modellek betöltése...</div>
          ) : (
            <select value={selectedModel} onChange={handleModelChange}
              style={{ width: '100%', padding: '0.5rem 0.75rem', border: '1px solid #d1d5db', borderRadius: '8px', backgroundColor: '#fff', fontSize: '0.85rem', fontFamily: 'monospace' }}>
              {current.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
        </div>
      )}

      <button onClick={handleSave}
        style={{ width: '100%', padding: '0.5rem', borderRadius: '8px', border: 'none', backgroundColor: saveFlash ? '#22c55e' : '#3b82f6', color: '#fff', fontWeight: 600, fontSize: '0.85rem', cursor: 'pointer', transition: 'background-color 0.2s' }}>
        {saveFlash ? tp('saved') : tp('save')}
      </button>

      {isDropdownOpen && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 40 }} onClick={() => setIsDropdownOpen(false)} />
      )}
    </div>
  );
}
