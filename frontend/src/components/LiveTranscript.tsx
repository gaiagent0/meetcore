'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';

interface Segment {
  id: number;
  text: string;
  time: string;
}

interface LiveTranscriptProps {
  onTranscriptUpdate?: (fullText: string) => void;
  backendUrl?: string;
}

export default function LiveTranscript({
  onTranscriptUpdate,
  backendUrl = 'http://localhost:5167',
}: LiveTranscriptProps) {
  const t = useTranslations('live');
  const [segments, setSegments] = useState<Segment[]>([]);
  const [status, setStatus] = useState<'idle' | 'connecting' | 'recording' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const segCountRef = useRef(0);

  const wsUrl = backendUrl.replace(/^http/, 'ws') + '/ws/live-asr';

  const cleanup = useCallback(() => {
    processorRef.current?.disconnect();
    if (audioCtxRef.current?.state !== 'closed') audioCtxRef.current?.close();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    processorRef.current = null;
    audioCtxRef.current = null;
    streamRef.current = null;
  }, []);

  const stop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
    } else {
      cleanup();
      setStatus('idle');
    }
  }, [cleanup]);

  const start = useCallback(async () => {
    setError(null);
    setSegments([]);
    segCountRef.current = 0;
    setStatus('connecting');

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Mikrofon hiba: ${msg}`);
      setStatus('error');
      return;
    }
    streamRef.current = stream;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'config', language: 'hu' }));
      setStatus('recording');

      const audioCtx = new AudioContext({ sampleRate: 16000 });
      audioCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      // bufferSize 4096 → ~256ms @ 16kHz — jó VAD granularitás
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (ws.readyState !== WebSocket.OPEN) return;
        const float32 = e.inputBuffer.getChannelData(0);
        const int16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i++) {
          const s = Math.max(-1, Math.min(1, float32[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        ws.send(int16.buffer);
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string);
        if (msg.type === 'final' && msg.text) {
          const seg: Segment = {
            id: segCountRef.current++,
            text: msg.text as string,
            time: new Date().toLocaleTimeString(),
          };
          setSegments((prev) => {
            const next = [...prev, seg];
            onTranscriptUpdate?.(next.map((s) => s.text).join(' '));
            return next;
          });
        } else if (msg.type === 'done') {
          cleanup();
          setStatus('idle');
        } else if (msg.type === 'error') {
          setError(msg.message as string);
          cleanup();
          setStatus('error');
        }
      } catch {
        // nem JSON → ignore
      }
    };

    ws.onerror = () => {
      setError('WebSocket kapcsolati hiba');
      cleanup();
      setStatus('error');
    };

    ws.onclose = () => {
      cleanup();
      setStatus('idle');
    };
  }, [wsUrl, cleanup, onTranscriptUpdate]);

  useEffect(() => () => { cleanup(); }, [cleanup]);

  return (
    <div style={{ padding: '1rem', borderRadius: '10px', backgroundColor: '#f0fdf4', border: '1px solid #bbf7d0' }}>
      <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '0.75rem' }}>
        {status === 'idle' || status === 'error' ? (
          <button
            onClick={start}
            style={{ padding: '0.55rem 1.1rem', borderRadius: '7px', backgroundColor: '#16a34a', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600 }}
          >
            🎙️ {t('startRecording')}
          </button>
        ) : status === 'connecting' ? (
          <span style={{ color: '#6b7280', fontSize: '0.875rem' }}>⏳ {t('connecting')}</span>
        ) : (
          <button
            onClick={stop}
            style={{ padding: '0.55rem 1.1rem', borderRadius: '7px', backgroundColor: '#dc2626', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600 }}
          >
            ⏹ {t('stopRecording')}
          </button>
        )}
        {status === 'recording' && (
          <span style={{ color: '#16a34a', fontSize: '0.85rem', fontWeight: 500 }}>
            ● {t('liveTranscribing')}
          </span>
        )}
      </div>

      {error && (
        <div style={{ marginBottom: '0.5rem', padding: '0.5rem 0.75rem', backgroundColor: '#fff1f2', border: '1px solid #fecdd3', borderRadius: '6px', color: '#9f1239', fontSize: '0.8rem' }}>
          {error}
        </div>
      )}

      <div style={{ minHeight: '80px', maxHeight: '280px', overflowY: 'auto' }}>
        {segments.length === 0 ? (
          <p style={{ color: '#9ca3af', fontSize: '0.875rem', textAlign: 'center', paddingTop: '1.25rem' }}>
            {t('noSegmentsYet')}
          </p>
        ) : (
          segments.map((seg) => (
            <div
              key={seg.id}
              style={{ padding: '0.4rem 0.6rem', marginBottom: '0.3rem', backgroundColor: '#fff', borderRadius: '6px', border: '1px solid #d1fae5' }}
            >
              <span style={{ fontSize: '0.7rem', color: '#9ca3af', marginRight: '0.5rem' }}>{seg.time}</span>
              <span style={{ fontSize: '0.875rem' }}>{seg.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
