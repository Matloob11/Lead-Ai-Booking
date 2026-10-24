"""
C44 Playwright: Leads popup Community select + payload.community.
Every send blocked. Needs Matloob storage_state.

  python ops/bitrix-aws/a7_c44_playwright.py --state path/to/matloob.json --lead-id 123
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CRM = "https://crm.a7grouprealestatedxb.com"
JS_MARK = "A7_LEAD_WA_V20"


def install_send_guard(page) -> None:
    page.add_init_script(
        """
        (() => {
          window.__a7_c44_blocked = 0;
          window.__a7_c44_payloads = [];
          const block = (url, body) => {
            const u = String(url || "");
            const b = String(body || "");
            return u.includes("a7_lead_wa.php") && (u.includes("action=send") || b.includes("action=send"));
          };
          const origFetch = window.fetch;
          window.fetch = function(input, init) {
            const url = typeof input === "string" ? input : (input && input.url) || "";
            const body = init && init.body;
            if (block(url, body)) {
              window.__a7_c44_blocked += 1;
              try {
                const params = new URLSearchParams(String(body || ""));
                const raw = params.get("payload") || "";
                window.__a7_c44_payloads.push(JSON.parse(raw));
              } catch (e) {}
              return Promise.resolve(new Response(JSON.stringify({ok:false,error:"blocked"}), {
                status: 499, headers: {"Content-Type": "application/json"}
              }));
            }
            return origFetch.apply(this, arguments);
          };
        })();
        """
    )
    page.route("**/api/campaigns/**", lambda route: route.abort())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--lead-id", type=int, required=True)
    ap.add_argument("--shot", default="files/temp/c44-popups/community.png")
    args = ap.parse_args()
    Path(args.shot).parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=args.state)
        page = context.new_page()
        install_send_guard(page)
        page.goto(f"{CRM}/crm/lead/list/", wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(2000)
        has = page.evaluate(f"() => !!window.{JS_MARK}")
        print("V20", "yes" if has else "no")
        opened = page.evaluate(
            """async (id) => {
              const form = new URLSearchParams();
              form.set('action', 'context');
              form.set('sessid', (window.BX && BX.bitrix_sessid && BX.bitrix_sessid()) || '');
              form.set('entity', 'lead');
              form.append('lead_ids[]', String(id));
              const res = await fetch('/bitrix/tools/a7_lead_wa.php', {
                method: 'POST', credentials: 'same-origin',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: form.toString()
              });
              const data = await res.json();
              if (!data || !data.ok) return {ok:false, err: data && data.error};
              const btn = document.querySelector('.a7-lwa-btn');
              if (btn) btn.click();
              return {ok:true, leads: (data.leads||[]).length};
            }""",
            args.lead_id,
        )
        print("OPEN", json.dumps(opened))
        page.wait_for_timeout(1500)
        # Tick Lead AI and read Community default.
        page.evaluate(
            """() => {
              const box = document.querySelector('.a7-lwa-leadai input[type=checkbox]');
              if (box && !box.checked) { box.click(); }
            }"""
        )
        page.wait_for_timeout(500)
        info = page.evaluate(
            """() => {
              const sel = document.querySelector('select.a7-lwa-community');
              return sel ? {value: sel.value, options: sel.options.length, visible: sel.offsetParent !== null} : null;
            }"""
        )
        print("COMMUNITY", json.dumps(info))
        page.screenshot(path=args.shot, full_page=True)
        browser.close()
    if not info or info.get("value") != "International City":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
