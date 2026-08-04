import "dotenv/config";
import path from "node:path";

const digits = (value) => String(value || "").replace(/\D/g, "");

const list = (name) =>
  String(process.env[name] || "")
    .split(",")
    .map(digits)
    .filter(Boolean);

export const config = {
  port: Number(process.env.PORT || 8300),
  databaseUrl: process.env.DATABASE_URL || "",
  dataRoot: process.env.DATA_ROOT || path.resolve("data"),
  maxMediaBytes: Number(process.env.MAX_MEDIA_MB || 25) * 1024 * 1024,

  /** Numbers already on the WhatsApp Business Platform. See guardNumber. */
  blockedNumbers: new Set(list("BLOCKED_NUMBERS")),

  /**
   * Whether group chats are kept at all.
   *
   * This is a sales inbox: a chat is one customer an agent is answering. A
   * linked phone also belongs to a person, and carries their family groups and
   * neighbourhood threads, which are neither the company's business to store
   * nor useful to an agent looking for a customer. Off by default; set
   * IGNORE_GROUPS=false if a group is ever worth keeping.
   */
  ignoreGroups: String(process.env.IGNORE_GROUPS ?? "true").toLowerCase() !== "false",

  // Empty until the two halves are joined; see README, "Joining it up".
  webhookUrl: process.env.WEBHOOK_URL || "",
  webhookToken: process.env.WEBHOOK_TOKEN || "",
};

export const authRoot = path.join(config.dataRoot, "auth");
export const mediaRoot = path.join(config.dataRoot, "media");

/**
 * Refuses a number that is already live on the Business Platform.
 *
 * Linking one of those by QR risks a permanent ban on a verified number
 * carrying the company's approved templates, and a ban cannot be undone. The
 * check is here rather than in the UI because it has to hold for every route
 * into the service — the panel, the API, and anything added later.
 *
 * @throws {Error} when the number must not be linked
 */
export function guardNumber(phoneNumber) {
  const number = digits(phoneNumber);
  if (!number) return "";

  if (config.blockedNumbers.has(number)) {
    throw new Error(
      `${number} is registered on the WhatsApp Business Platform. Linking it by ` +
        `QR would put a verified number and its approved templates at risk of a ` +
        `permanent ban. Use a separate SIM.`
    );
  }
  return number;
}
