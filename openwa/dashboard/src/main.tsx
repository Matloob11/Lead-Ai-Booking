import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './i18n';
import './index.css';
// A7: read after index.css so it can override the page layout it adjusts.
import './a7-embedded.css';
// A7: Omni-style liquid glass when Linked devices frames this dashboard.
import './a7-glass-embedded.css';
import App from './App.tsx';

// A7: mark the document when this dashboard is not the top window.
//
// It is opened inside the A7 panel, which already gives it a titled bar and the
// full height of the screen. The page's own padding, heading and strapline
// repeat that bar and eat the room the conversation needs — and `.chats-layout`
// is pinned to `calc(100vh - 12rem)`, which framed leaves a dead strip along the
// bottom, because 100vh in a frame is the frame.
//
// Set before first paint, and before React runs, so the framed layout is what
// gets drawn rather than something that visibly rearranges itself. Wrapped
// because reading window.top throws across origins in some browsers, and a
// dashboard that fails to start is a far worse outcome than an untrimmed one.
try {
  const framed = window.self !== window.top;
  const wantEmbed = new URLSearchParams(window.location.search).get('embedded') === '1';
  if (framed || wantEmbed) {
    document.documentElement.dataset.embedded = 'true';
    // Linked panel always uses the glass-dark palette (matches Omni WhatsApp).
    document.documentElement.setAttribute('data-theme', 'dark');
  }
} catch {
  // Cross-origin frame: being unable to see the top window is itself the answer.
  document.documentElement.dataset.embedded = 'true';
  document.documentElement.setAttribute('data-theme', 'dark');
}

// Apply the stored theme BEFORE first paint: useTheme() only runs inside Layout, so standalone
// routes (Login) otherwise flash the OS theme on reload even when the user explicitly picked one.
// Mirrors applyTheme: an explicit choice sets data-theme; system/absent leaves it to the media query.
// Embedded Linked devices keeps dark (set above) so it matches the Omni glass theme.
if (document.documentElement.dataset.embedded !== 'true') {
  const storedTheme = localStorage.getItem('openwa_theme');
  if (storedTheme === 'light' || storedTheme === 'dark') {
    document.documentElement.setAttribute('data-theme', storedTheme);
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
