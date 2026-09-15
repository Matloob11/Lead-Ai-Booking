import { useRef } from 'react';
import { Maximize2 } from 'lucide-react';

interface ChatVideoProps {
  src: string;
  onLoadedData?: () => void;
}

function requestVideoFullscreen(video: HTMLVideoElement): void {
  const anyVideo = video as HTMLVideoElement & {
    webkitEnterFullscreen?: () => void;
    webkitRequestFullscreen?: () => void;
    msRequestFullscreen?: () => void;
  };
  if (typeof video.requestFullscreen === 'function') {
    void video.requestFullscreen().catch(() => undefined);
    return;
  }
  if (typeof anyVideo.webkitEnterFullscreen === 'function') {
    anyVideo.webkitEnterFullscreen();
    return;
  }
  if (typeof anyVideo.webkitRequestFullscreen === 'function') {
    anyVideo.webkitRequestFullscreen();
    return;
  }
  if (typeof anyVideo.msRequestFullscreen === 'function') {
    anyVideo.msRequestFullscreen();
  }
}

/**
 * Chat video: plays inline; fullscreen only via the explicit control
 * (auto-fullscreen breaks Bitrix iframe / agent flow).
 */
export default function ChatVideo({ src, onLoadedData }: ChatVideoProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const enterFullscreen = () => {
    const video = videoRef.current;
    if (!video) return;
    requestVideoFullscreen(video);
  };

  return (
    <div className="a7-video-wrap">
      <video
        ref={videoRef}
        src={src}
        controls
        playsInline
        className="chat-video-media"
        onLoadedData={onLoadedData}
      />
      <button
        type="button"
        className="a7-video-fs-btn"
        onClick={() => {
          const video = videoRef.current;
          if (!video) return;
          enterFullscreen();
          if (video.paused) void video.play().catch(() => undefined);
        }}
        aria-label="Play video fullscreen"
        title="Play fullscreen"
      >
        <Maximize2 size={16} />
      </button>
    </div>
  );
}
