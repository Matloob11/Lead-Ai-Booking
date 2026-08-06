"""Let the deployment say who may frame the OpenWA dashboard.

helmet defaults to `frame-ancestors 'self'` and sends X-Frame-Options: SAMEORIGIN.
The A7 panel opens this dashboard from Bitrix, which is a different origin, so both
headers refuse to render it and the frame comes up blank with nothing to explain it.

Read from the environment rather than hard-coded: unset leaves upstream behaviour
byte for byte, which keeps this patch re-appliable after an update.
"""

import io
import sys

PATH = "/opt/openwa-trial/OpenWA/src/main.ts"

CSP_ANCHOR = """          objectSrc: ["'none'"],"""

CSP_PATCH = """          objectSrc: ["'none'"],
          // Local patch (A7 deployment): the dashboard is opened inside the Bitrix
          // panel, a different origin, and helmet's default `frame-ancestors 'self'`
          // refuses to render it there with nothing in the frame to say why. Taken
          // from the environment so the permitted embedders are configuration; an
          // unset value keeps upstream behaviour unchanged.
          frameAncestors: (process.env.FRAME_ANCESTORS || "'self'")
            .split(/\\s+/)
            .filter(Boolean),"""

GUARD_ANCHOR = "      noSniff: true,"

GUARD_PATCH = """      // X-Frame-Options cannot name two origins and a browser applies it beside
      // the CSP, so SAMEORIGIN would refuse the frame whatever frame-ancestors
      // says. Dropped only once the deployment has named its embedders above;
      // frame-ancestors supersedes it and can express what it cannot.
      frameguard: process.env.FRAME_ANCESTORS ? false : undefined,
      noSniff: true,"""


def apply(text, anchor, patch, what):
    seen = text.count(anchor)
    if patch.split("\n")[1].strip() in text:
        print(f"{what}: already patched, left alone")
        return text
    if seen != 1:
        sys.exit(f"{what}: anchor matched {seen} times, expected exactly 1 — not patching")
    print(f"{what}: patched")
    return text.replace(anchor, patch)


with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

source = apply(source, CSP_ANCHOR, CSP_PATCH, "frame-ancestors")
source = apply(source, GUARD_ANCHOR, GUARD_PATCH, "frameguard")

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
