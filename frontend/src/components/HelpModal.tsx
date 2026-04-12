'use client';

import { useEffect } from 'react';
import { useTranslations } from 'next-intl';

interface Props {
  onClose: () => void;
}

export default function HelpModal({ onClose }: Props) {
  const t = useTranslations('help');

  // ESC billentyű zárja be
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const Section = ({ icon, title, children }: { icon: string; title: string; children: React.ReactNode }) => (
    <section style={{ marginBottom: '1.75rem' }}>
      <h3 style={{ margin: '0 0 0.6rem', fontSize: '1rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.4rem', color: '#111827' }}>
        <span>{icon}</span> {title}
      </h3>
      <div style={{ color: '#374151', fontSize: '0.9rem', lineHeight: 1.6 }}>{children}</div>
    </section>
  );

  const Step = ({ n, text }: { n: number; text: string }) => (
    <div style={{ display: 'flex', gap: '0.6rem', marginBottom: '0.4rem', alignItems: 'flex-start' }}>
      <span style={{ minWidth: '1.4rem', height: '1.4rem', borderRadius: '50%', backgroundColor: '#3b82f6', color: '#fff', fontSize: '0.75rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: '0.1rem' }}>{n}</span>
      <span>{text}</span>
    </div>
  );

  const Badge = ({ color, label }: { color: string; label: string }) => (
    <span style={{ display: 'inline-block', padding: '0.1rem 0.5rem', borderRadius: '12px', backgroundColor: color, fontSize: '0.75rem', fontWeight: 600, marginRight: '0.4rem', marginBottom: '0.2rem' }}>{label}</span>
  );

  const Url = ({ href }: { href: string }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#3b82f6', fontFamily: 'monospace', fontSize: '0.85rem' }}>{href}</a>
  );

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.45)', zIndex: 999, backdropFilter: 'blur(2px)' }}
      />

      {/* Modal */}
      <div style={{
        position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
        zIndex: 1000, backgroundColor: '#fff', borderRadius: '16px',
        width: 'min(760px, 95vw)', maxHeight: '85vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 25px 60px rgba(0,0,0,0.3)',
      }}>

        {/* Header */}
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid #e5e7eb', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700 }}>📖 {t('title')}</h2>
            <p style={{ margin: '0.15rem 0 0', color: '#6b7280', fontSize: '0.8rem' }}>{t('subtitle')}</p>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: '1px solid #d1d5db', borderRadius: '8px', padding: '0.3rem 0.7rem', cursor: 'pointer', fontSize: '1rem', color: '#6b7280' }}
            title="Bezárás (ESC)"
          >✕</button>
        </div>

        {/* Scrollable content */}
        <div style={{ overflowY: 'auto', padding: '1.5rem' }}>

          <Section icon="🎯" title={t('whatTitle')}>
            <p style={{ margin: '0 0 0.5rem' }}>{t('whatDesc')}</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.5rem' }}>
              <Badge color="#dbeafe" label="🖥️ Parakeet ASR – NPU" />
              <Badge color="#dcfce7" label="🧠 Llama 3.1 8B – NPU" />
              <Badge color="#fef9c3" label="🗄️ SQLite – lokális" />
              <Badge color="#f3e8ff" label="🔒 100% offline" />
            </div>
          </Section>

          <Section icon="🚀" title={t('startTitle')}>
            <p style={{ margin: '0 0 0.5rem', color: '#6b7280', fontSize: '0.85rem' }}>{t('startDesc')}</p>
            <Step n={1} text={t('start1')} />
            <Step n={2} text={t('start2')} />
            <Step n={3} text={t('start3')} />
          </Section>

          <Section icon="🎙️" title={t('recordTitle')}>
            <Step n={1} text={t('record1')} />
            <Step n={2} text={t('record2')} />
            <Step n={3} text={t('record3')} />
            <Step n={4} text={t('record4')} />
            <p style={{ marginTop: '0.6rem', padding: '0.5rem 0.75rem', backgroundColor: '#fffbeb', borderRadius: '6px', border: '1px solid #fde68a', fontSize: '0.85rem' }}>
              💡 {t('recordTip')}
            </p>
          </Section>

          <Section icon="📁" title={t('uploadTitle')}>
            <p>{t('uploadDesc')}</p>
            <div style={{ marginTop: '0.4rem', padding: '0.5rem 0.75rem', backgroundColor: '#f9fafb', borderRadius: '6px', fontFamily: 'monospace', fontSize: '0.8rem', color: '#374151' }}>
              .wav · .mp3 · .m4a · .ogg · .webm
            </div>
            <p style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: '#6b7280' }}>{t('uploadNote')}</p>
          </Section>

          <Section icon="🤖" title={t('providersTitle')}>
            <p style={{ marginBottom: '0.75rem' }}>{t('providersDesc')}</p>

            <div style={{ display: 'grid', gap: '0.5rem' }}>
              {[
                { icon: '🖥️', name: 'Qualcomm NPU (GenieAPIService)', port: ':8912', badge: '#dcfce7', badgeText: 'Ajánlott', desc: t('providerNpu') },
                { icon: '🟤', name: 'Ollama', port: ':11434', badge: '#f3f4f6', badgeText: 'Lokális', desc: t('providerOllama') },
                { icon: '🔵', name: 'NexaAI (nexa serve)', port: ':18181', badge: '#dbeafe', badgeText: 'NPU', desc: t('providerNexa') },
              ].map(p => (
                <div key={p.name} style={{ padding: '0.65rem 0.85rem', borderRadius: '8px', backgroundColor: '#f9fafb', border: '1px solid #e5e7eb' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.2rem' }}>
                    <span>{p.icon}</span>
                    <strong style={{ fontSize: '0.875rem' }}>{p.name}</strong>
                    <code style={{ fontSize: '0.75rem', color: '#6b7280' }}>{p.port}</code>
                    <Badge color={p.badge} label={p.badgeText} />
                  </div>
                  <p style={{ margin: 0, fontSize: '0.82rem', color: '#6b7280' }}>{p.desc}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section icon="📋" title={t('meetingsTitle')}>
            <Step n={1} text={t('meetings1')} />
            <Step n={2} text={t('meetings2')} />
            <Step n={3} text={t('meetings3')} />
          </Section>

          <Section icon="🔧" title={t('servicesTitle')}>
            <p style={{ marginBottom: '0.5rem', fontSize: '0.85rem', color: '#6b7280' }}>{t('servicesDesc')}</p>
            <div style={{ display: 'grid', gap: '0.3rem' }}>
              {[
                { url: 'http://localhost:5167/docs', label: 'Backend API (Swagger)', color: '#dcfce7' },
                { url: 'http://localhost:5167/npu/status', label: 'Provider státusz (JSON)', color: '#dbeafe' },
                { url: 'http://localhost:3118', label: 'Frontend', color: '#f3e8ff' },
                { url: 'http://localhost:8912', label: 'GenieAPIService (NPU LLM)', color: '#fef9c3' },
                { url: 'http://localhost:18181/docs/ui', label: 'Nexa serve API docs', color: '#fce7f3' },
              ].map(s => (
                <div key={s.url} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.35rem 0.5rem', borderRadius: '6px', backgroundColor: s.color }}>
                  <code style={{ fontSize: '0.78rem', color: '#374151' }}><Url href={s.url} /></code>
                  <span style={{ fontSize: '0.78rem', color: '#6b7280' }}>— {s.label}</span>
                </div>
              ))}
            </div>
          </Section>

          <Section icon="⚠️" title={t('troubleTitle')}>
            {[
              { q: t('trouble1q'), a: t('trouble1a') },
              { q: t('trouble2q'), a: t('trouble2a') },
              { q: t('trouble3q'), a: t('trouble3a') },
              { q: t('trouble4q'), a: t('trouble4a') },
            ].map((item, i) => (
              <div key={i} style={{ marginBottom: '0.65rem', padding: '0.6rem 0.75rem', borderRadius: '8px', backgroundColor: '#f9fafb', border: '1px solid #e5e7eb' }}>
                <p style={{ margin: '0 0 0.2rem', fontWeight: 600, fontSize: '0.875rem' }}>❓ {item.q}</p>
                <p style={{ margin: 0, color: '#6b7280', fontSize: '0.82rem' }}>→ {item.a}</p>
              </div>
            ))}
          </Section>

          <Section icon="⌨️" title={t('shortcutsTitle')}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.3rem' }}>
              {[
                ['ESC', t('shortcutEsc')],
                ['scripts\\start-meetily-npu.bat', t('shortcutBat')],
              ].map(([key, desc]) => (
                <div key={key} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', padding: '0.3rem 0.5rem', backgroundColor: '#f3f4f6', borderRadius: '6px' }}>
                  <kbd style={{ padding: '0.1rem 0.4rem', backgroundColor: '#fff', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.75rem', fontFamily: 'monospace' }}>{key}</kbd>
                  <span style={{ fontSize: '0.82rem', color: '#6b7280' }}>{desc}</span>
                </div>
              ))}
            </div>
          </Section>

        </div>

        {/* Footer */}
        <div style={{ padding: '0.75rem 1.5rem', borderTop: '1px solid #e5e7eb', fontSize: '0.78rem', color: '#9ca3af', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
          <span>Meetily Snapdragon · Snapdragon X Elite ARM64</span>
          <button onClick={onClose} style={{ padding: '0.4rem 1rem', borderRadius: '8px', backgroundColor: '#3b82f6', color: '#fff', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}>
            {t('closeBtn')}
          </button>
        </div>
      </div>
    </>
  );
}
