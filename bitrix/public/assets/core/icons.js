/**
 * Inline SVG icon set.
 *
 * Emoji were standing in for icons and looked like emoji: different shapes at
 * different weights, coloured by the platform, and rendered differently on
 * every machine. These are drawn on one 24×24 grid with a single stroke weight
 * and inherit `currentColor`, so a tick can be blue in one place and grey in
 * another with no extra assets.
 *
 * Inline rather than an icon font because the panel's CSP blocks every external
 * host, and a font would be one more thing that can fail to load.
 */

const NS = "http://www.w3.org/2000/svg";

/**
 * Each entry is a list of [tag, attributes] shapes on a 24×24 canvas.
 * Stroke-only: no fills, so they stay legible at 14px.
 */
const ICONS = {
  paperclip: [["path", { d: "M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" }]],

  smile: [
    ["circle", { cx: 12, cy: 12, r: 10 }],
    ["path", { d: "M8 14s1.5 2 4 2 4-2 4-2" }],
    ["path", { d: "M9 9h.01M15 9h.01" }],
  ],

  send: [
    ["path", { d: "M22 2 11 13" }],
    ["path", { d: "M22 2 15 22l-4-9-9-4Z" }],
  ],

  image: [
    ["rect", { x: 3, y: 3, width: 18, height: 18, rx: 2 }],
    ["circle", { cx: 8.5, cy: 8.5, r: 1.5 }],
    ["path", { d: "m21 15-5-5L5 21" }],
  ],

  file: [
    ["path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }],
    ["path", { d: "M14 2v6h6" }],
    ["path", { d: "M9 13h6M9 17h6" }],
  ],

  // icon() returns null for a name it does not hold, and el() drops a null
  // child — so a missing icon is not a fallback glyph, it is a button with
  // nothing in it at all. These four were being asked for and rendered blank.
  fileText: [
    ["path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }],
    ["path", { d: "M14 2v6h6" }],
    ["path", { d: "M16 13H8M16 17H8M10 9H8" }],
  ],

  folder: [
    ["path", { d: "M4 20a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2z" }],
  ],

  eye: [
    ["path", { d: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" }],
    ["circle", { cx: 12, cy: 12, r: 3 }],
  ],

  trash: [
    ["path", { d: "M3 6h18" }],
    ["path", { d: "M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" }],
    ["path", { d: "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" }],
    ["path", { d: "M10 11v6M14 11v6" }],
  ],

  mic: [
    ["rect", { x: 9, y: 2, width: 6, height: 11, rx: 3 }],
    ["path", { d: "M19 10v2a7 7 0 0 1-14 0v-2" }],
    ["path", { d: "M12 19v3" }],
  ],

  play: [
    ["polygon", { points: "8 5 19 12 8 19 8 5", fill: "currentColor", stroke: "none" }],
  ],

  pause: [
    ["rect", { x: 7, y: 5, width: 4, height: 14, rx: 1, fill: "currentColor", stroke: "none" }],
    ["rect", { x: 13, y: 5, width: 4, height: 14, rx: 1, fill: "currentColor", stroke: "none" }],
  ],

  video: [
    ["path", { d: "m23 7-7 5 7 5V7Z" }],
    ["rect", { x: 1, y: 5, width: 15, height: 14, rx: 2 }],
  ],

  pin: [
    ["path", { d: "M12 17v5" }],
    ["path", { d: "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16h14v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z" }],
  ],

  archive: [
    ["path", { d: "M21 8v13H3V8" }],
    ["path", { d: "M23 3H1v5h22z" }],
    ["path", { d: "M10 12h4" }],
  ],

  download: [
    ["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }],
    ["path", { d: "m7 10 5 5 5-5" }],
    ["path", { d: "M12 15V3" }],
  ],

  close: [["path", { d: "M18 6 6 18M6 6l12 12" }]],
  chevronLeft: [["path", { d: "m15 18-6-6 6-6" }]],
  chevronRight: [["path", { d: "m9 18 6-6-6-6" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
  minus: [["path", { d: "M5 12h14" }]],

  zoomReset: [
    ["path", { d: "M3 2v6h6" }],
    ["path", { d: "M3.51 15a9 9 0 1 0 2.13-9.36L3 8" }],
  ],

  refresh: [
    ["path", { d: "M21 2v6h-6" }],
    ["path", { d: "M20.49 9a9 9 0 1 0-2.13 9.36L21 16" }],
  ],

  check: [["path", { d: "M18 6 7 17l-5-5" }]],

  // Delivered/read. The two ticks are offset rather than overlaid — overlapping
  // them at 15px made the pair read as a single tick with a stray stroke.
  checkDouble: [
    ["path", { d: "M18 6 7 17l-5-5" }],
    ["path", { d: "m22 10-7.5 7.5L13 16" }],
  ],

  clock: [
    ["circle", { cx: 12, cy: 12, r: 10 }],
    ["path", { d: "M12 6v6l4 2" }],
  ],

  alert: [
    ["path", { d: "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" }],
    ["path", { d: "M12 9v4M12 17h.01" }],
  ],

  users: [
    ["path", { d: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" }],
    ["circle", { cx: 9, cy: 7, r: 4 }],
    ["path", { d: "M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" }],
  ],

  hash: [["path", { d: "M4 9h16M4 15h16M10 3 8 21M16 3l-2 18" }]],
  menu: [["path", { d: "M4 6h16M4 12h16M4 18h16" }]],
  phone: [
    ["path", { d: "M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" }],
  ],
  copy: [
    ["rect", { x: 9, y: 9, width: 13, height: 13, rx: 2, ry: 2 }],
    ["path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }],
  ],
  user: [
    ["path", { d: "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" }],
    ["circle", { cx: 12, cy: 7, r: 4 }],
  ],
  bell: [
    ["path", { d: "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" }],
    ["path", { d: "M13.73 21a2 2 0 0 1-3.46 0" }],
  ],
  messageSquare: [
    ["path", { d: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" }],
  ],
  shield: [
    ["path", { d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" }],
  ],
  zap: [
    ["polygon", { points: "13 2 3 14 12 14 11 22 21 10 12 10 13 2" }],
  ],
  globe: [
    ["circle", { cx: 12, cy: 12, r: 10 }],
    ["path", { d: "M2 12h20" }],
    ["path", { d: "M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" }],
  ],
  mapPin: [
    ["path", { d: "M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" }],
    ["circle", { cx: 12, cy: 10, r: 3 }],
  ],
  location: [
    ["path", { d: "M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" }],
    ["circle", { cx: 12, cy: 10, r: 3 }],
  ],
  star: [
    ["polygon", { points: "12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" }],
  ],
  starFill: [
    ["polygon", { points: "12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2", fill: "currentColor" }],
  ],
  forward: [
    ["polyline", { points: "15 17 20 12 15 7" }],
    ["path", { d: "M4 18v-2a4 4 0 0 1 4-4h12" }],
  ],
  // Forward's mirror image: the arrow turns back on itself.
  reply: [
    ["polyline", { points: "9 17 4 12 9 7" }],
    ["path", { d: "M20 18v-2a4 4 0 0 0-4-4H4" }],
  ],
  smartphone: [
    ["rect", { x: 5, y: 2, width: 14, height: 20, rx: 2 }],
    ["path", { d: "M12 18h.01" }],
  ],
  moreVertical: [
    ["circle", { cx: 12, cy: 12, r: 1 }],
    ["circle", { cx: 12, cy: 5, r: 1 }],
    ["circle", { cx: 12, cy: 19, r: 1 }],
  ],
  userCheck: [
    ["path", { d: "M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" }],
    ["circle", { cx: 8.5, cy: 7, r: 4 }],
    ["polyline", { points: "17 11 19 13 23 9" }],
  ],
  userX: [
    ["path", { d: "M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" }],
    ["circle", { cx: 8.5, cy: 7, r: 4 }],
    ["line", { x1: 18, y1: 8, x2: 22, y2: 12 }],
    ["line", { x1: 22, y1: 8, x2: 18, y2: 12 }],
  ],
};

/**
 * @param {keyof ICONS} name
 * @param {{size?: number, className?: string, title?: string}} options
 * @returns {SVGElement|null} null for an unknown name, so callers can pass
 *          through a message kind that has no icon without branching.
 */
export function icon(name, { size = 18, className = "", title = "" } = {}) {
  const shapes = ICONS[name];
  if (!shapes) return null;

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", title ? "false" : "true");
  svg.setAttribute("focusable", "false");
  svg.classList.add("icon");
  if (className) svg.classList.add(...className.split(" ").filter(Boolean));

  if (title) {
    const node = document.createElementNS(NS, "title");
    node.textContent = title;
    svg.append(node);
  }

  for (const [tag, attributes] of shapes) {
    const shape = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) shape.setAttribute(key, value);
    svg.append(shape);
  }
  return svg;
}

/** Icon for a WhatsApp message kind, or null for text and templates. */
export const KIND_ICON = {
  image: "image",
  sticker: "image",
  video: "video",
  audio: "mic",
  document: "file",
  album: "image",
  pinned_message: "pin",
};

export const iconForKind = (kind, options) => {
  const name = KIND_ICON[String(kind || "").toLowerCase()];
  return name ? icon(name, options) : null;
};
