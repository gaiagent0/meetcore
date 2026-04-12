'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

interface TranscriptSegment {
  id: string;
  text: string;
  timestamp?: string;
  audioStartTime?: number;
  confidence?: number;
  duration?: number;
}

interface TranscriptViewProps {
  segments: TranscriptSegment[];
  isRecording?: boolean;
  isPaused?: boolean;
  isProcessing?: boolean;
}

/** Remove consecutive short-word repetitions ("a a a" → "a") */
function cleanRepetitions(text: string): string {
  if (!text.trim()) return text;
  const words = text.split(/\s+/);
  const cleaned: string[] = [];
  let i = 0;
  while (i < words.length) {
    const w = words[i].toLowerCase();
    let count = 1;
    while (i + count < words.length && words[i + count].toLowerCase() === w) count++;
    if (w.length <= 2 && count >= 2) {
      cleaned.push(words[i]);
      i += count;
    } else {
      cleaned.push(words[i]);
      i++;
    }
  }
  return cleaned.join(' ');
}

function formatRecordingTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

export default function TranscriptView({
  segments,
  isRecording = false,
  isPaused = false,
  isProcessing = false,
}: TranscriptViewProps) {
  const tt = useTranslations('transcript');
  const containerRef = useRef<HTMLDivElement>(null);
  const [hasAutoScrolled, setHasAutoScrolled] = useState(false);

  // Auto-scroll to bottom on new segments
  useEffect(() => {
    if (segments.length > 0 && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      setHasAutoScrolled(true);
    }
  }, [segments.length]);

  if (segments.length === 0) {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '3rem 1rem',
          color: '#6b7280',
        }}
      >
        {isRecording ? (
          <>
            <div
              style={{
                width: '12px',
                height: '12px',
                borderRadius: '50%',
                backgroundColor: isPaused ? '#f97316' : '#3b82f6',
                margin: '0 auto 0.75rem',
                ...(isPaused ? {} : { animation: 'pulse 2s infinite' }),
              }}
            />
            <p style={{ fontSize: '0.9rem', margin: 0 }}>
              {isPaused ? 'Felvétel szüneteltetve' : tt('emptyState')}
            </p>
            <p style={{ fontSize: '0.8rem', marginTop: '0.25rem', color: '#9ca3af' }}>
              {tt('emptyStateSub')}
            </p>
          </>
        ) : (
          <>
            <p style={{ fontSize: '1rem', fontWeight: 600, margin: 0 }}>{tt('noTranscript')}</p>
          </>
        )}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        maxHeight: '400px',
        overflowY: 'auto',
        padding: '0.5rem',
      }}
    >
      {segments.map((seg, idx) => {
        const cleaned = cleanRepetitions(seg.text);
        const displayText = seg.text.trim() === '' ? tt('silence') : cleaned;
        const timeLabel = seg.audioStartTime !== undefined
          ? formatRecordingTime(seg.audioStartTime)
          : seg.timestamp || `${idx + 1}`;

        return (
          <div key={seg.id} style={{ marginBottom: '0.75rem' }}>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
              <span
                style={{
                  fontSize: '0.75rem',
                  color: '#9ca3af',
                  flexShrink: 0,
                  minWidth: '50px',
                  paddingTop: '0.2rem',
                  fontFamily: 'monospace',
                }}
              >
                {timeLabel}
              </span>
              <div style={{ flex: 1 }}>
                <p
                  style={{
                    margin: 0,
                    fontSize: '0.95rem',
                    lineHeight: 1.6,
                    color: '#1f2937',
                  }}
                >
                  {displayText}
                </p>
                {seg.confidence !== undefined && (
                  <div style={{ marginTop: '0.25rem' }}>
                    <div
                      style={{
                        display: 'inline-block',
                        height: '3px',
                        width: `${seg.confidence * 100}%`,
                        maxWidth: '60px',
                        borderRadius: '2px',
                        backgroundColor: seg.confidence > 0.8 ? '#22c55e' : seg.confidence > 0.5 ? '#f59e0b' : '#ef4444',
                      }}
                    />
                    <span style={{ fontSize: '0.7rem', color: '#9ca3af', marginLeft: '0.35rem' }}>
                      {Math.round(seg.confidence * 100)}%
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* Listening indicator */}
      {isRecording && !isPaused && !isProcessing && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            marginTop: '1rem',
            color: '#6b7280',
          }}
        >
          <div
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: '#3b82f6',
              animation: 'pulse 2s infinite',
            }}
          />
          <span style={{ fontSize: '0.85rem' }}>{tt('listening')}</span>
        </div>
      )}
    </div>
  );
}
