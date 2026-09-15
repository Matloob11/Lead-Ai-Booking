/**
 * WhatsApp-style voice note player — waveform, seek, duration, download, speed.
 */

import { el, clear } from "./dom.js";
import { icon } from "./icons.js";

let activeVoice = null;

function stopActiveVoice() {
  if (!activeVoice) return;
  activeVoice.pause();
  activeVoice = null;
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fallbackPeaks(count, seed = 0) {
  const peaks = [];
  for (let i = 0; i < count; i++) {
    const wave = Math.sin((i + seed) * 0.55) * 0.35 + Math.cos((i + seed) * 0.31) * 0.25;
    const base = 0.35 + (((i + seed) * 17) % 11) / 22;
    peaks.push(Math.min(1, Math.max(0.15, base + wave)));
  }
  return peaks;
}

async function loadAudioProfile(src) {
  const res = await fetch(src, { credentials: "include" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const blob = await res.blob();
  const mime = blob.type && blob.type.startsWith("audio/") ? blob.type : "audio/ogg";
  const typed = blob.type === mime ? blob : new Blob([blob], { type: mime });
  const objectUrl = URL.createObjectURL(typed);
  const buffer = await typed.arrayBuffer();

  let duration = 0;
  let peaks = fallbackPeaks(48, src.length);

  try {
    const ctx = new AudioContext();
    const decoded = await ctx.decodeAudioData(buffer.slice(0));
    await ctx.close();
    duration = decoded.duration;
    const channel = decoded.getChannelData(0);
    const barCount = 48;
    const block = Math.max(1, Math.floor(channel.length / barCount));
    const next = [];
    for (let i = 0; i < barCount; i++) {
      let sum = 0;
      const start = i * block;
      for (let j = 0; j < block; j++) sum += Math.abs(channel[start + j] || 0);
      next.push(sum / block);
    }
    const max = Math.max(...next, 0.0001);
    peaks = next.map((v) => Math.max(0.12, v / max));
  } catch {
    const probe = new Audio(objectUrl);
    probe.preload = "metadata";
    await new Promise((resolve, reject) => {
      const done = () => {
        probe.removeEventListener("loadedmetadata", done);
        probe.removeEventListener("error", fail);
        resolve();
      };
      const fail = () => {
        probe.removeEventListener("loadedmetadata", done);
        probe.removeEventListener("error", fail);
        reject(new Error("metadata"));
      };
      probe.addEventListener("loadedmetadata", done);
      probe.addEventListener("error", fail);
      probe.load();
    });
    if (Number.isFinite(probe.duration) && probe.duration > 0) duration = probe.duration;
  }

  return { objectUrl, duration, peaks, blob, mime };
}

/**
 * @param {{ src: string, downloadName?: string, outbound?: boolean }} opts
 */
export function createVoicePlayer({ src, downloadName = "voice.ogg", outbound = false }) {
  const audio = new Audio();
  audio.preload = "auto";

  let duration = 0;
  let objectUrl = "";
  let ready = false;
  let raf = 0;
  let speedIndex = 0;
  const speeds = [1, 1.5, 2];

  const playBtn = el("button.voice__play", {
    type: "button",
    title: "Play voice message",
    "aria-label": "Play voice message",
  });
  const wave = el("div.voice__wave", { title: "Click to seek" });
  const timeEl = el("span.voice__time", {}, ["…"]);
  const speedBtn = el("button.voice__tool", { type: "button", title: "Playback speed", hidden: true }, ["1×"]);
  const downloadBtn = el(
    "a.voice__tool.voice__tool--dl",
    { href: src, download: downloadName, title: "Download voice message", hidden: true },
    [icon("download", { size: 15 })]
  );

  const root = el(
    "div.msg__voice",
    { class: outbound ? "msg__voice--out" : "msg__voice--in" },
    [
      playBtn,
      el("div.voice__body", {}, [wave, el("div.voice__footrow", {}, [timeEl, el("div.voice__tools", {}, [speedBtn, downloadBtn])])]),
    ]
  );

  let bars = [];

  function setPlaying(on) {
    root.classList.toggle("is-playing", on);
    clear(playBtn);
    playBtn.append(icon(on ? "pause" : "play", { size: 16 }));
    playBtn.title = on ? "Pause voice message" : "Play voice message";
    playBtn.setAttribute("aria-label", playBtn.title);
  }

  function paintProgress() {
    const total = duration || audio.duration || 0;
    const current = audio.currentTime || 0;
    const pct = total > 0 ? Math.min(1, current / total) : 0;
    const heardThrough = Math.floor(pct * bars.length);

    bars.forEach((bar, index) => {
      bar.classList.toggle("is-heard", index < heardThrough);
      bar.classList.toggle("is-scrub", index === heardThrough);
    });

    if (!ready) {
      timeEl.textContent = "…";
      return;
    }
    if (total > 0) {
      timeEl.textContent =
        audio.paused && current <= 0.05
          ? formatTime(total)
          : `${formatTime(current)} / ${formatTime(total)}`;
    } else {
      timeEl.textContent = formatTime(current);
    }
  }

  function tick() {
    paintProgress();
    if (!audio.paused) raf = requestAnimationFrame(tick);
  }

  function pause() {
    audio.pause();
    setPlaying(false);
    cancelAnimationFrame(raf);
    paintProgress();
    if (activeVoice === audio) activeVoice = null;
  }

  function play() {
    if (!ready) return;
    stopActiveVoice();
    activeVoice = audio;
    audio
      .play()
      .then(() => {
        setPlaying(true);
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(tick);
      })
      .catch(() => {
        setPlaying(false);
        activeVoice = null;
      });
  }

  function seekTo(clientX) {
    const total = duration || audio.duration || 0;
    if (!total || !bars.length) return;
    const rect = wave.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    audio.currentTime = ratio * total;
    paintProgress();
  }

  function buildBars(peaks) {
    clear(wave);
    bars = peaks.map((peak, index) => {
      const h = Math.round(18 + peak * 82);
      return el("button.voice__bar", {
        type: "button",
        style: `--h: ${h}%`,
        title: "Seek",
        "aria-label": `Seek ${index + 1}`,
        onclick: (event) => {
          event.stopPropagation();
          const total = duration || audio.duration || 0;
          if (!total) return;
          audio.currentTime = ((index + 0.5) / peaks.length) * total;
          paintProgress();
        },
      });
    });
    wave.append(...bars);
  }

  function showFailed(reason) {
    root.replaceWith(
      el("div.msg__media-failed", {}, [
        icon("alert", { size: 15 }),
        "Voice message unavailable",
        el("span.msg__media-failed-hint", {}, [reason]),
      ])
    );
  }

  playBtn.addEventListener("click", () => {
    if (!ready) return;
    if (audio.paused) play();
    else pause();
  });

  wave.addEventListener("click", (event) => seekTo(event.clientX));

  let dragging = false;
  wave.addEventListener("mousedown", (event) => {
    dragging = true;
    seekTo(event.clientX);
  });
  window.addEventListener("mousemove", (event) => {
    if (dragging) seekTo(event.clientX);
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
  });

  speedBtn.addEventListener("click", () => {
    speedIndex = (speedIndex + 1) % speeds.length;
    const rate = speeds[speedIndex];
    audio.playbackRate = rate;
    speedBtn.textContent = `${rate}×`;
  });

  audio.addEventListener("timeupdate", paintProgress);
  audio.addEventListener("ended", () => {
    setPlaying(false);
    cancelAnimationFrame(raf);
    audio.currentTime = 0;
    paintProgress();
    if (activeVoice === audio) activeVoice = null;
  });

  audio.addEventListener("error", () => {
    showFailed("Could not play this audio file");
  });

  setPlaying(false);
  buildBars(fallbackPeaks(48));
  paintProgress();

  function beginLoad() {
    if (beginLoad.started) return;
    beginLoad.started = true;

    loadAudioProfile(src)
      .then((profile) => {
        objectUrl = profile.objectUrl;
        duration = profile.duration || 0;
        audio.src = objectUrl;
        buildBars(profile.peaks);
        ready = true;
        playBtn.disabled = false;
        speedBtn.hidden = false;
        downloadBtn.hidden = false;
        downloadBtn.href = objectUrl;
        paintProgress();
      })
      .catch(() => {
        audio.src = src;
        audio.addEventListener(
          "loadedmetadata",
          () => {
            duration = audio.duration || 0;
            ready = true;
            playBtn.disabled = false;
            speedBtn.hidden = false;
            downloadBtn.hidden = false;
            paintProgress();
          },
          { once: true }
        );
        audio.addEventListener(
          "error",
          () => showFailed("Media was not saved on the server"),
          { once: true }
        );
        audio.load();
      });
  }

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          beginLoad();
          observer.disconnect();
        }
      },
      { rootMargin: "120px" }
    );
    observer.observe(root);
  } else {
    beginLoad();
  }

  playBtn.disabled = true;
  return root;
}
