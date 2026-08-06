/**
 * The band across the top that says a number is being used in a way that gets
 * numbers banned.
 *
 * A QR-linked phone is a personal WhatsApp account. There are no approved
 * templates behind it, no rate limit agreed with Meta, and no appeal worth the
 * name — when one goes, it goes, and every conversation on it goes with it.
 * The behaviour that causes it is not subtle and the server counts it; this is
 * only the part that makes sure somebody sees it before it happens rather than
 * after.
 *
 * Deliberately at the top of the whole panel and not inside a dialog. It is a
 * warning about the thing the agent is in the middle of doing.
 */

const POLL_MS = 60_000; // behaviour measured in days does not move in seconds

const LOOK = {
  high: { chip: "At risk of a ban", cls: "safety--high" },
  watch: { chip: "Worth watching", cls: "safety--watch" },
};

/**
 * @param {object} deps  el, api, asList and withPlus from the panel — passed in
 *                       rather than imported so this module has no opinion
 *                       about where they live, and app.js keeps one import.
 */
export function installSafetyBanner({ el, clear, api, asList, withPlus, mount }) {
  const bar = el("div.safety", { hidden: true });
  mount(bar);

  const dismissed = new Set();

  async function refresh() {
    let rows = [];
    try {
      rows = asList(await api("api/risk"), "risk");
    } catch {
      // A banner that cannot be drawn is not worth an error on screen. The
      // numbers behind it are still being counted server-side either way.
      return;
    }

    // Highest first, and nothing that is fine.
    const worrying = rows
      .filter((r) => (r.level === "high" || r.level === "watch") && !dismissed.has(keyFor(r)))
      .sort((a, b) => (a.level === "high" ? -1 : 1) - (b.level === "high" ? -1 : 1));

    if (!worrying.length) {
      bar.hidden = true;
      clear(bar);
      return;
    }

    clear(bar);
    bar.hidden = false;
    bar.className = `safety ${LOOK[worrying[0].level].cls}`;

    for (const row of worrying) {
      const look = LOOK[row.level];
      const name = row.label || withPlus(row.phone_number) || `Phone #${row.session_id}`;

      const close = el("button.safety__x", { type: "button", title: "Hide until this changes" }, [
        icon("close", { size: 14 }),
      ]);
      close.addEventListener("click", () => {
        // Keyed on the reasons, not on the phone: hiding it once must not hide
        // the next warning, which is a different fact about the same number.
        dismissed.add(keyFor(row));
        refresh();
      });

      bar.append(
        el("div.safety__row", {}, [
          el("span.safety__chip", {}, [look.chip]),
          el("div.safety__body", {}, [
            el("div.safety__who", {}, [name]),
            // Every reason names the number behind it. "High risk" on its own
            // tells somebody to worry without telling them what to stop doing.
            ...row.reasons.map((reason) => el("div.safety__why", {}, [reason])),
            el("div.safety__advice", {}, [
              row.level === "high"
                ? "Stop starting new conversations from this number today. Reply to people who wrote first — that is not what gets a number banned."
                : "Keep an eye on it. Replying to people who wrote first is safe; starting conversations with people who did not is what counts against a number.",
            ]),
          ]),
          close,
        ])
      );
    }
  }

  const keyFor = (row) => `${row.session_id}:${row.level}:${row.reasons.join("|")}`;

  refresh();
  setInterval(refresh, POLL_MS);
  return { refresh };
}
