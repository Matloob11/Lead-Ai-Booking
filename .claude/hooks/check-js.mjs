/**
 * Refuses to let a JavaScript file be saved if it does not parse.
 *
 * This project has no build step and no CI. A file goes from an editor straight
 * onto a live server, and a stray bracket there is not a red squiggle — it is
 * `docker compose ps` showing a service stuck in Restarting while WhatsApp
 * messages queue up behind it. That happened twice in one afternoon.
 *
 * Reads Claude Code's PostToolUse payload on stdin and exits 2 — a blocking
 * error — when `node --check` refuses the file, so the reason is put back in
 * front of whoever wrote it rather than found later on the server.
 *
 * Anything that is not a JavaScript file, and any payload it cannot read, exits
 * 0: a hook that guesses is worse than one that stays out of the way.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (raw += chunk));

process.stdin.on("end", () => {
  let file = "";
  try {
    const payload = JSON.parse(raw || "{}");
    file = payload.tool_input?.file_path || payload.tool_response?.filePath || "";
  } catch {
    process.exit(0);
  }

  if (!/\.(js|mjs|cjs)$/i.test(file)) process.exit(0);

  // `node --check file.js` is not a check at all once the file holds an import
  // or an export. It answers 0 for `export function f( { return 1 }` — for
  // anything, in fact — because it parses a .js file as a CommonJS script,
  // finds ESM syntax, and gives up quietly instead of failing. Everything in
  // this repo is an ES module, so the plain form was passing every file it was
  // ever pointed at, and said so in a way that read exactly like a pass.
  //
  // --input-type=module is the form that parses, and it only exists for input
  // arriving on stdin — as a file argument node refuses it outright. So the
  // source is piped in rather than named.
  //
  // Which type to declare is decided from the file itself and never by falling
  // back: "try as a module, and if that fails try as a script" reintroduces the
  // whole problem, because the script form passes every ES module ever written,
  // broken or not.
  let source = "";
  try {
    source = readFileSync(file, "utf8");
  } catch {
    process.exit(0); // deleted or moved between the write and this check
  }

  const isModule =
    /\.mjs$/i.test(file) ||
    (!/\.cjs$/i.test(file) && /^[ \t]*(import|export)[\s{('"*]/m.test(source));

  try {
    execFileSync(
      process.execPath,
      ["--check", `--input-type=${isModule ? "module" : "commonjs"}`],
      { input: source, stdio: ["pipe", "pipe", "pipe"] }
    );
  } catch (error) {
    // node names the offending line but calls the file [stdin]; the real name
    // is put back, because "SyntaxError in [stdin]" helps nobody.
    const detail = String(error.stderr || error.message).replaceAll("[stdin]", file).trim();
    console.error(`${file} does not parse, so it must not be deployed:\n${detail}`);
    process.exit(2);
  }
});
