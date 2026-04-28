'use client';

import { useCallback, useRef, useState } from 'react';

interface TtsPlayerProps {
  text: string;
  backendUrl?: string;
  label?: string;
}

type Status = 'idle' | 'loading' | 'playing' | 'error';

export default function TtsPlayer({
  text,
  backendUrl = 'http://localhost:5167',
  label = 'Felolvasás',
}: TtsPlayerProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
    setStatus('idle');
  }, []);

  const play = useCallback(async () => {
    if (status === 'playing') {
      stop();
      return;
    }
    if (!text.trim()) return;

    setStatus('loading');
    setError(null);

    try {
      const formData = new FormData();
      formData.append('text', text.slice(0, 2000));

      const resp = await fetch(`${backendUrl}/tts/synthesize`, {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
        throw new Error(typeof detail.detail === 'string' ? detail.detail : JSON.stringify(detail.detail));
      }

      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;

      audio.onended = () => { setStatus('idle'); URL.revokeObjectURL(url); };
      audio.onerror = () => { setStatus('error'); setError('Lejátszási hiba'); };

      await audio.play();
      setStatus('playing');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      setStatus('error');
    }
  }, [text, status, backendUrl, stop]);

  const isLoading = status === 'loading';
  const isPlaying = status === 'playing';

  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
      <button
        onClick={play}
        disabled={isLoading || !text.trim()}
        title={isPlaying ? 'Leállítás' : label}
        style={{
          padding: '0.3rem 0.7rem',
          borderRadius: '6px',
          border: '1px solid #d1d5db',
          backgroundColor: isPlaying ? '#fef3c7' : isLoading ? '#f3f4f6' : '#fff',
          color: isLoading ? '#9ca3af' : '#374151',
          cursor: isLoading || !text.trim() ? 'not-allowed' : 'pointer',
          fontSize: '0.8rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.3rem',
        }}
      >
        {isLoading ? '⏳' : isPlaying ? '⏹' : '🔊'}
        {isLoading ? 'Generálás...' : isPlaying ? 'Leállítás' : label}
      </button>
      {status === 'error' && error && (
        <span style={{ fontSize: '0.75rem', color: '#dc2626' }} title={error}>
          ⚠️ TTS hiba
        </span>
      )}
    </div>
  );
}
