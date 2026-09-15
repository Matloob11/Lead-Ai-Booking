import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';

interface VoicePlayerProps {
  src: string;
  /** Outgoing bubbles use a slightly different accent. */
  outgoing?: boolean;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

/**
 * Custom voice / audio control for chat bubbles. Replaces the native browser
 * <audio controls> chrome, which looks like a system widget inside WhatsApp UI.
 */
export default function VoicePlayer({ src, outgoing = false }: VoicePlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playerId = useId();
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRate] = useState(1);

  const pauseOthers = useCallback(() => {
    document.querySelectorAll<HTMLAudioElement>('audio[data-a7-voice]').forEach(el => {
      if (el.dataset.a7Voice === playerId) return;
      el.pause();
    });
  }, [playerId]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTime = () => setCurrent(audio.currentTime);
    const onMeta = () => setDuration(audio.duration || 0);
    const onPlay = () => {
      pauseOthers();
      setPlaying(true);
    };
    const onPause = () => setPlaying(false);
    const onEnded = () => {
      setPlaying(false);
      setCurrent(0);
      audio.currentTime = 0;
    };

    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('loadedmetadata', onMeta);
    audio.addEventListener('durationchange', onMeta);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnded);
    return () => {
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('loadedmetadata', onMeta);
      audio.removeEventListener('durationchange', onMeta);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onEnded);
    };
  }, [pauseOthers, src]);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      void audio.play().catch(() => undefined);
    } else {
      audio.pause();
    }
  };

  const seek = (value: number) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(value)) return;
    audio.currentTime = value;
    setCurrent(value);
  };

  const cycleRate = () => {
    const next = rate === 1 ? 1.5 : rate === 1.5 ? 2 : 1;
    setRate(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
  };

  const progress = duration > 0 ? Math.min(100, (current / duration) * 100) : 0;

  return (
    <div className={`a7-voice-player ${outgoing ? 'outgoing' : 'incoming'}`}>
      <audio ref={audioRef} src={src} preload="metadata" data-a7-voice={playerId} />
      <button
        type="button"
        className="a7-voice-play"
        onClick={toggle}
        aria-label={playing ? 'Pause voice message' : 'Play voice message'}
      >
        {playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
      </button>
      <div className="a7-voice-body">
        <div className="a7-voice-wave" aria-hidden="true">
          {Array.from({ length: 28 }, (_, i) => {
            const h = 28 + ((i * 17) % 48);
            const active = progress > (i / 28) * 100;
            return <span key={i} className={active ? 'on' : ''} style={{ height: `${h}%` }} />;
          })}
        </div>
        <input
          type="range"
          className="a7-voice-seek"
          min={0}
          max={duration > 0 ? duration : 1}
          step={0.01}
          value={duration > 0 ? current : 0}
          disabled={duration <= 0}
          onChange={e => seek(Number(e.target.value))}
          aria-label="Seek voice message"
        />
        <div className="a7-voice-meta">
          <span>{formatTime(playing || current > 0 ? current : duration)}</span>
          <button type="button" className="a7-voice-rate" onClick={cycleRate} title="Playback speed">
            {rate}x
          </button>
        </div>
      </div>
    </div>
  );
}
