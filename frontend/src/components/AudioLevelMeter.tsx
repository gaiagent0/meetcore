'use client';

import { useEffect, useRef, useState } from 'react';

interface AudioLevelMeterProps {
  stream: MediaStream | null;
  barCount?: number;
  isActive?: boolean;
}

export default function AudioLevelMeter({ stream, barCount = 20, isActive = false }: AudioLevelMeterProps) {
  const [levels, setLevels] = useState<number[]>(Array(barCount).fill(4));
  const animFrameRef = useRef<number>(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => {
    if (!stream || !isActive) {
      setLevels(Array(barCount).fill(4));
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (audioCtxRef.current) {
        audioCtxRef.current.close();
        audioCtxRef.current = null;
      }
      return;
    }

    const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
    audioCtxRef.current = audioCtx;
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.8;
    analyserRef.current = analyser;

    const source = audioCtx.createMediaStreamSource(stream);
    sourceRef.current = source;
    source.connect(analyser);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const updateLevels = () => {
      analyser.getByteFrequencyData(dataArray);

      const step = Math.floor(dataArray.length / barCount);
      const newLevels = Array.from({ length: barCount }, (_, i) => {
        const value = dataArray[i * step] || 0;
        return Math.max(4, (value / 255) * 32);
      });
      setLevels(newLevels);
      animFrameRef.current = requestAnimationFrame(updateLevels);
    };

    animFrameRef.current = requestAnimationFrame(updateLevels);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (sourceRef.current) sourceRef.current.disconnect();
      if (audioCtxRef.current) audioCtxRef.current.close();
    };
  }, [stream, isActive, barCount]);

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: '2px',
        height: '36px',
        padding: '0.5rem',
      }}
      role="img"
      aria-label="Audio level meter"
    >
      {levels.map((height, i) => (
        <div
          key={i}
          style={{
            width: '3px',
            height: `${height}px`,
            borderRadius: '2px',
            backgroundColor: isActive ? (height > 20 ? '#dc3545' : height > 12 ? '#f59e0b' : '#22c55e') : '#d1d5db',
            transition: 'height 0.08s ease, background-color 0.2s ease',
          }}
        />
      ))}
    </div>
  );
}
