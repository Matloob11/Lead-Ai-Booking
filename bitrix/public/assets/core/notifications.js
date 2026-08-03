/**
 * Browser Sound & Desktop Push Notifications Manager
 */

const SOUND_KEY = "a7wa_sound_enabled";
const DESKTOP_KEY = "a7wa_desktop_enabled";

export function isSoundEnabled() {
  const val = localStorage.getItem(SOUND_KEY);
  return val === null ? true : val === "true";
}

export function setSoundEnabled(enabled) {
  localStorage.setItem(SOUND_KEY, String(enabled));
}

export function isDesktopEnabled() {
  const val = localStorage.getItem(DESKTOP_KEY);
  return val === null ? true : val === "true";
}

export function setDesktopEnabled(enabled) {
  localStorage.setItem(DESKTOP_KEY, String(enabled));
}

export async function requestNotificationPermission() {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission !== "denied") {
    const result = await Notification.requestPermission();
    return result === "granted";
  }
  return false;
}

let audioCtx = null;

export function playChime() {
  if (!isSoundEnabled()) return;
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    if (!audioCtx || audioCtx.state === "closed") {
      audioCtx = new AudioCtx();
    }
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }

    const now = audioCtx.currentTime;
    
    // Tone 1: C5 (523.25 Hz)
    const osc1 = audioCtx.createOscillator();
    const gain1 = audioCtx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(523.25, now);
    gain1.gain.setValueAtTime(0.15, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
    osc1.connect(gain1);
    gain1.connect(audioCtx.destination);
    osc1.start(now);
    osc1.stop(now + 0.3);

    // Tone 2: E5 (659.25 Hz)
    const osc2 = audioCtx.createOscillator();
    const gain2 = audioCtx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(659.25, now + 0.12);
    gain2.gain.setValueAtTime(0.2, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
    osc2.connect(gain2);
    gain2.connect(audioCtx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.45);
  } catch (err) {
    console.warn("Audio chime failed:", err);
  }
}

export function notifyNewMessage({ contactName, messageText, conversationId, onClick } = {}) {
  playChime();

  if (!isDesktopEnabled() || typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  
  // Only trigger desktop notification if window is currently blurred/hidden
  if (!document.hidden && document.hasFocus()) return;

  try {
    const notif = new Notification(contactName || "New WhatsApp Message", {
      body: messageText || "Received a new message",
      icon: "/assets/favicon.ico",
      tag: conversationId ? `wa-conv-${conversationId}` : "wa-msg",
      renotify: true,
    });

    notif.onclick = () => {
      window.focus();
      onClick?.();
      notif.close();
    };
  } catch (err) {
    console.warn("Desktop notification failed:", err);
  }
}
