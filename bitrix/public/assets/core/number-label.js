/**
 * Compact "which of our lines is this?" label.
 *
 * Titles are often just the agent's name. Two people named the same thing on
 * a UAE line and a UK line then look identical in a picker. The dial code
 * (971 / 44 / …) is the bit they need before they send.
 */

const DIALS = [
  "971",
  "966",
  "974",
  "973",
  "965",
  "968",
  "961",
  "44",
  "91",
  "92",
  "20",
  "27",
  "49",
  "33",
  "39",
  "34",
  "61",
  "86",
  "81",
  "1",
];

export function dialCode(phone) {
  const digits = String(phone || "").replace(/\D/g, "");
  if (!digits) return "";
  for (const code of DIALS) {
    if (digits.startsWith(code)) return code;
  }
  return digits.slice(0, 2);
}

/**
 * @param {object | null | undefined} number
 * @returns {string} e.g. "Mabriha · 971"
 */
export function numberNameWithDial(number) {
  if (!number) return "—";
  const phone = String(number.phone_number || "").replace(/\D/g, "");
  const code = dialCode(phone);
  const title = String(number.title || number.label || "").trim();
  const titleDigits = title.replace(/\D/g, "");
  const titleIsPhone = Boolean(titleDigits && phone && titleDigits === phone);
  const name = title && !titleIsPhone ? title : phone ? `+${phone}` : "—";
  if (code && !name.includes(code)) return `${name} · ${code}`;
  return name;
}
