/**
 * The panel's icons, drawn rather than typed.
 *
 * Inline SVG for the same reason the rest of this folder has no build step: the
 * page is served from a plain directory and the Bitrix frame's CSP refuses
 * external hosts, so an icon font or a CDN sprite would arrive as a blank box.
 *
 * Every path is on a 24×24 grid and strokes with `currentColor`, so an icon
 * takes the colour of whatever it sits in and needs no variant per theme.
 *
 * `icon()` returns null for a name it does not hold, and el() drops null
 * children — so a missing icon is a button with no glyph, not a broken one.
 * Add the name here rather than reaching for an emoji.
 */

const SVG = "http://www.w3.org/2000/svg";

const PATHS = {
  search: ["circle:11,11,7", "M20 20l-3.2-3.2"],
  send: ["M4.5 12l15.5-7.5-4 15.5-4-6.5-7.5-1.5z", "M11.9 13.6L20 4.5"],
  check: ["M4.5 12.5l4.5 4.5L19.5 6.5"],
  checkDouble: ["M2 12.6l4 4L14.5 8", "M9.5 12.6l4 4L22 8"],
  clock: ["circle:12,12,8.4", "M12 7.4V12l3 1.8"],
  alert: ["M12 4.6l8.4 14.8H3.6z", "M12 10v4", "M12 17h.01"],
  chat: ["M20.5 12.4c0 4-3.8 7.2-8.5 7.2a10 10 0 01-2.7-.36L4 21l1.3-3.7A6.8 6.8 0 013.5 12.4c0-4 3.8-7.2 8.5-7.2s8.5 3.2 8.5 7.2z"],
  users: ["circle:9,8.5,3.6", "M2.8 19.4c.6-3.2 3.2-5 6.2-5s5.6 1.8 6.2 5", "M16.4 5.4a3.6 3.6 0 010 6.6", "M17.6 14.8c2.2.5 3.8 2.2 4.2 4.6"],
  phone: ["M7 2.6h10a1.6 1.6 0 011.6 1.6v15.6A1.6 1.6 0 0117 21.4H7a1.6 1.6 0 01-1.6-1.6V4.2A1.6 1.6 0 017 2.6z", "M10.4 18.4h3.2"],
  link: ["M10 13.6a4 4 0 006 .5l2.2-2.2a4 4 0 00-5.6-5.6l-1.2 1.2", "M14 10.4a4 4 0 00-6-.5L5.8 12.1a4 4 0 005.6 5.6l1.2-1.2"],
  power: ["M12 3.4v8.2", "M17.5 6.6a7.6 7.6 0 11-11 0"],
  image: ["M4.2 4.6h15.6v14.8H4.2z", "circle:9,9.6,1.6", "M4.2 16.4l4.6-4 3.4 3 3-2.4 3.6 3.2"],
  file: ["M13.4 3.2H7a1.8 1.8 0 00-1.8 1.8v14a1.8 1.8 0 001.8 1.8h10a1.8 1.8 0 001.8-1.8V8.6z", "M13.4 3.2v5.4h5.4"],
  close: ["M6.4 6.4l11.2 11.2", "M17.6 6.4L6.4 17.6"],
  refresh: ["M20.2 11.4a8.2 8.2 0 10-.9 4.6", "M20.6 5.6v5.8h-5.8"],
  qr: ["M4.2 4.2h6v6h-6z", "M13.8 4.2h6v6h-6z", "M4.2 13.8h6v6h-6z", "M13.8 13.8h2.6v2.6h-2.6z", "M19.8 13.8v6h-6"],
  reply: ["M9.4 6.2L4 11.6l5.4 5.4", "M4 11.6h9a7 7 0 017 7v.8"],
  smile: ["circle:12,12,8.6", "M8.6 14.2a4.4 4.4 0 006.8 0", "M9.2 9.6h.01", "M14.8 9.6h.01"],
  mic: ["M12 3.4a2.6 2.6 0 012.6 2.6v6a2.6 2.6 0 11-5.2 0v-6A2.6 2.6 0 0112 3.4z", "M6 11.4a6 6 0 0012 0", "M12 17.4v3.2"],
  video: ["M3.6 6.6h11.2v10.8H3.6z", "M14.8 10.4l5.6-3v9.2l-5.6-3z"],
  location: ["M12 21s6.4-5.6 6.4-10.4a6.4 6.4 0 10-12.8 0C5.6 15.4 12 21 12 21z", "circle:12,10.4,2.4"],
  paperclip: ["M20.4 11.6l-8.2 8.2a5 5 0 01-7-7l8.6-8.6a3.4 3.4 0 014.8 4.8l-8.6 8.6a1.8 1.8 0 01-2.5-2.5l7.9-7.9"],
  inbox: ["M3.4 12.6L6 5.2h12l2.6 7.4v5.6a1.6 1.6 0 01-1.6 1.6H5a1.6 1.6 0 01-1.6-1.6z", "M3.4 12.6h4.4a2 2 0 002 2h4.4a2 2 0 002-2h4.4"],
};

/**
 * @param {string} name  a key of PATHS
 * @param {{size?: number, stroke?: number}} [options]
 * @returns {SVGSVGElement|null}
 */
export function icon(name, { size = 16, stroke = 1.7 } = {}) {
  const shapes = PATHS[name];
  if (!shapes) return null;

  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", String(stroke));
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  // Decorative: the text beside it already says what the control does, and a
  // screen reader announcing "image" between the label and the button is noise.
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  for (const shape of shapes) {
    if (shape.startsWith("circle:")) {
      const [cx, cy, r] = shape.slice(7).split(",");
      const circle = document.createElementNS(SVG, "circle");
      circle.setAttribute("cx", cx);
      circle.setAttribute("cy", cy);
      circle.setAttribute("r", r);
      svg.append(circle);
    } else {
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("d", shape);
      svg.append(path);
    }
  }

  return svg;
}

/**
 * Up to two letters for an avatar, from whatever the chat is called.
 *
 * A number falls back to its last two digits: "+971 50 123 4567" has no initials
 * worth taking, and the tail is the part a person recognises.
 */
export function initials(name) {
  const text = String(name || "").trim();
  if (!text) return "?";

  const words = text.replace(/[+_-]+/g, " ").split(/\s+/).filter(Boolean);
  const letters = words
    .map((word) => [...word][0])
    .filter((ch) => /\p{L}/u.test(ch))
    .slice(0, 2)
    .join("");

  if (letters) return letters.toUpperCase();
  const digits = text.replace(/\D/g, "");
  return digits ? digits.slice(-2) : "?";
}

/**
 * A stable colour for an avatar, so the same chat is the same colour every time.
 *
 * Hue only — saturation and lightness are fixed, and the CSS picks how far to
 * take them per theme. Random colours per repaint would make the list flicker
 * on every poll.
 */
export function hueFor(key) {
  const text = String(key || "");
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) % 360;
  return hash;
}
