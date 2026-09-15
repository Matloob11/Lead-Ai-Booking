/** Tiny DOM helpers — enough structure to avoid a framework and a build step. */
import { icon } from "./icons.js";

/**
 * el("div.row", {onclick}, [child, "text"]) → HTMLElement.
 * The tag accepts `tag.class.class` shorthand; everything else is a property
 * (onclick, value, disabled) or an attribute (data-*, aria-*, src, href).
 */
export function el(spec, props = {}, children = []) {
  const [tag, ...classes] = spec.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");

  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      node.className = [node.className, value].filter(Boolean).join(" ");
    } else if (key === "text") {
      node.textContent = value;
    } else if (key in node && key !== "list") {
      node[key] = value;
    } else {
      node.setAttribute(key, value === true ? "" : value);
    }
  }

  for (const child of [children].flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

/** Waits for `ms` of quiet before firing — used for the search box. */
export function debounce(fn, ms = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

const TIME = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const DAY = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });

/** Chat-app style stamp: time today, date before that. */
export function stamp(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const sameDay =
    date.getDate() === today.getDate() &&
    date.getMonth() === today.getMonth() &&
    date.getFullYear() === today.getFullYear();
  return sameDay ? TIME.format(date) : DAY.format(date);
}

const DATE_FULL = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "long", year: "numeric" });

/** Local calendar day, for deciding where a date separator goes. */
export function dayKey(iso) {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/** "Aaj" / "Kal" / "14 March 2026" for the separator between days. */
export function dayLabel(iso) {
  const key = dayKey(iso);
  if (!key) return "";
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86400000);
  if (key === dayKey(today.toISOString())) return "Aaj";
  if (key === dayKey(yesterday.toISOString())) return "Kal";
  return DATE_FULL.format(new Date(iso));
}

/** Minutes from now until the given instant; negative once it has passed. */
export function minutesUntil(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Number.isFinite(ms) ? Math.floor(ms / 60000) : null;
}

/** "3h 12m" until the given instant, or null once it has passed. */
export function untilText(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const minutes = Math.floor(ms / 60000);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
}

/** "1.4 MB" — sizes are shown next to files the agent is about to send. */
export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  const value = n / 1024 ** i;
  return `${value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)} ${units[i]}`;
}

/**
 * Centred dialog over the panel. Returns { close, box } so callers can swap
 * their own content in and dismiss it themselves.
 */
export function modal(title, content, { wide = false, onClose } = {}) {
  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    onClose?.();
  };

  const onKey = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    close();
  };

  const box = el("div.modal__box", { class: wide ? "modal__box--wide" : "" }, [
    el("div.modal__head", {}, [
      el("h2.modal__title", {}, [title]),
      el("button.modal__x", { type: "button", onclick: close, title: "Close" }, [icon("close", { size: 14 })]),
    ]),
    content,
  ]);

  const backdrop = el("div.modal", { onclick: (event) => event.target === backdrop && close() }, [box]);

  document.addEventListener("keydown", onKey, true);
  document.body.append(backdrop);
  return { close, box };
}

/** Initials for the avatar circle. */
export function initials(name) {
  // Letters only — "Matloob (test)" must not become "M(".
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .map((part) => part.replace(/[^A-Za-z\u00C0-\u024F]/g, ""))
    .filter(Boolean);
  if (!parts.length) {
    const digits = String(name || "").replace(/\D/g, "");
    return digits ? digits.slice(-2) : "#";
  }
  return (parts[0][0] + (parts[1]?.[0] || "")).toUpperCase();
}

/**
 * Brief confirmation or failure notice, bottom-centre.
 *
 * Replaces window.alert for things the agent does not have to acknowledge —
 * a forward that went through, a star that did not. alert() blocks the whole
 * frame and has to be dismissed, which is far too much ceremony for feedback
 * the agent will glance at once.
 *
 * @param {"ok"|"err"} [kind]
 */
export function toast(message, kind = "ok") {
  let host = document.querySelector(".toasts");
  if (!host) {
    host = el("div.toasts");
    document.body.append(host);
  }

  const node = el("div.toast", { class: `toast--${kind}` }, [String(message)]);
  host.append(node);

  // Fade out first, then remove — the class change drives the CSS transition.
  setTimeout(() => {
    node.classList.add("toast--out");
    setTimeout(() => node.remove(), 250);
  }, kind === "err" ? 4200 : 2400);

  return node;
}
