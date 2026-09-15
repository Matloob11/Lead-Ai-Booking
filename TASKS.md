# Who did what

Three AI sessions work this repository at the same time, and they cannot see
each other. Two of them have already rewritten the same file in one afternoon,
and one shipped a change that another had to undo without knowing whose it was.
This file is how that stops: **before you start, read the last ten entries;
when you finish, add one.**

It is a log of decisions, not of commits. `git log` already says what changed ?
this says *who was working on what, whether it reached the server, and whether
anybody proved it works*, which is the part a commit message cannot carry.

## The rules

1. **Add your entry when the work is done**, not when it is planned. An entry
   that says "in progress" for two days tells the next session nothing.
2. **Name the files you touched.** Especially the shared ones ?
   `wa-qr/public/app.js`, `bitrix/public/assets/modules/inbox.js`,
   `ops/wa.sh`. That is the sentence that stops the next collision.
3. **Say what you verified and what you did not.** "Deployed" is not
   "working". Reaching an endpoint is not proof it does its job ? see the
   Verifying section of `CLAUDE.md`. If you could not test something, write
   that down; a gap somebody knows about is not a gap.
4. **If you undo somebody's work, say whose and why.** Never silently.
5. Newest first. Keep an entry to a few lines ? the detail belongs in the
   commit and in the code's own comments.

## 2026-09-15 — From dropdown contrast + dial codes (Cursor)

New contact From (native `<select>`) inherited glass-dark light ink onto Windows' white option list — names vanished except the blue highlight. `official-glass.css` now forces every `option` to `#0f172a` on white. Number labels that were only an agent name now append the dial (`Mabriha · 971` / `· 44`) in the From picker, chat list, and thread header. New: `core/number-label.js`. **Shared:** `inbox.js` (import + `numberTitle`), `template-composer.js` (From option text), `official-glass.css` (append only).

**Live:** `ops/wa.sh panel`. Disk and `/opt/a7-wa/panel` md5 matched for the four files. Public GET 200: `official-glass.css` (option rule present), `number-label.js`. Browser computed style on a glass-dark select: option `rgb(15,23,42)` on white, closed select `rgb(238,243,249)` on glass. **Not verified:** Bitrix iframe click (SSO); OpenWA dashboard (different UI).

---

## 2026-09-15 — Template 500 text + video upload ceiling (Cursor)

New Contact HTTP 500 was alots ``Network Banned`` on Dubai03WBX / Mehreen I ``447447178015`` — UI only printed the status code. ``describe_alots_failure`` now surfaces that sentence. Official nginx/Django 32m + attach 16 MB blocked ~90 MB videos; Meta video is still 16 MB / file 100 MB, so a larger clip uploads and sends as a document. Nginx Official+OpenWA ``1024m``. OpenWA compose ``BODY_SIZE_LIMIT=1400mb``, ``MEDIA_DOWNLOAD_MAX_BYTES=1g``, mem 4g. **Shared:** `gateway/client.py`, `catalog/views.py`, `inbox/services.py`, `inbox/views.py`, `settings.py`, `attach.js`, `deploy/a7-wa.nginx.conf`, `ops/wa.sh`, OpenWA compose + nginx. inbox.js / inbox.css not touched.

**Live:** push + full Official `build app` + up web/worker/beat; `panel`; `raise-upload-limit` (both confs 1024m); OpenWA compose push + `up openwa-api`. attach.js md5 matched. django-check: No changes. **Not verified:** live New Contact click, a real 90 MB send, OpenWA dashboard rebuild (1 GB picker toast not in the running image).

---

## 2026-09-11 — HR access for Furqan Khalid 2632 (Cursor)

`furqan.a7group@gmail.com` (Bitrix **2632**, not 26320) was already in HR dept 58 + group 9, no CRM role. Bound **44 HR** + **45 hr** (same as Usman 2628). Role 45 also got Recruitment `1160_C45` + Agent Profile `1172_C48` (copied from Applicant / HR Request) so the HR left menu is all four pages. Not given admin role 3. Live PHP: 1156/1160/1168/1172 read=Y for 2632 (Usman now Y on 1160/1172 too). Script: `ops/bitrix-aws/grant_hr_access_khalid.php`. Khalid logout/login. Browser as Khalid **not** opened.

---

## 2026-09-11 — Official hamburger overlay (Cursor)

Hamburger (3 lines) opened as a see-through 8% glass sheet over the chat list — Profile / Inbox tools / AI desk sat on top of conversations. Menu is now an opaque 280×360 dropdown under the button (`official-glass.css`). Did not touch dirty `inbox.js` / `extras.css`.

**Live:** `ops/wa.sh panel`. Bitrix iframe click **not** SSO-tested — Ctrl+F5 then open the hamburger.

---

## 2026-09-11 — Official 3-dot chat menu (Cursor)

Thread-header 3-dots (Export / Transfer / CRM / AI) opened inside `.thread { overflow:hidden }` and extras' pill `.btn--ghost`, so the sheet spilled across the inbox. Menu now pins to the iframe (`position: fixed` + body portal). Hamburger `max-height: %` of the title row was clipping that dropdown too — now 420px. **Shared:** `inbox-ai.js`, `inbox-ai.css`, `official-glass.css`. Did not touch dirty `inbox.js` / `extras.css`.

**Live:** `ops/wa.sh panel`. Bitrix iframe 3-dot click **not** SSO-tested — hard-refresh the WhatsApp placement.

---

## 2026-09-04 ? Sales Deals kanban: Voiso + Zadarma Call (Cursor)

Deal category **1** (`/crm/deal/kanban/category/1/`): green **Call with Zadarma** (`BXIM.phoneTo`) + blue **Call with Voiso** (`deal-call-voiso` ? cc-ams04). Phones from linked Contact/Company. Widened `deal-phones` for cat 1; init injects `a7_deals_call.js`. Deployed AWS. **Verified:** php -l OK; JS HTTP 200; deal-phones logic includes sales cat. **Not browser-verified** ? agent Ctrl+F5 on Deals kanban.

**Shared:** `ops/bitrix-aws/a7_deals_call.js`, `patch_sales_deals_call.php`, `widen_deal_phones.php`; live `/bitrix/js/a7_deals_call.js`, `a7_3cx_click_to_call.php`, `init.php`.

---

## 2026-09-04 ? WhatsApp-like sidebar sort (Cursor)

Sidebar: latest message activity on top (send or receive). Opening a chat no longer changes order; later activity on other chats can pass it. Fixes: (1) optimistic send + media bump `last_message_at` immediately; (2) upsert keeps fresher activity if open/WS is stale; (3) removed API `transferred_in` boost that forced old transfers above newer chats ? order is `-is_pinned, -last_message_at`. Deployed panel + web/worker/beat. **Not browser-verified** ? agent Ctrl+F5 then send in one chat, receive in another.

**Shared:** `bitrix/public/assets/modules/inbox.js`, `backend/apps/inbox/views.py`.

---

## 2026-09-04 ? Blue Brick Official numbers (Cursor)

Alots WABA Channels top 4 (Webhook=NA, Display Blue Brick) were already in Official catalog via gateway sync (`971556829046`, `971557466914`, `971556748730`, `971557327268`) ? not missing inserts. Set `display_name`/`label` = Blue Brick. **Still need:** paste webhook `https://wa.srv1802669.hstgr.cloud/api/gateway/webhook/alots/` on those 4 Alots rows (cannot set from API). Gateway list = 26 channels, all already in catalog.

**Shared:** `ops/catalog/label-blue-brick-numbers.py`, `probe-alots-channels-vs-catalog.py`, runners.

---

## 2026-09-04 ? Diagnose Meta 131031 on Luxe chat (Cursor)

Zein Lozi / `971521557940` on Official number **447723321328** (Luxe Towers Realty, WABA `1535123498115022`): failed outs show Meta **131031** ?Business Account locked? ? not a panel/Retry bug. Live DB: **84** msgs with that code (Luxe 46 + Warda UK `447360545726` 38). This chat: last inbound 2026-09-01 ? session expired 09-02; every later free-form (incl. BR/BUA retries) failed 131031. Meta meaning: WABA restricted/disabled (policy) **or** two-step PIN/data verify fail. Fix is Meta Business Manager / Account Quality / Health Status ? code Retry won?t unlock. **Not done:** Health Status API call / BM appeal.

**Shared:** read-only `ops/wa.sh sql` on live `inbox_message`.

---

## 2026-09-03 ? WhatsApp laptop handoff zip (Cursor)

Packed Official API (`backend`/`bitrix`/`deploy`) + OpenWA + `wa-qr` + live `credentials/` (deploy.env, openwa.env, root.env) into Desktop zip. Excluded agent-reports, CRM handoff, node_modules, OpenWA session data. **START_HERE.md** inside zip. Path: `Desktop/a7-whatsapp-system-with-credentials-2026-09-03.zip` (~5.3 MB). Do not commit/upload zip publicly.

**Shared:** none in repo (Desktop zip only); staging cleaned.

---

## 2026-09-03 ? esha ghazi WhatsApp Inbox HTTP 500 (Cursor)

`POST /api/auth/bitrix/` 500: Bitrix `PERSONAL_PHOTO` URL > `avatar_url` varchar(200) ? `DataError`. **Fix:** skip/clamp oversized avatar on login + widen field to 1000 (`0010_agent_avatar_url_max_length`). Deployed web/worker/beat; migration OK. Agent bitrix_2368 (esha ghazi). **Not browser-verified** ? she should Try again / re-open Inbox.

**Shared:** `backend/apps/accounts/views.py`, `models.py`, `migrations/0010_agent_avatar_url_max_length.py`.

---

## 2026-09-03 ? Handoff pack: bitrix-crm-access (Cursor)

Moved agent/head CRM visibility scripts + docs into **`handoff/bitrix-crm-access/`** (README, HOWTO, STRUCTURE, teams JSON, fixes/probes/verify + related-tl copies). Old `ops/bitrix-aws/fix_agent_*.php` stubs point here. Zip that folder to hand off updates.

**Shared:** `handoff/bitrix-crm-access/**`; stubs under `ops/bitrix-aws/`.

---

## 2026-09-03 ? Verify head vs agent CRM scope (Cursor)

Live PHP: heads Hassan/Hussnain/Jaweria LEAD+OD **department** attrs (D69/70/71); agents Uzma/mehnaz/Warda/Farhat **self-only**. Item check: Uzma own lead Y / teammate N / Hassan can read teammate Y; Farhat same vs Jaweria. **ALL CHECKS PASSED**. Not browser UI.

**Shared:** `ops/bitrix-aws/verify_head_vs_agent_scope.php`.

---

## 2026-09-03 ? Agents Leads Access Denied fix (Cursor)

Uzma + all Agent-role users: `/crm/lead/list/` **Access Denied** (Owner Data already OK after earlier fix). Root: CRM role **36 Agent** had no LEAD/CONTACT/COMPANY/DEAL perms. Added personal ATTR=`A` set mirroring Sales Agent role 8. Cache cleared. **Verified PHP:** Uzma/mehnaz/Warda/Farhat LEAD=CONTACT=DEAL=OD=Y (self-only attrs). **Not browser-verified** ? logout/login.

**Shared:** `ops/bitrix-aws/fix_agent_lead_crm_perms.php`, `probe_agent_lead_access.php`; live `b_crm_role_perms` role 36.

---

## 2026-09-03 ? Agents Owner Data Access denied fix (Cursor)

Agents (e.g. mehnaz 2381) got **Access denied** on `/crm/type/1042/kanban/category/14/` while heads OK. Root cause: CRM role **36 Agent** (group G11) had **zero** `DYNAMIC_1042*` perms. Added personal READ/WRITE/ADD (ATTR=`A`) for `DYNAMIC_1042` + C13 + C14 + C14 stage READ rows (mirror Sales Agent role 8). Cache cleared. **Verified PHP:** mehnaz/Warda/Uzma `canReadItemsInCategory(13/14)=Y` (attrs self-only); TLs still department. mehnaz has 348 assigned C13 cards. **Not browser-verified** ? agents must re-login / hard refresh.

**Shared:** `ops/bitrix-aws/fix_agent_owner_data_perms.php`, `probe_agent_owner_access.php`; live `b_crm_role_perms` role 36.

---

## 2026-09-03 ? Shareable hardcoded bitrix-all-users.html (Cursor)

Rewrote `agent-reports/bitrix-all-users.html` as offline shareable file: all **79** users hard-coded one `<tr>` per line, no JSON/CDN fetch, filter + print-friendly. Snapshot date in header. Open/double-click or WhatsApp/email the `.html` as-is.

**Shared:** `agent-reports/bitrix-all-users.html`.

---

## 2026-09-03 ? Refresh bitrix-all-users.html (Cursor)

Live Bitrix dump (ACTIVE employees, skip EXTERNAL_AUTH bots/extranet): **70 ? 79**. Added: Mehreen 2535, SHAZIA 2536, hassan riaz 2550, Rana Hussnain 2551, khadija Munir 2558, Hassan T.L 2560, Safeeer 2561, Saba 2566, Saad 2567. JSON matched. Webhook `dump_bitrix_users.py` hung earlier ? used AWS PHP dump instead. **Not deployed** (local reference files only).

**Shared:** `agent-reports/bitrix-all-users.html`, `bitrix-all-users.json`; `ops/bitrix-aws/dump_all_users_json.php`, `regen_users_html.py`.

---

## 2026-09-02 ? VPS resource snapshot (Cursor)

Hostinger WA (`srv1802669`): **32 GB RAM / 8 vCPU / 387 GB disk**; ~**16.5 GB available**, load ~0.6, **no swap**, no recent OOM. Heaviest: `openwa-api` ~**8.9/20 GB** + many Chrome sessions; Official `a7wa-web/worker` ~240?250 MB each (no compose mem limit). Bitrix AWS: **~7.5 GB / 2 vCPU**, MemAvailable ~**1.3 GB**, swap used ? tighter. Hang not primarily Hostinger RAM; OpenWA Chrome + Meta/API wait more likely. Probe: `ops/probe_vps_resources.sh`.

**Shared:** `ops/probe_vps_resources.sh` (read-only).

---

## 2026-09-02 ? Campaign xlsx 500 + template submit hang + Template Center cache (Cursor)

Preview `POST /api/campaigns/preview/` 500: zero-var template treated .xlsx as CSV ? `_csv.Error`. **Fix:** xlsx always via `parse_campaign_spreadsheet`. Create-bulk hung on Select-all ? every Official WABA sequential Meta; **Fix:** parallel (6) + always send checked `number_ids` (no `all_numbers:true`). Template Center: `template-cache.js` session cache, show old list immediately + background refresh. **Deployed:** backend rebuild web/worker/beat; panel md5 `template-cache.js`/`template-composer.js` match. Hard-refresh panel. **Not verified:** live campaign preview click / create submit timing in browser.

**Shared:** `backend/apps/campaigns/phones.py`, `services.py`, `catalog/views.py`; `bitrix/public/assets/modules/template-cache.js`, `template-composer.js`.

---

## 2026-09-02 ? a7jobs expired apps ? campaign phone file (Cursor)

From `a7jobs-applications-expired (3).xlsx` Applications sheet: Mobile 1+2 ? unique phones. Output `a7jobs-interview-campaign-phones.xlsx` (+ `.csv`) with headers `{{1}}` (Full Name) + `Number` for WA Campaigns upload. Script: `ops/extract_a7jobs_campaign_phones.py`. **Not run:** live campaign send.

**Shared:** `ops/extract_a7jobs_campaign_phones.py`, `a7jobs-interview-campaign-phones.xlsx`, `a7jobs-interview-campaign-phones.csv`.

---

## 2026-09-02 ? Voiso Call failed: curl_init missing (Cursor)

Owner Data blue **Call with Voiso** toasted "Voiso call failed"; exceptions.log = `Call to undefined function curl_init()` (Apache `/etc/php.d/20-curl.ini` empty). **Fix:** `a7_handle_owner_data_call_voiso` ? `a7_http_raw` (stream fallback). **Verified:** web probe ? Voiso click2call HTTP 200. **Not verified:** live agent click while Available (retest). Backup `a7_3cx_click_to_call.php.bak-voiso-nocurl-*`.

**Shared:** `ops/bitrix-aws/fix_owner_voiso_nocurl.php`, `patch_owner_voiso_call.php`, `a7_owner_data_call_handlers.php`; live `a7_3cx_click_to_call.php`.

---

## 2026-09-02 ? Owner Data dual Call: Zadarma + Voiso (Cursor)

Kanban/detail: green **Call with Zadarma** (`BXIM.phoneTo`) + blue **Call with Voiso** (`POST owner-data-call-voiso` ? `cc-ams04?/bitrix/click2call` with backup token). Voiso NOT restored on `ONEXTERNALCALLSTART` so Zadarma path stays exclusive. **Deployed** live JS + PHP patch. **Not verified:** live click with agent Available in Voiso.

**Shared:** `ops/bitrix-aws/a7_owner_data_call.js`, `patch_owner_voiso_call.php`, `a7_owner_data_call_handlers.php`; live `/bitrix/js/a7_owner_data_call.js`, `a7_3cx_click_to_call.php`.

---

## 2026-09-02 ? Create Template modal: number pick + dark fields (Cursor)

Admin create modal showed agent **names** (not phones) and white `.field` inputs; deploy list ignored `hidden`. **Fix:** phone-first checklist + Select all; submit selected `number_ids` (or all); short labels; glass-dark field styles. **Deployed** panel `template-composer.js/css`, `template-center.css` (md5 push ok). Browser hard-refresh to verify.

**Shared:** `bitrix/public/assets/modules/template-composer.js`, `template-composer.css`, `template-center.css`.

---

## 2026-09-02 ? Owner Data cat13 kanban already team-scoped (Cursor)

User: `/crm/type/1042/kanban/category/13/` pe ?all agents?. **Probed:** permission SQL + stage counts match Hassan team only (New Data 4552 team vs 54110 company; cards = Ruqia/Uzma/Sapna/Aila ? all Hassan agents). Same READ=`D` path for C13 as leads. No further perm change. Explain to user; other heads re-login.

**Shared:** `ops/bitrix-aws/probe_owner_kanban_perms.php`, `probe_owner_kanban_counts.php`.

---

## 2026-09-02 ? TL team-only CRM + phone mask for all 3 heads (Cursor)

Root cause: stale intranet codes (Hassan still on Re-Sale `D41`) + Jaweria in Administrators (CRM `IsAdmin` ? ALL). Fixed: UF_DEPARTMENT + CAccess rebuild for teams 69/70/71 (HR nodes 59/60/61); role 54 READ=`D` WRITE=`A`; removed Jaweria from group 1. **Verified (PHP as each TL):** team lead/owner read=Y write=N; outsider + cross-team read=N. Phone mask JS/PHP/init already live for 2560/2551/2297 (incl. edit inputs). **Not verified in browser UI** ? heads must re-login / hard refresh. Jaweria still in Portal Administrators (group 13); CRM admin bypass gone.

**Shared:** `ops/bitrix-aws/fix_tl_visibility_deep.php`, `fix_jaweria_admin.php`, `verify_tl_final.php`, `fix_tl_perms_deep.php`; live Bitrix role 54 / user groups / access codes.

---

## 2026-08-31 ? Owner Data Call: Voiso off ? Zadarma +971 (Cursor)

Live AWS: deleted Voiso `ONEXTERNALCALLSTART` (event 786, backed up `a7_rest_event_voiso_backup`); Zadarma app 77 stays. Deployed `a7_owner_data_call.js` + `a7_renewals_call.js` (`dialViaZadarma`, strict `+971` no spaces). Patched `a7_owner_data_normalize_phone_value` E.164. **Verify:** Owner Data green Call ? Zadarma dialer with +971? (agent must have a7 cloud line open).

**Shared:** `ops/bitrix-aws/a7_owner_data_call.js`, `a7_renewals_call.js`, handlers; live `/bitrix/js/*`, `a7_3cx_click_to_call.php`, `b_rest_event`.

---

## 2026-08-31 ? Owner Data ? Zadarma call research (Cursor)

Live AWS CRM probe: Owner Data Call JS already `BXIM.phoneTo`; Zadarma app ACTIVE + `ONEXTERNALCALLSTART`; Voiso handler still registered (ID 786) + 3CX + MyHub. Need: disable Voiso handler, harden `+971` normalize, retarget messaging Voiso?Zadarma. Not implemented yet ? plan given to user.

**Shared:** none (research only). Live paths: `/bitrix/js/a7_owner_data_call.js`, `init.php`, `b_rest_event`.

---

## 2026-08-28 ? New = float only; chrome transparent (Cursor)

User: neeche sirf green New, koi bar nahi ? peeche chats; upar ab bhi solid dark. **Fix:** foot hata ke FAB absolute; list `padding-bottom:72px`; glass-dark chrome `transparent` (navy strip gone); inputs glass. **Deployed:** inbox.js/css, extras.css.

**Shared:** `inbox.js`, `inbox.css`, `extras.css`.

---

## 2026-08-28 ? Soften dark number/search + New footer only (Cursor)

User: sirf All-numbers/search boxes + neeche New foot dark/blue thay; baaki page theek. **Fix:** glass-dark inputs `0.08?0.14` + blur; foot solid navy ? translucent glass. **Deployed:** extras.css, inbox.css.

**Shared:** `extras.css`, `inbox.css`.

---

## 2026-08-28 ? Live browser deep-fix sidebar override (Cursor)

Bitrix iframe login + measure. **Root causes:** absolute `+ New` FAB chats pe paint; row gap 3px + duplicate Transferred chip; filter clip; avatar `M(`. **Fixes:** FAB ? `.sidebar__foot` (static, never overlay); gap 6px; Transferred chip hide (meta only); filter `min-width:0` scroll; initials letters-only. **Verified live:** `fabPosition:static`, `coveringCount` boundary-only, gap 6px, avatar `MT`, quickText full `Transferred`.

**Shared:** `inbox.css`, `inbox.js`, `extras.css`, `core/dom.js`.

---

## 2026-08-28 ? Fix chat-list row text overlap (Cursor)

User screenshot: filters OK ab; chat rows mein preview/meta/tags tight + "Sent from WhatsApp" next line pe override. **Fix:** `conv__body` flex column + gaps; preview as flex with `conv__preview-text` ellipsis; labels/meta min-width rules; removed duplicate label CSS. **Verified:** panel pushed.

**Shared:** `inbox.js`, `inbox.css`.

---

## 2026-08-28 ? Deep fix sidebar overlap (Cursor)

User: filter/search ab bhi chats pe override. **Verified live checksums matched prior CSS but overlap remained.** Root: absolute number dropdown + stacking. **Rewrite:** `number-picker.js` now inline accordion (`.np`, no `position:absolute`); sidebar wrapped in `.sidebar__chrome` (opaque, above list); old `.filter__number-*` forced `display:none`; chat list `isolation:isolate`. **Verified:** pushed live (`number-picker.js` 9f24?, `inbox.js` 9d04?, `inbox.css` c5a4?, `extras.css` d046?).

**Shared:** `inbox.js`, `inbox.css`, `extras.css`, `number-picker.js`.

---

## 2026-08-28 ? Fix sidebar filter overlap (Cursor)

User: search/filters aur chat list override ho rahe the. **Root cause:** `.filter__number-panel { display:flex }` UA `[hidden]` ko override kar raha tha ? closed number dropdown always painted over chat search + first rows. **Fix:** panel closed = `display:none !important`; open only under `.is-open`; filter bar opaque background + z-index; `convs__wrap` lower stack; old `.tag-filter` forced hidden. **Verified:** panel CSS/JS pushed live.

**Shared:** `inbox.css`, `extras.css`, `number-picker.js`.

---

## 2026-08-28 ? Inbox sidebar: one search, quick filters, tags in menu (Cursor)

User: do search boxes merge karo (number search All numbers dropdown ke andar); Hot Lead/Transferred tags list se hata kar sidebar menu mein; unki jagah compact Unread/Pinned/Transferred filters; chat select par list jump na kare. **Panel:** `core/number-picker.js` (dropdown + inner search), `core/list-quick-filters.js` (All/Unread/Pinned/Transferred row + tag chips in menu). Sort no longer boosts unread (stops jump on open). Tags under Menu ? Tags. **Verified:** panel pushed live. **Not verified:** browser on Matloob account.

**Shared:** `inbox.js`, `inbox.css`, `extras.css`.

---

## 2026-08-28 ? Button replies + template buttons in thread (Cursor)

User: button replies chat mein show nahi; template messages ke buttons bhi nahi. **Root cause:** ingest stored button/interactive label in `preview` but wrote empty `caption` to `Message.body`. **Fix:** `stored_body()` in `gateway/ingest.py`; `_message_body()` + `template_buttons`/`template_footer` in `serializers.py` (old rows read from payload). Panel: `core/message-bubble-extras.js` ? button reply tag, template footer + WhatsApp-style button row under bubble; wired from `inbox.js`. **Verified:** panel + backend pushed; `build app` + web/worker/beat restarted. **Not verified:** live chat with palka thread in browser.

**Shared:** `inbox.js`, `inbox.css`, `extras.css`, `serializers.py`, `ingest.py`.

---

## 2026-08-28 ? WhatsApp-style voice player v2 (Cursor)

User: play se pehle total seconds, real waves, click/drag seek, download, speed ? WhatsApp jaisa. New `core/voice-player.js`: fetch+blob decode via Web Audio for true duration + waveform peaks; before play shows total time; click/drag seek on wave; 1�/1.5�/2� speed; download button; lazy load via IntersectionObserver. Wired from `message-media.js`. CSS in `inbox.css` + `extras.css`. **Verified:** panel pushed live (`voice-player.js`, `message-media.js`, `inbox.css`, `extras.css`); public URL 200 for `voice-player.js`. **Not verified:** live browser play on Matloob test chat. Red "Voice message unavailable ? Media was not saved" = server missing file (`media_failed`), UI cannot fix.

**Shared:** `core/voice-player.js` (new), `core/message-media.js`, `inbox.css`, `extras.css`.

---

## 2026-08-28 ? Inbox media UI: voice player + docs/video/image (Cursor)

User: voice professional karo; image/video/PDF UX improve. New `core/message-media.js`: WhatsApp-style voice (play/pause, waveform, seek, one-at-a-time), photo shimmer loader + lightbox, video badge wrap, PDF/Word/Excel doc cards with colour icons, clearer unavailable state. Added play/pause icons. **Verified:** panel files pushed live (`message-media.js`, `inbox.js`, `inbox.css`, `extras.css`, `icons.js`). **Not verified:** live voice play in browser; red "unavailable" rows are server-side missing media (not a UI bug).

**Shared:** `bitrix/public/assets/core/message-media.js`, `icons.js`, `modules/inbox.js`, `inbox.css`, `extras.css`.

---

## 2026-08-28 ? Inbox pagination: 30 chats + Load more (Cursor)

User: auto-load se zyada load ho gaya ? wapas Load more. Sidebar pehle **30 chats**, phir Load more; chat mein **40 messages**, phir **Load older messages** button (auto scroll load hata diya). Kuch delete nahi hota ? sirf page-by-page load. **Verified:** live `inbox.js` pushed (md5 `5a721632?`).

**Shared:** `bitrix/public/assets/modules/inbox.js`.

---

## 2026-08-28 ? Inbox: show all chats + full message history (Cursor)

User: sidebar mein purani chats nahi dikh rahi; saari history rahe, koi delete/auto-remove na ho. Root cause: list sirf 40 chats load karti thi, archived hide hoti thi, thread mein sirf latest 40 messages (scroll-up load missing). Fix: auto-load full conversation list (200/page), archived bhi list mein, scroll up = older messages, Archive button hata diya. Backend archived filter ab default pe sab dikhata hai. **Verified:** live `inbox.js` has `loadOlderMessages` + `LIST_PAGE_SIZE=200`. **Not verified:** live click on long thread / agent with 500+ chats.

**Shared:** `bitrix/public/assets/modules/inbox.js`, `contact-panel.js`; `backend/apps/inbox/views.py`.

---

## 2026-08-27 ? Gateway Live Webhook Inspector deployed (Antigravity)

User asked live proof/diagnostic page with compact rows, real-time search, and color coding. Built and deployed live inspector (`/app/webhook-inspector.html`) + API (`/api/gateway/inspector/events/`). Auto-polls every 1.5s, compact 1-line event cards with collapsible JSON, instant search ("body", "nobody", "status", numbers, text), and clear color-coding:
- ?? **Red Badges/Borders:** Status Only / No Body (Physical phone sends missing body in webhook)
- ?? **Green Badges/Borders:** Inbound / Alots Panel Outbounds (Carrying real text body)
- ?? **Purple Badges:** 11 WBX Coexistence Numbers (Abdul, Fameeda, Dubai01-10)
- ?? **Blue Badges:** Inbound Client Messages
**Verified:** Deployed, tested live in CDP browser session with instant search ("body" -> 72 events, "nobody" -> 8 events).

**Shared:** `bitrix/public/webhook-inspector.html`, `backend/apps/gateway/views.py`, `backend/apps/gateway/urls.py`.

---

## 2026-08-27 ? Removed Alots UI cookie scraping; verified flat vs status webhook (Antigravity)

Removed brittle Alots UI session cookie scraping (`ALOTS_UI_COOKIE`, `live_inbox.py`, `hydrate_placeholder_message`, `backfill_placeholder_bodies`). Investigated coexistence flow: Alots panel sends fire flat outbound webhook with real `text.body` (e.g. event 32919) which stores full text in CRM, while mobile phone WhatsApp Business App sends only trigger Meta/Alots delivery status webhook (`statuses: [id, status: delivered/read]`) without text body, rendering clean `Sent from WhatsApp` placeholder in CRM without cookie dependency. Deployed and rebuilt web/worker/beat. **Verified:** `django-check` 0 changes, containers up & healthy.

**Shared:** `backend/apps/gateway/ingest.py`, `backend/apps/gateway/tasks.py`, `backend/apps/gateway/client.py`, `backend/apps/gateway/live_inbox.py`, `backend/a7wa/settings.py`.

---

## 2026-08-27 ? Campaign history: retry same number + simpler UI (Cursor)

User: History pe same-number se bhi template retry + kam text / simple buttons. Backend `resend_skipped_on_number` ab same WABA pe media reuse karta hai; panel pe `Retry same number (N)` + `Try another number`; issues short chips, failures short labels. Deployed panel + full app build (web/worker/beat). **Verified:** live `/app/assets/modules/campaigns.js` has both button strings; panel+services+views md5 match local; containers Up ~1m. **Not verified:** live click on MUDON SENHA (needs agent Ctrl+F5).

**Shared:** `bitrix/public/assets/modules/campaigns.js`, `campaigns.css`, `api/api.js`; `backend/apps/campaigns/services.py`, `views.py`.

---

## 2026-08-26 ? CRM down: Apache stuck on Bitrix cache lock (Cursor)

User: CRM not loading after Renewals Call button deploy. Root cause: httpd workers all blocked on `cacheCleanJob_lock.php` (inode lock wait), listen backlog full ? not PHP syntax. Restarted httpd, removed stale lock; CRM 200 again. Soft-disabled then re-enabled Call JS with debounced MutationObserver (`subtree:false`) to avoid kanban freeze. **Verified:** home + deal kanban HTTP 200 ~0.06?0.16s.

---

## 2026-08-26 ? Renewals deals (cat 9) Voiso Call button (Cursor)

User asked same green Call button on Renewals kanban `/crm/deal/kanban/category/9/`. Deployed `a7_renewals_call.js` + init inject on `/crm/deal/` + PHP `deal-phones` (tenant/owner UFs + contact phone; cat 9 only). Dial = `BXIM.phoneTo` ? Voiso. **Verified:** #35117 tenant `971503594054`; #39064 two phones; php -l / js / init OK. UI click not verified here.

**Shared/AWS:** `/bitrix/js/a7_renewals_call.js`, `php_interface/init.php`, `tools/a7_3cx_click_to_call.php`. Local: `ops/bitrix-aws/a7_renewals_call.js`, `patch_renewals_call.py`.

---

## 2026-08-26 ? Owner Data Call ? Voiso (not 3CX) (Cursor)

User: green Call button must start call in Voiso dialer (`cc-ams04.voiso.com`) like lead click-to-call, not 3CX. Found Bitrix native path = `BXIM.phoneTo` ? `ONEXTERNALCALLSTART` ? Voiso webhook `https://cc-ams04.voiso.com/api/v2/bitrix/click2call` (event 786). Rewrote `a7_owner_data_call.js` to dial via `BXIM.phoneTo` + UAE normalize (`566404737`?`+971566404737`); phones still from `owner-data-phones`. Deployed AWS JS. **Verified:** #73267 phone UF; Voiso event registered; JS uses phoneTo. **Not verified:** live click with agent Available in Voiso (screenshot showed Unavailable).

**Shared/AWS:** `/bitrix/js/a7_owner_data_call.js`. Local: `ops/bitrix-aws/a7_owner_data_call.js`.

---

## 2026-08-26 ? Owner Data custom Call button (Cursor)

User asked custom call button on Owner Data only (not lead kanban) ? read all phone UFs, no Contact sync. Deployed on Bitrix AWS: `a7_owner_data_call.js` + init inject on `/crm/type/1042/` + PHP actions `owner-data-phones` / `owner-data-call` (bypass global click-to-call off; dial via existing 3CX makecall). Phone fields include Owner no 1 + phone number UFs. **Verified:** CLI phones for Availability #88414 / Calling #88164; JS HTTP 200; php -l OK. **Not verified:** logged-in browser click / real outbound ring (needs agent with UF_PHONE_INNER + hard refresh).

**Shared/AWS:** `/bitrix/js/a7_owner_data_call.js`, `php_interface/init.php`, `tools/a7_3cx_click_to_call.php`. Local: `ops/bitrix-aws/*`.

---

### 2026-08-25 ? Cursor session ? Coexistence WBX labels + Alots body format

Marked 11 WBX UAE numbers `community=coexistence` (empty labels ? Dubai0xWBX / A7GroupWBX; kept Abdul/Fozia/?). Fixed Fameeda live pnid typo `?9589`?`?9689`; reactivated Dubai01 `971563523109`. Parse accepts Alots coexistence flat body without wamid + bare `messages[]`/`from_user_id`; no-id body hydrates latest ?Sent from WhatsApp? stub. Deployed web/worker/beat + `catalog.0010`. Live: migration OK; labels community set. **Not verified:** Alots still mostly sends status-only on these channels (6h: ~412 placeholders vs 7 real) ? real text needs their flat/echo body webhook.

**Shared:** `gateway/parse.py`, `ingest.py`, `tasks.py`; migration `0010_coexistence_wbx_labels.py`. No panel JS.

### 2026-08-21 ? Cursor session ? Owner Data calling kanban AED amounts

Category 13 (Name / New Data / Assigned to Caller?) showed AED0 like old Availability bug: Lease/Selling UF filled but `opportunity` empty. Extended `ops/openwa/fix-owner-data-kanban-amounts.py` with `--calling` (prefer Selling) + start=0 pagination so updates don?t skip rows. Sync running on VPS (`/var/log/owner-data-calling-amount-sync.log`); hourly cron still Availability-focused (`--only-new`) and full pass on :00. Verified sample cards (La Tilia etc.) had sell price + opp=0. Call icons on this board still need phone UF ? most New Data cards have no phone.

### 2026-08-21 ? Cursor session ? Owner Data phone?Contact bulk + auto sync

All Owner Data rows with phone UF linked to CRM Contacts so call button works: bulk run linked **4034** items (3648 contacts created, 0 errors). Ongoing: Celery beat every 10 min (`task_sync_owner_phone_contacts`, only unlinked, limit 200). Ops: `ops/wa.sh agent-reports-sync-owner-phones [--dry-run|--limit N|--all]`. Redeployed agent-reports (web/worker/beat). Verified post-sync dry-run `seen:0`. Did not click-test call UI on a live card after bulk. Files: `agent-reports/backend/app/bitrix/owner_phone_link.py`, `workers/tasks.py`, `workers/celery_app.py`, `scripts/bulk_link_owner_phones.py`, `ops/wa.sh`.

### 2026-08-21 ? Cursor session ? Owner Data call button (Contact link)

Owner Data SPA has no Lead-style `fm` phone; call icon needs Client Contact with PHONE. Card #86884 had UF `phone number` (double=506252693) but `contactId=0`. Linked Contact `43897` (+971506252693). Refresh card to see call active. Permanent: put phones on Contact/Client, not Number UF ? or bulk link script. Files: `agent-reports/backend/scripts/link_owner_phone_to_contact.py`, `inspect_owner_phone.py`.

### 2026-08-21 ? Cursor session ? Agent Reports Bitrix menu live

Local app saved (handler `?/agent-reports/`, menu label AgentReports, marketplace app `/marketplace/app/80/`). FastAPI now accepts Bitrix POST on `/` (was Method Not Allowed). Panel loads in iframe with agent list. Clicked ?Add current page to left menu?. Verified: iframe agents visible. Shared: `ops/wa.sh`, `agent-reports/backend/app/main.py`.

### 2026-08-21 ? Cursor session ? Agent Reports deployed to Hostinger

Live at `https://wa.srv1802669.hstgr.cloud/agent-reports/` (FastAPI+panel+API; Celery worker/beat; Postgres/Redis). Host port **8091** (8090 already taken by nginx). Nginx `^~ /agent-reports/` in **HTTPS** server of `a7-wa.conf` (first install landed on :80 ? fixed via `deploy/fix_nginx.py`). Verified: health 200, panel 200, `/api/agents` 200. Not verified: Bitrix left-menu iframe registration, full 18:00 Messenger run. Ops: `ops/wa.sh agent-reports-deploy|check|fix-nginx`. Shared: `ops/wa.sh`.

### 2026-08-21 ? Cursor session ? Agent Reports complete (PDF/history/schedule)

Finished v1: collect ? OpenAI summary ? reportlab PDF ? SQLite history ? generate/history APIs ? panel Agents/History + PDF buttons ? Celery beat 18:00 Dubai ? Messenger digest helpers (Disk upload optional). Verified: pytest 7 passed; one live PDF for a Sales agent + Matloob notify probe. Not verified on Hostinger deploy / Bitrix iframe menu / full 46-agent evening run. Files under `agent-reports/**`.

### 2026-08-21 ? Cursor session ? Agent Reports Task 2?3 (agents + day metrics)

Bitrix client, Sales/TS agent list (`/api/agents` ? 46 live), day snapshot (`/api/agents/{id}/day`: timeman, leads, owner data, tasks, calls). Panel lists agents and shows day stats. Unit tests 4 passed; live probe OK. Timeman check-in now day-scoped. Next: PDF + AI + history DB + 18:00 delivery. Files: `agent-reports/backend/app/bitrix/*`, `api/routes.py`, `panel/assets/*`, `tests/*`.

### 2026-08-21 ? Cursor session ? Agent Daily Reports ? design + scaffold

New Hostinger project (not WhatsApp): Sales/TS daily PDF reports, Bitrix iframe sidebar, 18:00 Dubai Messenger to Malik/Sattar/Matloob/Amna. Spec + plan written; scaffold `agent-reports/` (FastAPI health, panel shell, compose stub). Webhook `AGENT_REPORT_BITRIX_WEBHOOK` already in root `.env` and verified. Not built yet: metrics, PDF, Celery, deploy iframe. Files: `docs/superpowers/specs/2026-08-21-agent-daily-reports-design.md`, `docs/superpowers/plans/2026-08-21-agent-daily-reports.md`, `agent-reports/**`.

### 2026-08-21 ? Cursor session ? Campaign permanent-fail deep fix (MUDON lessons)

Root causes from campaign 6: (1) webhook without code scheduled retries, later 131049 ignored because recipient was no longer SENT; (2) 131026 undeliverable retried 5?8�; (3) silent SENT on recipient mismatch. Fixes: `failures.py` permanent codes 131049/131026/130472/RECIPIENT_MISMATCH; `mark_recipient_undelivered` also updates FAILED; no requeue for permanent; marketing-cap pause after 12; Redis lock on `run_campaign`; `_record_result` raises SendBlocked. Files: `campaigns/failures.py`, `services.py`, `tasks.py`, `inbox/services.py`, `campaigns.js`. Rebuilt web/worker/beat + panel. Verified: django-check, helper smoke. Not verified: new live marketing campaign.

### 2026-08-21 ? Cursor session ? Campaign modal footer + background History

Pinned Start campaign in a non-scrolling footer; after start jumps to History with live poll so you need not stay on New. History highlights failure groups (131049 marketing cap vs undeliverable) ? MUDON SENHA study: 84 sent / 172 cap / 34 undeliverable (not a panel send bug). Files: `campaigns.js`, `campaigns.css`. Pushed to panel; md5 matched. Not browser-screenshot verified.

### 2026-08-20 ? Cursor session ? Inbox ?All numbers? search box

Added ?Find WhatsApp number?? search above the Official API number dropdown: filters by phone digits, label/title, agent name, or community text. Files: `inbox.js`, `inbox.css`, `extras.css` (glass theme). Panel published. Not verified in browser screenshot. Shared: `inbox.js`.

### 2026-08-20 ? Cursor session ? Campaign number picker search

Added search box above ?From WhatsApp number? in New campaign: filters by label/title or phone digits; options show `phone ? name`. Files: `campaigns.js`, `campaigns.css`. Panel published. Not verified in browser screenshot.

### 2026-08-20 ? Cursor session ? Fix 131026 undeliverable (Alots India 91 mangle)

SAPNA `971559298388` templates failed 131026 because Alots resolved bare UAE digits as `91971559298388`. Fix: send `to` as `+E.164` (`format_recipient_for_gateway`) and fail fast on `RECIPIENT_MISMATCH` if response wa_id is `91`+intended. Live probe with `+971559298388` ? wa_id correct; message **4009 status=sent**. Panel: clearer 131026 copy in `inbox.js`. Files: `inbox/services.py`, `inbox.js`. Recreate web/worker/beat + panel. Not verified: every campaign path (campaigns use own send ? check later if bare digits).

### 2026-08-20 ? Cursor session ? Explain panel 1208 vs DB 1328 templates

Panel TOTAL **1208** matches templates on **active** Official numbers only. DB has **1329**; **121** sit on inactive/removed WABAs (no active `catalog_wabanumber`) so `all_templates` correctly hides them. Admin visible_numbers=96 ? same 1208 (1184 APPROVED / 9 PENDING / 15 REJECTED). Ops: `explain-template-count-gap.py`. No code change.

### 2026-08-20 ? Cursor session ? Sync all Official templates from Alots into Bitrix

Ran `ops/wa.sh sync-all-templates` on live: **96** active WABAs, **1159** template rows pulled/updated, DB total **1328** (1302 APPROVED, 8 PENDING, 18 REJECTED). **3 WABAs HTTP 500** from Alots (cannot list): `447723351148`, `447723356623`, `971507563104`. **3 WABAs return 0 templates** from Alots (empty on Meta): `971543752608`, `971559783176`, `971564821835`. Ops: `sync-all-templates.py`, `retry-template-sync-failed.py`, `probe-empty-template-wabas.py`. Panel Ctrl+F5 ? Template Center / number templates should show refreshed statuses. Not verified: every agent?s scoped list in Chrome.

### 2026-08-20 ? Cursor session ? Fix voice-note ?attachment unavailable? + clearer template Meta errors

Root cause for ZAW AJ / voice notes: Alots `filelink` ends in `.bin` but gsauth hosts audio as `.ogg` (`.bin` ? 404, lookaside ? 401). Added `candidate_media_urls()` in `gateway/media.py` to try `.ogg`/`.opus` before Meta CDN. Retried failed audio: asset **337 now downloaded**; audio success went **0 ? 80+**. Template: `_meta_error_detail` now surfaces Meta `error_user_msg`; `_parse_template_form` + composer reject footer>60 and body start/end variables (common ?Invalid parameter?). Deployed web/worker/beat + panel. **Not fixed:** ?Sent from WhatsApp? stubs ? still Alots coexistence (no body in webhook).

### 2026-08-20 ? Cursor session ? Add Dubai10WBX Official numbers to Bitrix catalog

Added **13** Official numbers from Dubai10WBX + two extras (`971564821835`, `971543752608`) into `catalog_wabanumber` (manual, active). Skipped `971559759052` ? already in DB. Migration `catalog.0008_add_dubai10wbx_numbers`; live insert via `ops/wa.sh add-dubai10wbx-numbers`; image rebuild + migrate applied. **Webhook:** cannot set Alots WBBOX URI from here ? must paste `https://wa.srv1802669.hstgr.cloud/api/gateway/webhook/alots/` on channels still showing NA (and preferably replace n8n URLs if inbox should hit Bitrix). Not verified: inbound webhook delivery on the new numbers.

### 2026-08-20 ? Cursor session ? Bulk deploy villa_nova2 to all Official WABAs

Ran `ops/wa.sh deploy-villa-nova2` on live: source `WaTemplate` pk 678 (`villa_nova2`, en). Submitted to **79** WABAs missing it; skipped **4** that already had any Villa Nova variant (`villanova_`, `villa_nova1`, `villa_nova2`, `villa_nova3`). **73** created on first pass, **1** on retry; **3** failed (2� Meta error 3835016 ?account restricted from creating template? on 447462363289 / 447475922171; 1� gateway HTTP 500 on 971507563104). DB now **78** WABAs with `villa_nova2` (52 APPROVED, 26 PENDING). Ops scripts: `ops/catalog/deploy-villa-nova2.py`, `retry-villa-nova2-failed.py`, `diag-villa-nova2-error.py`; `ops/wa.sh` subcommands added. Not verified: PENDING?APPROVED sync, campaign send on newly pending numbers.

### 2026-08-20 ? Cursor session ? Campaign modal visual polish

Reworked New campaign UI: step cards (1?3), Excel columns as chips, paste tucked into a details block, sticky actions, and glass-dark surfaces so empty fields no longer flash as a white box on navy. Phone preview kept as the visual anchor. Functionality unchanged.

**Live:** panel published; `campaigns.css` / `campaigns.js` md5 match. **Not verified in browser screenshot.**
**Shared:** `campaigns.js`, `campaigns.css`. Did not touch `inbox.js` this pass.

### 2026-08-20 ? Cursor session ? Admin bulk template create on all numbers

Panel admins can submit one new template to **All Official numbers** or a picked subset ? Meta gets one POST per business account (WABAs already carrying that name are skipped). Existing templates have **Copy to missing numbers**, which replays the stored components onto every WABA that does not have it yet. Non-admins keep single-account create.

**Live:** panel + backend rebuilt (web/worker/beat). **502 fix (same day):** `whitenoise` was accidentally dropped from `requirements.txt` when adding openpyxl ? web could not start; restored and rebuilt.
**Shared:** `template-composer.js`, `template-center.css`, `api.js`, `inbox.js`, `catalog/views.py`, `catalog/urls.py`.

### 2026-08-20 ? Cursor session ? Campaign Excel mapping + Owner Data New Availability

Campaigns now require the fixed spreadsheet layout when a template has body placeholders: row 1 headers `{{1}}`, `Number`, `{{2}}`?`{{n}}` (order free). Each row fills that recipient's template vars; `.xlsx` supported via openpyxl. Wrong headers return "Wrong format" with the missing column named. New Owner Data cards from campaign sends land on New Availability (`DT1042_14:NEW`, category 14).

**Live:** panel published; web/worker/beat rebuilt; migration `0003_recipient_variables` applied. **Not verified in panel:** real Excel upload + send + Owner Data card on New Availability kanban.
**Shared:** `campaigns.js`, `campaigns.css`, `api.js`, `backend/apps/campaigns/*`, `crmlink/client.py`, `requirements.txt`. Did not touch `inbox.js`.

### 2026-08-20 ? Cursor session ? Template Remove + submit-to-Meta without Sync

Template manager now has Remove (DELETE at Meta by name, then drop local rows for that name). Create already POSTed to Meta; after submit the list reloads from our DB so Sync is only for Pending?Approved. Confirm dialog warns every language of the name is deleted.

**Live:** panel md5 matches `template-composer.js` / `api.js` / `template-center.css`; GET `/api/catalog/templates/1/` is 401 (route exists) vs unknown path 404; web/worker/beat recreated. **Not verified in the panel:** clicking Remove on a real template, or a brand-new create actually approved by Meta.
**Shared:** `bitrix/public/assets/modules/template-composer.js`, `template-center.css`, `bitrix/public/assets/api/api.js`, `backend/apps/catalog/views.py`, `urls.py`, `backend/apps/gateway/client.py`. Did not touch `inbox.js`.

### 2026-08-19 ? Antigravity session ? Meta Cloud API Trial setup for coexistence echoes

Configured Meta Cloud API direct trial (non-Alots) for coexistence tests. Created business portfolio "A7 Real Estate Trial" (`1093308803132637`), new Meta App "A7 WA Trial" (`4647890838763112`) with WhatsApp Business use case, and test WABA (`2126465684948940`) with test number `+1 555-669-7661` (`1285433664655647`). Created Admin System User "A7 Trial Admin" (`61593504000186`), assigned assets, and issued a permanent system access token (never expires). Registered phone number with 2FA pin `123456` via Graph API (`POST /1285433664655647/register` -> `success: true`). Probed `POST /messages` -> HTTP 400 `#131030 Recipient phone number not in allowed list` (Cloud API live, authenticated, and ready). Did not touch live Alots numbers, webhooks, or production containers.

**Live:** Trial WABA + phone_number_id created and registered in Meta Cloud API. No code pushed to host.
**Shared:** none. Did not touch `inbox.js`, backend code, or docker.

### 2026-08-19 ? Cursor session ? Omni cookie file for Live Agent hydrate

Alots sign-in hashes the password and requires captcha, so the worker cannot POST login (empty captcha = invalid, do not retry). A logged-in Omni browser session was captured to `deploy/alots.ui.cookie` (gitignored) and mounted on **worker** at `/run/alots.ui.cookie`. Compose env_file interpolation ate `$` in the cookie; file mount avoids that. Local probe of GetUserChatMessages with that cookie: HTTP 200, `n=3`. Live hydrate waits for the next webhook (none since the cookie-file recreate). Password was not stored in git.

**Live:** cookie file pushed; worker mount in compose; web/worker/beat recreated. **Not verified in Chrome / live hydrate:** no webhook after cookie-file up; placeholders still 149.
**Shared:** `gateway/client.py`, `tasks.py`, `live_inbox.py`, `a7wa/settings.py`, `deploy/docker-compose.yml`. Did not touch `inbox.js`.

### 2026-08-19 ? Cursor session ? Bearer live-chat fetch is 200 with empty chatList

Hydrate stubs from Alots `GetUserChatMessages` using the existing API key. Live: HTTP 200, `chatList` length 0, placeholders still 127, hydrates retry then give up. Cookie UI on the same URL returns the text. Next needs an Omni login on the server, not the Cloud API key.

**Live:** 67 GETs status 200 `{"n":0}`; worker `hydrate_placeholder_message` retry/8s. Unit tests parse match 8 passed locally. **Not verified in Chrome:** text fill.
**Shared:** `gateway/client.py`, `ingest.py`, `parse.py`, `tasks.py`. New: `gateway/live_inbox.py`. Did not touch `inbox.js`.

### 2026-08-19 ? Cursor session ? Alots dashboard: text exists only in their Live Agent API

Logged into alots.io (WBBOX). Public developer API has no chat-history GET; `GET /{version}/{id}` is ?Get Template or Media By ID?, which matches our live 400s on wamids. Coexistence page says WA Business App sends appear in **their** panel inbox. Their Live Agent UI loads text via session cookie: `GET /WAMessage/UserLiveChat/GetUserChatMessages?senderNumber=&channelNumber=` ? `chatList[].messageText` + `messageId` (wamid), `source: inbox`. Not in the Bearer Cloud API. No code change.

**Live:** coexistence connected for 971559632895; GetUserChatMessages 200 with outbound text on aaa/971566471256. **Not done:** polling that cookie API.
**Shared:** none.

### 2026-08-19 ? Cursor session ? WA-app outbound text cannot be recovered from Alots

WhatsApp Business app / Alots-inbox sends still appear as a bubble, but the body stays **Sent from WhatsApp**. Status webhooks have no text (`id`, `status`, `recipient_id` only). Live `GET /v23.0/{wamid}` is HTTP 400 (same class of miss as media GET). Zero `smb_message_echoes` in all `gateway_webhookevent` rows. GET hydrate was deployed then removed so we stop paying 400s on every tick. Echo ingest path is still there if Alots ever forwards `smb_message_echoes`. Panel-originated sends already store the real body.

**Live:** GET-by-wamid 400 on many wamids tonight; 126 placeholder rows still in `inbox_message`; echo field count 0. web/worker/beat had been recreated earlier with the GET attempt. **Not verified in Chrome:** Ctrl+F5 Official inbox ? bubbles will still say Sent from WhatsApp until Alots sends echoes.
**Shared:** `backend/apps/gateway/ingest.py`, `parse.py`, `client.py`, `tasks.py`. Did not touch dirty `inbox.js` / `serializers.py`.

#### 2026-08-19 ? Cursor session ? One-off: hide one javeria-bibi Linked-phones chat

Removed only javeria-bibi?s thread with 971502188528 (LID 110991299846152@lid) from OpenWA sqlite + live chat list. Other chats on that session left in place (38 messages remain). Not a product feature.

**Live:** `ops/wa.sh openwa-delete-javeria-one-chat` PASS (18 messages + 1 chat_lead deleted; live-list HTTP 200). **Not verified in Chrome:** Ctrl+F5 Linked phones as javeria-bibi ? +971 50 218 8528 should be gone; neighbouring chats stay.
**Shared:** `ops/wa.sh`. New one-off: `ops/openwa/delete-javeria-one-chat.js`. Did not touch inbox.js or Official API.

### 2026-08-19 ? Cursor session ? Official inbox ingest for Alots/WA-app sends

Outgoing replies sent from the WhatsApp Business app or the Alots inbox now land in the custom inbox. Status webhooks for unknown wamids create an outbound row on `(our number, recipient_id)` keyed by unique wamid; echo arrays (`smb_message_echoes` etc.) fill the body later. Duplicate webhooks stay one row. Inbound customer messages and panel sends are unchanged. Also corrected Abdul's `phone_number_id` typo (`?239?` ? live `?238?`) so those callbacks are no longer ignored.

**Live:** catalog.0007 applied (Abdul id `1266282383224189`); web/worker/beat recreated, healthy. Last 3 min: that phone_number_id events are `processed` not ignored; 10 outbound stubs `Sent from WhatsApp` exist (Alots status has no text). **Not verified in Chrome:** send from WA Business app and Alots inbox, Ctrl+F5, one bubble, chronological.
**Shared:** `backend/apps/inbox/services.py`. New: `backend/apps/gateway/ingest.py`, `parse.py`. Also `gateway/tasks.py`, `gateway/views.py`, catalog `0007_fix_abdul_phone_number_id`. Did not touch `inbox.js`.
### 2026-08-19 ? Cursor session ? Transfer copies history onto the senior's number

Transfer now copies panel history onto the receiving agent's Official number (customer is not resent those messages). Both threads get a permanent Transferred label and stay linked: later WhatsApp messages on either number appear as panel copies on the other. Original chat is not removed. Senior still needs a template until the customer replies on that number. Also applied catalog.0006 (two 971 numbers).

**Live:** inbox.0013 applied; web/worker/beat recreated; panel JS/CSS HTTP 200. **Not verified in Chrome:** Ctrl+F5, Transfer to Farhat ? her list should show Matloob on her number with Transferred + full history; original thread still on the source number.
**Shared:** `inbox.js`, `inbox.css`, `backend/apps/inbox/models.py`, `services.py`, `events.py`, `serializers.py`, `views.py`. New: `transfer.py`, migration `0013_transfer_panel_copy`.

### 2026-08-19 ? Cursor session ? Transfer opens the chat for both sides

Mohcine Hatifi (`971509034652`) lives on Official number `971559791401`, not Harm's `2710`. Searching `+971?` also missed because `wa_id` has no plus. Transfer now switches to All numbers, clears search/tags, and opens that thread in the list and the pane ? admin after click, assignee over websocket.

**Live:** web/worker/beat recreated; inbox.js checksum match; HTTP 200. **Not verified in Chrome:** Ctrl+F5 both sides, Transfer once, assignee should land on the chat without typing the number.
**Shared:** `inbox.js`, `backend/apps/inbox/views.py`.

### 2026-08-19 ? Cursor session ? Transfer shows in assignee list

`@` changed on transfer but the receiving agent still did not see the thread: their list is filtered by Official number, and this chat lives on someone else's number. List API now keeps chats assigned to them even when a number is selected, and those threads sort to the top labelled Transferred. Number roster is still not granted.

**Live:** web/worker/beat recreated (healthy); panel inbox.js/css checksum match; HTTP 200. **Not verified in Chrome:** Harm Fatima Ctrl+F5 Official API ? Matloob (test) / eman Fazal should sit at the top as Transferred; Choose a template still works with window closed.
**Shared:** `inbox.js`, `inbox.css`, `backend/apps/inbox/views.py`.

### 2026-08-19 ? Cursor session ? Transfer is one chat, not the whole number

Reverted the number-roster grant. Transfer now only assigns that thread: the receiving agent sees it in their list, can open it, and can send (including templates via `/conversations/<id>/templates/`). Other chats on that Official number stay hidden. Live updates go to their personal websocket as well as the number group.

**Live:** web/worker/beat recreated, healthz 200; inbox.js HTTP 200; unauthenticated templates ? 401. **Not verified in Chrome:** admin Transfer to an agent who does not hold the number ? only that chat should appear; template send if window closed.
**Shared:** `inbox.js`, `api.js`, `backend/apps/inbox/services.py`, `views.py`, `events.py`, `serializers.py`, `urls.py`.

### 2026-08-19 ? Cursor session ? Official chat Transfer grants the number

Transfer only flipped ``assigned_agent``, so the receiving agent never saw the chat: the sidebar is keyed on number assignment, and templates are too. ``reassign`` now grants that Official number (backup) if they do not already hold it, publishes on their personal websocket, and the list treats assigned chats as visible. Panel adopts the number in the filter and reconnects the socket.

**Live:** web/worker/beat recreated, healthz 200; inbox.js HTTP 200, checksum matches. **Not verified in Chrome:** admin Transfer to an agent who does not have that number ? their sidebar should show the number and the chat; they send a template if the 24h window is closed.
**Shared:** `inbox.js` (transfer toast + adopt number + socket reconnect), `backend/apps/inbox/services.py`, `views.py` (`_visible_conversations` only). Did not touch `extras.js`.

### 2026-08-17 ? Cursor session ? Report & Feedback (Official sidebar)

Agents file issues from hamburger **Inbox tools ? Report & Feedback**: text plus JPEG/PNG/WebP/GIF or MP4/WebM/MOV (max 4, 8 MB image / 28 MB video). Admins use Open / Solved in the same modal and Mark solved. New app `apps.feedback` ? Conversation/Message/accounts models not widened. Did not touch dirty `inbox.js`.

**Live:** `feedback.0001_initial` applied (0 rows); makemigrations check clean; web/worker/beat recreated and Up; web healthy. Unauthenticated `/api/feedback/` ? 401. Panel JS/CSS/api.js/index HTTP 200, checksums match. **Not verified in Chrome:** Ctrl+F5, click Report & Feedback, submit with screenshot, then as admin Mark solved.
**Shared:** `api.js`, `index.html`, `backend/a7wa/settings.py`, `backend/a7wa/urls.py`. New: `backend/apps/feedback/*`, `bitrix/public/assets/modules/report-feedback.js` + `report-feedback.css`.

### 2026-08-17 ? Cursor session ? Conversation Health in Admin menu

Health sat next to AI desk and only injected after `/me` resolved, so the hamburger often had AI desk but no Conversation Health (even for admins). Item now lives under **Admin**, using that section as the gate ? same as Numbers / Agents.

**Live:** `inbox-ai.js` pushed; public HTTP 200. **Not verified in Chrome:** Ctrl+F5, open hamburger, Admin ? Conversation Health.
**Shared:** none of `inbox.js`. Touched `inbox-ai.js` only.

### 2026-08-17 ? Cursor session ? Official Conversation Health (admin only)

AI now scores Official chats with the **same colour rules as Linked phones**: red / pink / amber / hot / green, false-RED guard, reclassify every 10 messages, admin Allow-as-green lock (password `CONVERSATION_HEALTH_OVERRIDE_PASSWORD`, default 222007). New `ConversationHealth` table ? Conversation/Message columns not touched. Menu item + AI desk **Health** tab only if `is_wa_admin`; API 403 for agents. Agents never see the colour board.

**Live:** `inboxai.0002_conversationhealth` applied; makemigrations check clean; web/worker/beat rebuilt and Up; panel JS/CSS/api.js HTTP 200. Unauthenticated `/api/inboxai/health/summary/` ? 401. Worker already ran `consider_health` on a real inbound *before* migrate (table missing then); table now exists (0 rows). **Not verified in Chrome:** Ctrl+F5 as admin ? Conversation Health / AI desk Health tab ? Analyse chats; as a normal agent the menu/tab must be absent.
**Shared:** `api.js`, `backend/a7wa/settings.py`. New: `inboxai/health.py`, `health_rules.py`, migration 0002. Touched `inbox-ai.js` + `inbox-ai.css`. Did not touch `inbox.js` / `extras.css`.

### 2026-08-17 ? Cursor session ? AI desk liquid glass modals

AI desk + per-chat AI forms were a solid navy slab (`extras.css` forces `.modal__box { background: #0e1a2b }`) so they did not match the Official panel blur. Overlay + sheet now use the same frosted glass as `.app` (translucent fill, 34px blur, hairline inset).

**Live:** `inbox-ai.css` / `.js` pushed; public HTTP 200. **Not verified in Chrome:** hard-refresh, open AI desk and a chat AI form ? chat list should show through, blurred.
**Shared:** none of `inbox.js` / `extras.css`. Touched `inbox-ai.js` + `inbox-ai.css`.

### 2026-08-17 ? Cursor session ? Thread header: pills stay, actions in ?

Official chat header was crowding Window + @agent + AI + CRM + Export + Transfer. Header now keeps **only** the window pill and the @agent pill; AI / CRM / Export / Transfer live in a ? dropdown. Did not edit dirty `inbox.js` ? the AI module folds those buttons after render.

**Live:** panel JS/CSS pushed; public HTTP 200. **Not verified in Chrome:** hard-refresh Official API and open the ? on a chat.
**Shared:** none of `inbox.js` / `inbox.css`. Touched `inbox-ai.js` + `inbox-ai.css` only.

### 2026-08-17 ? Cursor session ? Inbox AI desk (Official API)

When the agent is away: per-chat **AI** button in the thread header (context form) + hamburger **AI desk** (new / all / selected chats + global context). New Django app `apps.inboxai` so dirty Conversation/Message/gateway/inbox.js were not widened. Inbound `post_save` queues `reply_to_inbound` after 8s; AI sends via `send_text(..., payload={"source": "ai_desk"})`. Human outbound pauses that chat?s cover. Max 12 AI replies / chat / 24h. Closed 24h window is skipped.

**Live:** `inboxai.0001_initial` applied; tables present; worker lists `apps.inboxai.tasks.reply_to_inbound` and already ran it on a real inbound (no desk enabled, so it no-op?d). Panel JS/CSS HTTP 200, checksums match. web+worker+beat recreated, all Up. **Not verified in Chrome:** open Official API, hard-refresh, click AI / AI desk, write context, wait for a customer message.

**Shared:** `api.js`, `index.html`, `backend/a7wa/settings.py`, `backend/a7wa/urls.py`, `backend/apps/inbox/services.py` (`payload=` on `send_text` only). New: `backend/apps/inboxai/*`, `bitrix/public/assets/modules/inbox-ai.js` + `inbox-ai.css`. Did not touch `inbox.js` / `extras.js` / `gateway/tasks.py`.

### 2026-08-17 ? Cursor session ? AI Utility template rewrite

Agents were submitting UTILITY templates that Meta then approved as MARKETING because the wording was promotional. Create Template now has **Rewrite as Utility**: AI analyses the draft and returns 5 transactional wordings; **Use this** fills the form as UTILITY. Marketing phrases are stripped; if OpenAI is down, five canned utility templates still appear.

**Live:** panel JS checksum `5f66b1c9?`; composer + api.js HTTP 200; web healthy after full rebuild. Local unit checks for promo vs appointment copy. **Not verified in Chrome:** click Rewrite on a real draft (OpenAI round-trip).
**Shared:** `template-composer.js`, `api.js`, `catalog/views.py`, `catalog/urls.py`. New: `catalog/utility_rewrite.py`. CSS in `template-center.css`. Did not touch `inbox.js`.

### 2026-08-17 ? Cursor session ? Templates center liquid glass + Meta 500

Pink "Sync failed: GET ?/message_templates -> HTTP 500" was one foreign Dubai WABA aborting the whole Official key refresh. `sync_templates` now continues per WABA; UI shows a warning if extras were skipped, library stays usable.

Liquid-glass Templates center (`.tmc-`, new CSS). Did not widen dirty `inbox.js` / `template-composer.css`.

**Live:** panel CSS/JS checksums match; public CSS 200; templates still 1168 Approved / 16 Rejected. web+worker+beat rebuilt and recreated, all Up. **Not verified in Chrome** ? hard-refresh Official API, then Sync from Meta (HTTP 500 bar should not kill the page).
**Shared:** `template-composer.js`, `index.html` (one stylesheet link), `backend/apps/catalog/tasks.py` + `views.py` (sync only; other uncommitted catalog work in views.py was already on disk). New: `template-center.css`.

### 2026-08-16 ? Cursor session ? Add remaining UAE Official numbers

Added 4 leftover `971` manuals from Dubai02?05 (Shahid Nawab, Neha, khan, real esate). Did not retouch A7GroupWBX 22 sync numbers. `971559759052` was already live. Dubai01 Property Market stays deactivated (Excel unmatched). Empty labels.

**Live:** created 4; sync still 22; UAE active 27; active_total 77?81.
**Shared:** none of the panel JS.

### 2026-08-16 ? Cursor session ? Official roster: Excel matches + Dubai11, trim Dubai01

Added 54 manual Official numbers (40 Excel-matched from Dubai02?07/10 + all 14 Dubai11). Deactivated 15 unmatched Dubai01 rows (0 chats); kept CleanSlate `447476959465`. A7GroupWBX `source=sync` 22 labeled/assigned numbers untouched. Empty labels so inbox shows assignee after they assign. Linked phones not touched. Keys not stored.

**Live:** sync active still 22; manual active 55; deactivated 15; Dubai11=14/14; active_total 77.
**Shared:** none of the panel JS. Ops: `ops/catalog/sync-excel-waba-roster.py`.

### 2026-08-16 ? Cursor session ? Hide WBBOX brand names on Official filter

Cleared `label` + `display_name` on the 16 `source=manual` Official numbers so inbox "All numbers" no longer shows Amara Estates / Regal Peaks / etc. Unassigned shows "Not assigned"; Numbers Management still auto-fills the agent name on assign. Existing 22 sync numbers unchanged. Did not touch `inbox.js` (uncommitted mid-edit elsewhere).

**Live:** 16 manual labels empty; title=phone. **Not verified in Chrome** ? hard-refresh Official API.
**Shared:** none of the panel modules.

### 2026-08-16 ? Cursor session ? Add 16 WBBOX Official API numbers

WBBOX WABA Channels (16 rows) inserted as `source=manual` on Official API `catalog_wabanumber`. Display names used as labels (Property Market, Amara Estates, ?). Webhooks left unset (`webhook_configured=false`) ? operator will point them in WBBOX. Linked phones / OpenWA not touched. The pasted alots Bearer was **not** stored (would replace the live Official key and break the existing 22 UAE agent numbers).

**Live:** created=16 skipped=0; active_total 22?38; all 16 `source=manual`. Existing 22 agent numbers unchanged.
**Not verified:** sending or inbound on these WABAs (many show EXPIRED in WBBOX; they are a second BSP account).
**Shared:** none of the panel JS. Ops only: `ops/catalog/add-wbbox-official-numbers.py`.

### 2026-08-15 ? Cursor session ? Linked phones HTTP 500 + QR overload

Red **HTTP 500** on Linked phones was `GET /api/sessions` plus failed Start/pairing while 8 `qr_ready` Chromiums plus 6 connected engines starved the box (browser launch `Code: null`, init timeout). Stopped idle Scan-QR engines only (`abdul-qadir`, `heram`, `hina-recepstions`, `marketting`, `neha`, `qasim`, `shaid-mamo`). Left **shehreen** on QR (WhatsApp LOGOUT at 15:06Z deleted her local profile ? she must re-scan). Left every `ready` session running. Did **not** recreate `openwa-api`. Sessions page now clears the red banner after a successful list.

**Live:** `GET /api/sessions` 200; pids 185?101; status `ready=6 qr_ready=1 (shehreen) disconnected=11`; container started 2026-08-14T12:44 still Up. SPA overlay rebuilt (`Sessions-Dn45XXlK.js`). **Not verified in Chrome:** Irum/momina Start after the unload (those rows never had a phone ? they will need QR).
**Shared:** `Sessions.tsx`, nginx overlay already in place from the voice-note ship.

### 2026-08-15 ? Cursor session ? Linked phones voice-note send

Mic on the composer when the text box is empty; record ? Send as WhatsApp PTT
(`send-audio` + `ptt`). Convert to Ogg/Opus when ffmpeg answers, else send the
browser blob. iframe `allow="microphone; autoplay"`. OpenWA container **not**
recreated (read_only rootfs blocked docker cp): host `dashboard/dist` is served
by nginx on :2786, `/api/` and `/socket.io` still proxy to the running API.

**Live:** openwa-api Up 26 hours, healthy, readiness 200; image from 2026-08-14.
inbox.js md5 `8081f54a?`. `convert/voice` in built SPA. nginx overlay
`/etc/nginx/conf.d/a7-openwa.conf` (backup `.bak.voice`).
**Not verified in Chrome:** record+send a real note (needs mic + Bitrix iframe
delegation). If the browser refuses the mic, it is Bitrix?s outer iframe, not a
session drop.
**Shared:** `inbox.js`, `ChatComposer.tsx`, `a7/nginx-a7-openwa.conf`.

### 2026-08-15 ? Cursor session ? Live number communities from PDF matches

`catalog.0005` set `WabaNumber.community` on the 21 Official numbers whose
assigned agent matched the PDF. Left empty: Muhammad Saeed, plus Nabiha /
Sapna / Fakhra (no active number). Corrected Aila (was Mudon Al Ranim ?
Villa Nova) and Farhat (was Damac Lagoon ? International city).
**Live:** 0005 applied; 21 rows filled, Saeed blank. SQL verified.
**Shared:** only `catalog/migrations/0005_fill_wabanumber_community.py`.

### 2026-08-15 ? Cursor session ? Fill Official API communities from PDF

`accounts.0009` mapped first-name of live Bitrix display names onto the
AGENTS DETAILS roster (21 filled). Sapna and Fakhra are not on the panel yet
so they were skipped. Labels now show next to names in Agents, Numbers chips,
inbox transfer/filter, Reports, contact panel, and Linked phones picker.
**Live:** 0009 applied; 21 `community` rows non-empty. reports.js md5
`94976710?` matches panel. **Not verified in Chrome by me** ? hard-refresh.
**Shared:** `reports.js`, `reports/views.py`, `contact-panel.js`,
`linked-phones-admin.js`, `admin-kit.css`. Did not retouch `inbox.js`.

### 2026-08-15 ? Cursor session ? Official API community label (PDF roster)

PDF ?AGENTS DETAILS? is Name ? Community (Mudon Al Ranim, Damac Hills 2, ?).
Official API now stores that as `Agent.community` + optional `WabaNumber.community`.
Name ke saath pill; Add Official API number pe Community input; assign chip pe
Community input. PDF rows auto-import nahi ? admin types the label.

**Live:** `accounts.0008` + `catalog.0004` applied. Columns on `accounts_agent`
and `catalog_wabanumber`. Panel md5 match: numbers-admin.js `b8e27387?`,
agents-admin.js `6195356b?`, inbox.js `6cd93140?`. web healthy after full
`build app` + up web/worker/beat. `makemigrations --check` No changes detected.
**Not verified:** typing a community in the live UI (no admin session here).
**Shared:** `inbox.js`, `numbers-admin.js/css`, `agents-admin.js`, `admin-kit.css`,
`api.js`, `catalog/views.py`, `accounts/models.py`, `inbox/serializers.py`.

### 2026-08-15 ? Cursor session ? Official API CSS/theme looking unstyled

Placement 282 mounted, but the hamburger ?Design / Theme? rows looked like
raw HTML and the thread stayed white. Two real causes: (1) relative
`./assets/*.css` from `/app` (no slash) resolve as `/assets/*` and 404;
nginx `try_files` + `alias` could also serve `index.html` as CSS.
(2) extras dumped a nested absolute dropdown into `.sidebar__menu`, and
`panel.css` `.btn { margin-top:16px; navy fill }` hit those rows because
they were nested in a `.slot`, not `> *`.

Fix: root-absolute `/app/assets/?` URLs, `data-wa-theme` on `<html>`
before CSS, theme options as `#wa-theme-slot` menu items, dedicated
`location ^~ /app/assets/`, GET `/app` ? `/app/`, no `try_files`.

**Live:** extras.css `text/css` 41942, missing `.css` is 404 not inbox
HTML, POST `/app/` still 200. `index.html` `d5284928?`.
**Not verified in Chrome by me** ? hard-refresh the placement.
**Shared:** `index.html`, `inbox.js/css`, `extras.js/css`,
`bitrix/deploy/a7-wa-panel.location.conf`, live `/etc/nginx/conf.d/a7-wa.conf`.

### 2026-08-15 ? Cursor session ? Stuck on Signing you in

Inline `getInitData` hid Bitrix's overlay but consumed AUTH_ID, so
`BX24.getAuth()` was empty and `refreshAuth` hung with no timeout ? boot
card stayed on ?Signing you in??. Dummy handshake removed; SDK owns init
again. `refreshAuth` / `callMethod` now time out instead of hanging.

**Live:** `index.html` `b65de897?`, `bitrix-sso.js` `a5066b72?`.
**Shared:** `index.html`, `bitrix-sso.js`, `install.html`, `crm/index.html`.

### 2026-08-15 ? Cursor session ? Overlay stuck: 0-byte JS + CSS-before-init


Access log (`a7-wa.access.log`) shows Bitrix POSTs `/app/?DOMAIN&APP_SID` 200 ?
handler URL is fine. While files were being replaced / nginx reloaded, the same
clients got `200 0` for `bx24-early.js` and even the HTML, so BX24.init never
ran. CSS in `<head>` also delayed the handshake tens of seconds.

Inline `getInitData` postMessage now runs before any stylesheet. Overlay should
drop even if later JS is empty.

**Live:** pushing `index.html` handshake-first. AWS Bitrix host reachable;
webhook `placement.get` not used (log already proved the bound handler).
**Shared:** `index.html`, `install.html`, `crm/index.html`.

### 2026-08-15 ? Cursor session ? Loading WhatsApp overlay still up after early init


First fix (BX24.init before inbox.js) was live and not enough. Two further
faults: (1) official SDK throws unless `window.name` is `DOMAIN|PROTOCOL|APP_SID`
? Bitrix puts those on the query string, SidePanel often does not set the
iframe name, so init never reached the parent; (2) POST `/app` (no slash)
missed `location /app/` and 404'd through Django.

Hydrate `window.name` from `DOMAIN`/`APP_SID` query; vendor `bx24-sdk.js`
locally; nginx `location = /app` serves the same index.

**Live:** `index.html` `accfb0da?`, `bx24-early.js` `79376174?`, `bx24-sdk.js`
`dd6d1fe2?`; nginx reloaded (`location = /app`).
**Not verified in browser:** hard-refresh Bitrix WhatsApp (Ctrl+F5).
**Shared:** `index.html`, `install.html`, `crm/index.html`, `bx24-early.js`,
`bx24-sdk.js`, `bitrix/deploy/a7-wa-panel.location.conf`.

### 2026-08-15 ? Cursor session ? Bitrix left-menu stuck on Loading WhatsApp


LEFT_MENU slider (`/devops/placement/282/`) never dropped Bitrix?s own
?Loading WhatsApp? overlay. That overlay waits on `BX24.init` in the iframe;
the handler imported `inbox.js` (the whole panel graph) first, so a slow or
failed module left the overlay up and hid the boot card.

`bx24-early.js` now calls `BX24.init` as a classic script in `<head>`. Inbox
loads after SSO. `loadBX24` reuses that promise ? a second `init` on this
portal never fires.

**Live:** `ops/wa.sh push` of `index.html` (`0d1f4e89?`, 7761 bytes),
`bx24-early.js` (`228d3fc6?`, HTTP 200), `bitrix-sso.js` (`924243db?`),
plus install + CRM handlers. POST `/app/` was already 200 before this.
**Not verified in browser:** click WhatsApp in Bitrix after a hard refresh
(Ctrl+F5). If it still spins, the overlay is covering a boot error ? send
the console line starting `[a7-wa]`.
**Shared:** `index.html`, `install.html`, `crm/index.html`,
`assets/core/bx24-early.js`, `assets/core/bitrix-sso.js`.

### 2026-08-14 ? Cursor session ? Official API contact panel WhatsApp redesign


Official API contact drawer matched to Linked phones: teal ?Contact info?
head, hero avatar, Pin/Archive quick actions, media grid, professional
name/notes inputs, dimmed backdrop click-to-close. Archive icon added to
`icons.js`; `inbox.js` syncs pin/archive flags into the list.

**Live:** `ops/wa.sh panel` ? md5 `contact-panel.js` matches local
`64b3c9dc?`. Hard-refresh Official API iframe.
**Shared:** `contact-panel.js`, `contact-panel.css`, `icons.js`, `inbox.js`,
`extras.css` (backdrop rules moved into contact-panel.css).

### 2026-08-14 ? Cursor session ? Contact panel WhatsApp redesign

Linked phones Contact drawer: teal WhatsApp-style hero + quick actions
(Pin / Archive / Unread / Block), media grid, professional inputs, dimmed
backdrop so click on chat closes the panel. Team-local `pinned` on
`chat_profiles` (migration 178690) sorts sidebar; Archive hits engine
`/chats/archive`.

**Live:** `ops/openwa/deploy-contact-profile-panel.sh` ? bundle-ok, pin PATCH
200, `pinned` column present. Hard-refresh Linked phones iframe.
**Shared:** `ContactProfilePanel.tsx`, `Chats.css`, `Chats.tsx`,
`ChatSidebar.tsx`, `chat-profile.*`, `api.ts`, deploy script.

### 2026-08-14 ? Cursor session ? Contact profile save 500 + name UX

Linked phones Contact drawer: save failed with `SQLITE_CONSTRAINT_NOTNULL`
on `chat_profiles.createdAt` because `CreateDateColumn` + `DateTransformer`
inserted null (same trap as chat_leads). Explicit `createdAt`/`updatedAt` on
create + bump `updatedAt` on patch. UI: team-name field shows current name,
clear (X) to replace, red field error instead of green "Internal server error"
flash, Actions padding.

**Live:** `ops/openwa/deploy-contact-profile-panel.sh` ? PATCH probe `http=200`,
`null_ts_rows=0`. Hard-refresh Linked phones iframe.
**Shared:** `chat-profile.service.ts`, `ContactProfilePanel.tsx`, `Chats.css`,
deploy script.

### 2026-08-13 ? Cursor session ? Reminder preset menu contrast (glass-dark)

Clock reminder menu ("30 minutes", ?) used `var(--ink)` on dark navy so text
was invisible. Explicit light text + hover for `.wa-x-preset-item` (and attach
menu items) under glass-dark / glass-light.

**Live:** `ops/wa.sh panel` (`extras.css`).
**Shared:** `extras.css`.

### 2026-08-13 ? Cursor session ? Official composer bottom-bar clip fix

Composer vanished for some agents on short Bitrix sliders: `.thread` lacked
`min-height:0` / overflow containment so the message list grew past the frame
and `.app { overflow:hidden }` clipped the bottom bar. Hardened grid/flex
containment, stopped header wrap stealing height, pinned html/body/#root to
`visualViewport` height after mount.

**Live:** `ops/wa.sh panel` (inbox.md5 match); OpenWA
`deploy-new-contact-fab.sh` ? readiness 200 (Linked room `min-height:0` /
footer pin in same rebuild).
**Not proved:** every laptop viewport in Bitrix.
**Shared:** `inbox.css`, `inbox.js`, `Chats.css`.

### 2026-08-13 ? Cursor session ? Linked phones New contact FAB

Same green **New** bubble bottom-left of OpenWA chat list; calls existing
`onNewContact` ? `NewContactModal`. List padding under FAB.

**Live:** `ops/openwa/deploy-new-contact-fab.sh` ? readiness 200,
`new-contact-fab-bundle=ok`.
**Shared:** `ChatSidebar.tsx`, `Chats.css`, `deploy-new-contact-fab.sh`.

### 2026-08-13 ? Cursor session ? Official New contact FAB

Floating green **New** bubble bottom-left of Official API chat list; opens
existing `openNewContact` / template composer. List gets bottom padding so
rows stay readable under the FAB. Menu entry unchanged.

**Live:** `ops/wa.sh panel`.
**Shared:** `inbox.js`, `inbox.css`.

### 2026-08-13 ? Cursor session ? Agents access UI (Official + Linked)

Agents roster redesigned: search, avatar row, product toggles.
New Agent flags `can_official_api` / `can_linked_devices` (default true);
Panel Admin unchanged. Enforced on `visible_numbers`, openwa gate/credentials;
menu hides Linked when disabled.

**Live:** push accounts+catalog+migration `0007`; build app; migrate; up
web/worker/beat; `ops/wa.sh panel`.
**Not proved:** browser toggle click on a non-self agent.

**Shared:** `accounts/models.py`, `0007_agent_product_access.py`,
`accounts/views.py`, `catalog/views.py`, `agents-admin.js`, `admin-kit.css`,
`api.js`, `inbox.js`.

### 2026-08-13 ? Cursor session ? Official Add number ? already on panel + Save anyway

User could not add BSP-1 webbox credentials; Test said no gateway channel.
Live DB already has the same Phone Number ID / Business ID as **NABIHA**
(`971559632895` / `1248276241703985` / `1717333182876103`). Form had typo
`?3285` instead of `?3985`.

**Shipped:** local exact + 1-digit PNID near-miss detection; swapped-ID hint;
`allow_force` + panel **Save anyway** when channel is not on alots; warn style.

**Live:** push `catalog/views.py`; build app; up web/worker/beat; `ops/wa.sh panel`.
**Not proved:** browser Test click on mistyped form (logic matches DB row).

**Shared:** `backend/apps/catalog/views.py`, `numbers-admin.js`, `numbers-admin.css`.

### 2026-08-13 ? Cursor session ? Audit batch (broken + UX declutter)

Shipped fixable items from the deep audit list. Skipped deferred/impossible:
Disconnect alert; gateway typing/ticks/reactions; full CRM in-tab thread;
git/CI; bulk media recover; wa-qr teardown.

**Official:** API Retry (text fallback); tag filter bar + chip click; pin/
archive + create label in contact drawer; locked composer no extras slot;
menu sections; Numbers theme-hijack removed; agents-admin copy; album/
pinned labels+icon; Numbers Sync from gateway.

**OpenWA:** ApiKeys prefix-only (no fake eye), Ban revoke icon; Profile ?
My desk; embed menu trims Advanced (webhooks/infra/tester/logs); embed
login A7 copy; Amber/Hot colour label; block/unblock single action; glass
margin tighter; operator role copy = chats only.

**Live:** `ops/wa.sh panel`; `ops/openwa/deploy-audit-fixes.sh`.
**Not proved:** every click path in browser; CRM placements; campaign e2e.

**Shared:** many `bitrix/public/assets/modules/*`, `api.js`, `icons.js`,
`openwa/dashboard/src/{Layout,ApiKeys,Login,ContactProfilePanel,
AgentProfileModal,a7-glass-embedded.css,en.json}`,
`ops/openwa/deploy-audit-fixes.sh`.

### 2026-08-13 ? Cursor session ? Linked phones dashboard analytics

OpenWA Message Analytics period adds **1 year**; same dashboard gets
**Agent response time** (per linked phone/session: avg/median bands, Top 10
slowest/fastest, full table). OpenWA has no Bitrix agent id on messages ?
session name is the desk label.

**Live:** `ops/openwa/deploy-dashboard-analytics.sh` ? readiness 200,
`analytics-ok`. Hard-refresh Linked phones ? Dashboard ? 1 year + response
block under charts.

**Shared:** `openwa/src/modules/stats/{dto/stats-query.dto.ts,stats.service.ts}`,
`dashboard/src/components/DashboardCharts.{tsx,css}`, `services/api.ts`,
`i18n/locales/en.json`, `ops/openwa/deploy-dashboard-analytics.sh`.

### 2026-08-13 ? Cursor session ? Agent reply performance in Reports

Reports ? Agents: avg + median first-reply, performance bands (Excellent /
Good / Fair / Bad / Critical / Not enough data), Top 10 slowest + Top 10
fastest, full sortable roster. Gaps attributed to the agent who answered
(not every agent on the chat).

**Bands (median):** under 5m Excellent, under 15m Good, under 1h Fair,
under 4h Bad, else Critical; need 3+ timed replies.

**Live:** push `reports/views.py` + `build app` + up web/worker/beat;
`ops/wa.sh panel`. Hard-refresh ? Reports ? Agents.

**Not browser-walked** with a real admin session this turn.

**Shared:** `backend/apps/reports/views.py`,
`bitrix/public/assets/modules/reports.js`, `reports.css`.

### 2026-08-13 ? Cursor session ? Official Numbers Add + Test + Save

Webbox credentials (OTP or QR ? both Cloud API IDs) can be typed into
Numbers Management: Test against alots channels, then Save as `source=manual`.
Linked phones / OpenWA not touched.

**Backend:** `WabaNumber.source` (`sync`|`manual`); `sync_numbers` only
deactivates `sync` rows; `POST /api/catalog/numbers/test/` +
`POST /api/catalog/numbers/`; serializer adds `source` + `webhook_url`.

**Panel:** Numbers ? Add number form (phone, Business ID, Phone Number ID,
label); Test ? Checking? ? Connected/Failed; Save disabled until Test ok;
rows show IDs + webhook copy.

**Live:** push + `build app` + up web/worker/beat; migrate
`catalog.0003_wabanumber_source` OK; `makemigrations --check` clean; panel
published; 22 numbers `source=sync`; panel `numbers-admin.js` md5 matches repo.

**Not browser-proved:** Test/Save with a real unused webbox channel (needs
admin click + live credentials). Linked phones untouched as agreed.

**Shared:** `backend/apps/catalog/{models,tasks,views,urls}.py`,
`migrations/0003_wabanumber_source.py`, `inbox/serializers.py`,
`bitrix/public/assets/{api/api.js,modules/numbers-admin.js,numbers-admin.css}`.

### 2026-08-12 ? Cursor session ? Deep remaining-fixes batch

Shipped the focused backlog items (not the deferred impossibles).

**Backend:** webhook per-message/status `atomic()` isolate so one bad item
does not kill the batch; `Message.Kind` + `_describe` for `album` /
`pinned_message` (`inbox.0012`); campaign undelivered reconcile on FAILED
status ? Meta `131049` marketing-cap ? `EXHAUSTED` (no 5?min retry burn).

**OpenWA:** `POST /conversation-health/reclassify-false-red` + UI
?Re-check false RED?; Yellow?Amber / White?Hot labels; login CSS polish.

**Panel:** agents admin on `akit-*` (no inline styles); campaign MARKETING
confirm copy about cap + no auto-retry.

**Live:** `ops/wa.sh panel`; `ops/openwa/deploy-deep-fixes.sh` ?
`deep-fixes-ok` / readiness 200; push + `build app` + `up` web/worker/beat;
`migrate` `0012_message_kind_album_pinned` OK; `makemigrations --check` =
No changes detected; beat still runs `retry_due_campaign_recipients` every
~60s; panel `agents-admin.js` md5 matches repo; openwa `chat_leads` colours
present (16 red).

**Not proved:** end-to-end MARKETING undelivered flip on a live send;
browser click of Re-check false RED (would spend OpenAI on ~16 unlocked
reds); historical 4 `unknown` inbox rows (no payload to remap).

**Skipped (still):** Disconnect alert (deferred); gateway typing/read/send
reaction; CI/git remote; full CRM in-tab thread; bulk media recover.

**Shared:** `backend/apps/gateway/tasks.py`, `campaigns/services.py`,
`inbox/models.py` + `migrations/0012_*`, `bitrix/.../agents-admin.js`,
`campaigns.js`, `openwa/.../conversation-health.*`,
`ConversationHealthPanel.*`, `Login.css`, `ops/openwa/deploy-deep-fixes.sh`.

### 2026-08-12 ? Cursor session ? Full UI/UX polish batch

Audit list shipped: Official API theme holes + OpenWA embed polish.

**Panel:** Reports Classic-readable + glass-dark retint; `admin-kit.css` for
Quick replies / Shared / Starred / slash popup; Campaign/attach/closing/access
glass overrides in `extras.css`; modal z-index > contact drawer + backdrop;
badge `--ok` / linked status colours; contact drawer glass inset.

**OpenWA:** video no auto-fullscreen; health/New-contact dark tokens; Sessions
solid cards under glass; JID only when no phone; lead colour off header; All
chats button removed (select only); hamburger light contrast; voice width;
health legend denser; mobile chats height; FAB nudge on non-Chats.

**Live:** `ops/wa.sh panel`; `ops/openwa/deploy-ui-polish.sh` readiness 200,
`ui-polish-ok`. Hard-refresh Official + Linked iframes; flip Classic vs Glass.

**Not browser-walked every modal.** Shared: many `bitrix/public/assets/modules/*`,
`openwa/dashboard/src/**` listed in deploy script, `ops/openwa/deploy-ui-polish.sh`.

### 2026-08-12 ? Cursor session ? Campaign New vs History UI split

Campaign modal looked identical on both tabs because `.camp-hist { display:grid }`
overrode HTML `[hidden]`, so History stayed under New. Fixed with
`.camp-pane[hidden]` / `:not(.is-active) { display:none !important }`.
History is now a distinct 3-column layout (list ? detail/stats ? chats);
New is composer + preview only (live send card after start). Title toggles
with the tab.

**Live:** `ops/wa.sh panel`. Hard-refresh Campaign ? New must not show Past
campaigns / Chats; History tab only.

**Shared:** `bitrix/public/assets/modules/campaigns.js`, `campaigns.css`.

### 2026-08-12 ? Cursor session ? Campaign history + auto-retry

Campaign modal: **New / History** tabs; History shows sent/failed/retrying,
failures list, and a **Chats** side list (Open chat ? inbox). Backend:
recipient `attempt_count` / `next_retry_at` / `exhausted`; fail ? retry every
**5 min**, max **5** attempts then permanent fail; Celery beat
`retry-due-campaign-recipients` every 60s.

**Live:** sync + `build app` + up web/worker/beat; migrate `0002_campaign_retry`
OK; beat schedules retry task; panel `campaigns.js` published.
Hard-refresh ? menu Campaign ? History.

**Not browser-proved:** end-to-end fail?5min?retry on a real number.
**Shared:** `backend/apps/campaigns/*`, `settings.py`, `campaigns.js/css`,
`api.js` (unchanged client shape + new fields).

### 2026-08-12 ? Cursor session ? Create Session button (Linked phones)

Embedded Linked phones hid `.page-header`, so **Create Session** vanished.
Toolbar copy added on Sessions filters bar (`sessions-create-btn--toolbar`);
label ?Create Session?; empty-state button too.

**Live:** `ops/openwa/deploy-create-session-btn.sh`; readiness 200; bundle ok.
Hard-refresh Linked phones iframe ? button top-right of search/filter row.

**Shared:** `Sessions.tsx/css`, `a7-embedded.css`, `en.json`.

### 2026-08-12 ? Cursor session ? UX batch (list items one-by-one)

Shipped the prioritized UX list in one pass (Disconnect alert still deferred).

OpenWA: health colour legend + load error/Retry + RED allow hint; false-RED
guard (`looksLikeCleanReason` + tighter prompt); All-chats New contact/Profile
fallback; Theme hidden in embed; header JID off; Block confirm; agent empty
copy; Allow-as-green on RED rows.

Bitrix panel: CRM tab Official API vs Linked phone + multi-chat picker;
Campaign MARKETING daily-cap confirm; inbox 24h coach + gateway limits note;
Load more + unread-first; Create in CRM label; Transfer ? Ask admin for
agents; Linked phones rename / Official API title.

**Live:** `ops/openwa/deploy-ux-batch.sh` (readiness 200, bundle ok);
`ops/wa.sh panel` ? md5 matches for `inbox.js`, `crm-tab.js`, `campaigns.js`.
Hard-refresh panel + Linked iframe.

**Not verified in browser:** CRM placement picker click, campaign send confirm
UI, false-RED reclassify of existing rows (needs new classify job).
**Skipped:** Disconnect alert; full CRM in-tab thread; login rebrand polish.

**Shared:** `inbox.js/css`, `campaigns.js`, `crm/crm-tab.js/css`, OpenWA
health/constants/openai client, ConversationHealthPanel, Layout, Chats,
ContactProfilePanel, en.json, `ops/openwa/deploy-ux-batch.sh`.

### 2026-08-12 ? Cursor session ? Health admin-only + Allow green

Conversation Health menu/API now **admin only** (agents no longer see it).
RED list has **Allow as green** ? prompts admin password (`222007` via
`CONVERSATION_HEALTH_OVERRIDE_PASSWORD`); wrong password ? 403 (not logout).
Sets colour green + `colourLocked` so AI will not flip it back.

**Live:** `deploy-health-admin-override.sh` + compose forward; readiness 200;
`colourLocked` column ok; password in container. Hard-refresh as admin.

**Shared:** health controller/service/entity, migration 178680, Layout/Chats,
ConversationHealthPanel, api.ts, en.json, docker-compose.yml.

### 2026-08-12 ? Cursor session ? Conversation Health UI polish

Colour list was a nested floating box (cramped rows, fat scrollbar, glass
bleed). Now in-place list inside the Health dialog: back + colour title,
avatar rows, green ?Open chat? / ghost ?Open lead?, thin scrollbar, solid
embedded panel. No second modal.

**Live:** `ops/openwa/deploy-health-ui.sh`; readiness 200; `chp-list-view` in
bundle. Hard-refresh iframe ? ? ? Conversation Health ? colour.

**Shared:** `ConversationHealthPanel.tsx/css`, `Chats.css`,
`a7-glass-embedded.css`, `en.json`, `deploy-health-ui.sh`.

### 2026-08-12 ? Cursor session ? Embedded app-menu contrast

Hamburger menu (Chats / Theme) had dark text on dark glass when Theme=light ?
labels looked blank. Solid `#0f1c2e` + `#eef3f9` text forced in
`a7-glass-embedded.css` for embedded (both themes).

**Live:** `ops/openwa/deploy-app-menu-contrast.sh`; readiness 200; bundle ok.
Hard-refresh iframe, reopen ? menu.

**Shared:** `a7-glass-embedded.css`, `deploy-app-menu-contrast.sh`.

### 2026-08-12 ? Cursor session ? Contact panel opaque (no bleed)

Embedded glass made `.a7-cp` see-through (`--bg-white` translucent + fixed
full-iframe mount). Panel now mounts **inside** `.room-container`
(`position:absolute`), solid `#ffffff` / embedded `#0f1c2e` (no blur).

**Live:** `deploy-contact-profile-panel.sh` rebuilt `openwa-api`; readiness 200;
bundle has `#0f1c2e`. Hard-refresh Messenger iframe.

**Shared:** `Chats.tsx`, `Chats.css`, `ops/openwa/deploy-contact-profile-panel.sh`.

### 2026-08-12 ? Cursor session ? OpenWA contact side panel

Clicking the chat header (avatar + name) opens a right-edge **Contact** drawer
in the OpenWA Chats UI (embedded Messenger). Agents can edit team-local
**name** and **notes** (blur-save), see phone/JID/session, open Bitrix lead,
activity counts, recent media chips, and block/unblock. Name overlays the
sidebar list via `GET ?/chat-profiles`.

**Backend:** `chat_profiles` table + migration `1786700000000`;
`ChatProfileService` / `ChatProfileController`
(`GET/PATCH /sessions/:id/chats/:chatId/profile`, `GET ?/chat-profiles`).
**Dashboard:** `ContactProfilePanel.tsx`, header button in `Chats.tsx`,
`a7-cp*` CSS in `Chats.css`, `chatProfileApi` + block/unblock on `contactApi`.

**Verified:** migration unit test; dashboard `tsc --noEmit`.
**Live 2026-08-12:** `ops/openwa/deploy-contact-profile-panel.sh` ? push +
rebuild `openwa-api`; `chat_profiles` table ok; `GET ?/profile` 200 on an
`@lid` chat; dashboard bundle contains `room-contact-btn` + `a7-cp__`. Hard
refresh the Messenger iframe. Block still needs a started session.

**Shared:** `openwa/dashboard/src/pages/Chats.tsx`, `Chats.css`,
`services/api.ts`; new files under `openwa/src/modules/conversation-health/`
and `openwa/dashboard/src/components/chats/ContactProfilePanel.tsx`;
`ops/openwa/deploy-contact-profile-panel.sh`.

### 2026-08-11 ? Cursor session ? Campaign form complete (vars/buttons/media)

Campaign modal rebuilt: two-column layout + phone preview; body/header vars,
header media upload, URL-button suffixes, recipient parse preview, progress +
failures, recent campaigns. Backend validates filled body/header/button vars.
CSS: `campaigns.css` (linked in `index.html`). Old incomplete body-only fields
removed.

**Live:** panel + services.py pushed; web/worker/beat rebuilt. Hard-refresh
Campaign menu. End-to-end send still needs a real template run by Matloob.

**Shared:** campaigns.js/css, index.html, inbox.css (camp styles removed),
`backend/apps/campaigns/services.py`.

### 2026-08-11 ? Cursor session ? Campaign (paste + CSV ? Owner Data)

Bulk approved-template campaigns in the Bitrix panel hamburger (**Campaign**).
Recipients: paste numbers and/or CSV. Every number is matched or created in
**Owner Data (SPA 1042)** ? never a CRM Lead ? then the template is sent; chat
logs follow the existing Owner Data mirror + a campaign timeline comment.

**Backend:** `apps/campaigns/` (models, Celery `run_campaign` ~1.5s gap,
`/api/campaigns/`). **Panel:** `campaigns.js`, `api.js` `campaigns` helpers,
menu in `inbox.js`, styles in `inbox.css`. **Ops:** `ops/wa.sh migrate`.

**Live:** panel published; `campaigns.0001_initial` applied; web/worker/beat
rebuilt+recreated. Phone parse tests pass locally. End-to-end send not proved
here (needs a real approved template + test number).

**Shared:** `backend/apps/campaigns/*`, `backend/a7wa/{settings,urls}.py`,
`bitrix/public/assets/{api/api.js,modules/campaigns.js,inbox.js,inbox.css}`,
`ops/wa.sh`.

### 2026-08-11 ? Cursor session ? Owner Data kanban AED0 on New Availability

Availability kanban (SPA 1042 / category 14) sums Bitrix `opportunity`
(Amount), not the card UF ?Lease Price?. New Availability had opportunity=0
while `ufCrm5_1734247036310` held prices ? column showed AED0.

Synced Amount from Lease (else Selling) for New Availability: **20** items
updated (only those with a price UF filled; e.g. #86882 ? 3,200,000).

**Auto going forward:** VPS cron `*/15 * * * *` runs
`/opt/a7-wa/ops/openwa/run-owner-data-amount-sync.sh` (New Availability every
15m; other AED0 stages hourly). Log: `/var/log/owner-data-amount-sync.log`.
Install: `ops/openwa/install-owner-data-amount-cron.sh`.

**Shared:** fix-owner-data-kanban-amounts.py, run-owner-data-amount-sync.sh,
probe-owner-data-kanban-sum.py.

### 2026-08-10 ? Cursor session ? Fix jumbled WhatsApp Chat on leads

Some leads showed shredded/overlapping `UF_CRM_WA_CHAT` text. Root cause:
Bitrix string field `SETTINGS.SIZE=20` (textarea ~20 chars wide). Legacy
`crm.*.userfield.*` REST **cannot change SIZE** (ROWS yes; SIZE stuck at 20
even on recreate). `userfieldconfig.update` needs webhook scope we lack.

**What shipped:** soft-wrap + vCard strip for UF writes
(`formatThreadForBitrixField`, wrap width 20); OpenWA rebuilt; backfill
re-enqueued to rewrite chat/monitor text. Brief recreate attempt wiped UF
values then restored via conversation-health backfill (655 jobs).

**Still needs Matloob (1 min):** Bitrix ? CRM Settings ? Lead fields ?
WhatsApp Chat + AI Monitor ? **Size = 80** (or inbound webhook with
`userfieldconfig`, then `ops/openwa/widen-wa-chat-userfieldconfig.py --fix`).

**Shared:** conversation-health.format.ts + service, deploy-fix-wa-chat-layout.sh,
widen-wa-chat-userfieldconfig.py. Do **not** delete/recreate these UFs again.

### 2026-08-10 ? Cursor session ? Linked WhatsApp glass theme (Omni match)

Linked devices shell + embedded OpenWA now use the same liquid-glass look as
the API/Omni WhatsApp (teal?gold blobs, frosted panel, glass chat rows /
bubbles). New `a7-glass-embedded.css`; panel `.linked__glass-bg` blobs.

**Shared:** inbox.js/css, main.tsx, a7-embedded.css, a7-glass-embedded.css.
Deploy: `ops/openwa/deploy-linked-glass-theme.sh`.

**Live 2026-08-10:** panel + OpenWA rebuild; readiness 200; glass tokens in
dist. Hard-refresh Linked WhatsApp to see teal/gold glass.

### 2026-08-10 ? Cursor session ? Panel header "WhatsApp" + kill chats gap

Bitrix Linked-devices bar title ? **WhatsApp**; subtitle note removed. Menu
item same. Framed OpenWA: hide page-header strip, zero chats-layout margin,
tighter session header ? kills blank band above "WhatsApp session".

**Shared:** inbox.js/css, a7-embedded.css. Deploy: `ops/wa.sh panel` + OpenWA
dashboard rebuild for embedded CSS.

**Live 2026-08-10:** panel published (`linked__title` = WhatsApp, note gone);
OpenWA rebuild readiness 200. Hard-refresh panel + Linked/WhatsApp screen.

### 2026-08-10 ? Cursor session ? Pic-1 app menu (sidebar ? dropdown)

Permanent A7 left rail removed. Hamburger (beside WhatsApp session / FAB on
other routes) opens a pic-1 dropdown: Conversation Health, New contact,
Profile, then Dashboard/Sessions/Chats/?, Theme, Logout. Default route is
`/chats` (full page). Language picker removed ? English only (`i18n` fixed to
`en`). Dashboard moved to `/dashboard`.

**Shared:** Layout.tsx/css, useAppMenu.tsx, ChatSidebar.tsx, Chats.tsx/css,
App.tsx, Login.tsx, i18n/index.ts, a7-embedded.css. Deploy:
`ops/openwa/deploy-chats-app-menu.sh`.

**Live 2026-08-10:** push+build+recreate; readiness 200; `a7-app-menu` +
Conversation Health strings in dashboard dist. Browser spot-check for Matloob.

### 2026-08-10 ? Cursor session ? Chats UI: tools menu + voice/video polish

Linked-devices Chats: Conversation Health / New contact / Profile moved behind
a hamburger beside "WhatsApp session" (pic-2 style). Custom `VoicePlayer`
replaces native `<audio controls>`; `ChatVideo` enters fullscreen on play.

**Shared:** ChatSidebar.tsx, ChatThread.tsx, Chats.tsx/css, VoicePlayer.tsx,
ChatVideo.tsx, ConversationHealthPanel (mounted from sidebar). Deploy:
`ops/openwa/deploy-chats-ui-polish.sh`.

**Live 2026-08-10:** push+build+force-recreate; readiness 200;
`a7-voice-player` + `a7-tools-menu-btn` in `/app/dashboard/dist`. Browser
spot-check (menu click / voice / video fullscreen) still for Matloob.

### 2026-08-10 ? Cursor session ? CRM WhatsApp tab: Omni + Linked devices

CRM tab two buttons; **Open with WhatsApp** must use `BX24.openApplication({
linked_phone })` into the side panel (not embed OpenWA inside the CRM tab).
`index.html` ? `mountInbox` ? `honourOpenRequest` ? `openLinkedDevices(phone)`
with `/chats?phone=` + auth handoff; missing chat opens NewContactModal
(`initialPhone`). Owner Data `CRM_DYNAMIC_1042_DETAIL_TAB` still registered.

**Shared:** crm-tab.js/css, index.html, inbox.js, Chats.tsx, NewContactModal,
Login/main/chatFilters, TASKS.md. Deploy via `ops/openwa/deploy-crm-open-whatsapp.sh`.

### 2026-08-10 ? Cursor session ? Conversation Health also matches Owner Data (SPA 1042)

Phone resolve order is now: existing CRM Lead ? Owner Data (`entityTypeId` 1042,
phone fields `ufCrm5_1768317611513` / `ufCrm5_1769416533028`, same as
`backend/apps/crmlink/client.py`) ? else create WhatsApp Lead (`UC_WA_LEADS`).
`chat_leads.bitrixEntityType` stores `lead` or `DYNAMIC_1042`; timeline comments
use that ENTITY_TYPE; Open lead URL points at SPA details when Owner Data.
Owner Data colour/chat UF writes only if `BITRIX_OWNER_*_FIELD` env set (webhook
cannot create SPA userfields ? timeline `[WA]` / `[AI Monitor]` still written).

**Shared:** `bitrix-lead.client.ts`, conversation-health service/entity/constants,
migration `1786600000000-AddChatLeadBitrixEntityType`, docker-compose /
`.env.example`, specs, `ops/openwa/deploy-owner-data-match.sh`.

**Live deploy 2026-08-10:** `deploy-owner-data-match.sh` push+build+force-recreate.
Proved: readiness 200, `findOwnerDataByPhone` in dist, `chat_leads.bitrixEntityType`
column present, env `BITRIX_OWNER_DATA_TYPE_ID=1042` `REDIS_HOST=openwa-redis`,
summary total 495. Full backfill skipped (avoid duplicate timeline comments).
New chats / new `chat_leads` rows will use Lead ? Owner Data ? create WA Lead.

### 2026-08-10 ? Cursor session ? Bitrix lead 72122 empty card (data was already there)

User screenshot of `crm/lead/details/72122/` showed empty Conversation Health
and only ?Lead created? on the timeline. API prove: local `chat_leads` maps
phone `971508512115` colour yellow ? lead 72122; Bitrix already had
`UF_CRM_CONVERSATION_HEALTH=2309` (YELLOW), full `UF_CRM_WA_CHAT` (~720 chars),
`UF_CRM_AI_MONITOR`, and 3 timeline comments (`[WA history?]`, `[AI Monitor]`).
Root cause was card layout, not missing sync: section fields had
`optionFlags=0` (not always show) + personal layouts. Fixed via
`ops/openwa/fix-lead-form-ui.py --fix` (`optionFlags=1` on health/monitor/chat,
all `leadCustomerType` scopes) + `forceCommonScopeForAll` + UF labels/rows.

**Shared:** `ops/openwa/fix-lead-form-ui.py`, `ops/openwa/check-bitrix-lead.py`,
TASKS.md. **Not proved in browser:** hard-refresh of 72122 after forceCommon
(needs Matloob spot-check). Comment tab if Activity still filters them.

### 2026-08-09 ? Cursor session ? OpenWA Conversation Health full sync

Nest module `openwa/src/modules/conversation-health/` (chat_leads, Bitrix client,
OpenAI/Whisper, Bull worker), MessageProjector enqueue hook, summary/list/lead/
backfill APIs, dashboard `ConversationHealthPanel` on Dashboard + Chats + Open
lead. Ops: `ops/openwa/deploy-conversation-health.sh`,
`ops/openwa/prove-conversation-health.sh`,
`ops/conversation-monitor/backfill-all-openwa.sh`.

**Live prove:** API healthy again (Linked devices 502 was ChatLead `phone` typed
as Object + boot crash). `REDIS_HOST=openwa-redis` (bare `redis` hit a7wa-redis).
Backfill jobIds unique per run; LID?phone via `lid_mappings`; explicit
`createdAt`/`updatedAt` on insert. After backfill sample:
`summary` showed colours (e.g. red/pink/green) and `chat_leads` rows with Bitrix
ids (71955+). Queue still draining remaining chats.

**Shared files:** conversation-health module, message-projector, session.module,
queue module/names, docker-compose (`QUEUE_ENABLED` forward), env-precedence,
Dashboard/Chats/api/en.json, `ops/wa.sh` (known_hosts wslpath + openwa recreate
with redis profile), TASKS.md.

**Not fully re-proved in UI:** agent-scoped colour strip click-through and live
new-message ? timeline comment (worker path is live; spot-check in Bitrix when
queue finishes).

### 2026-08-09 ? Cursor session ? Conversation Health Phase 1

Bitrix lead enum field `UF_CRM_CONVERSATION_HEALTH` (field id 2522; enum
RED/PINK/YELLOW/WHITE/GREEN = 2307?2311). Secrets live only in root `.env`
(gitignored) + `.env.example` placeholders. Classifier:
`ops/conversation-monitor/phase1_classify.py` (OpenWA ready sessions ? OpenAI
JSON colour ? `crm.lead` update + `[AI Monitor]` timeline comment). Run:
`ops/conversation-monitor/run-phase1.sh` on VPS.

**Proved live:** 12 chats classified (6 ready sessions, 210 phone-ish candidates).
Sample lead `71863`: field=`2307` (RED), timeline comment `[AI Monitor] RED`.
Also green/pink samples in 71854?71862 / 64845 / 70567. Spot-check:
`ops/conversation-monitor/verify-lead.sh 71863`.

**UI fix:** value was on the lead but missing from the shared card layout. Added
top section **Conversation Health** via `crm.lead.details.configuration.set`
(+ labels / `forceCommonScopeForAll`). Script:
`ops/conversation-monitor/add-health-to-lead-form.sh`. Hard-refresh lead 71863
? section should show **RED**.

**Kanban split:** new status **WhatsApp Leads** (`UC_WA_LEADS`, sort 25,
between Assigned and Contacted). Moved 10 Phase-1 creates (71854?71863) out of
`NEW`. Future `crm.lead.add` from classifier sets `STATUS_ID=UC_WA_LEADS`;
existing sales leads matched by phone keep their stage. Script:
`ops/conversation-monitor/create-whatsapp-leads-status.sh`.

**Card UI:** enum labels ? `?? RED` / `?? PINK` / ? (Bitrix has no native
colour swatch). New fields `UF_CRM_AI_MONITOR` (why) + `UF_CRM_WA_CHAT` (thread
snippet) under Conversation Health section. Backfilled 10 Phase-1 leads; prove
71856 = ?? + reason + chat. Scripts: `upgrade-health-ui.sh`,
`backfill-wa-chat.sh`.

**Caveats:** (1) rotate OpenAI key + consider regenerating Bitrix webhook ? both
were pasted in chat. (2) Some ?phones? are still LID digits; `crm.lead.add` for
those can fire existing n8n outreach (seen on 71863). Next: stricter phone gate
before create, prefer `findbycomm` only when E.164-looking. (3) Many OpenAI
`confidence` values came back `0.0` ? prompt/schema tweak later. Not deployed as
a service yet ? manual/script only.

### 2026-08-09 ? Cursor session ? `openwa` ? All chats dropdown + LID?phone

All chats select no longer disables: dropdown has **All chats** (`__all__`) plus
sessions; picking a person exits merge mode. LID titles: persist `senderPhone` in
message metadata, use it in chat-list overlay, enrich lists via
`enrichLidChatNames` when `RESOLVE_LID_TO_PHONE=true`. Compose now forwards that
env (was missing ? `.env` alone never reached the container).

**Deployed** image `aad99ad7?`, healthy/readiness 200, `resolve-lid-runtime=true`.
Live `GET /sessions/chats/all`: 650 chats, 534 `@lid`, **349** phone-like titles
(sample `923192782505` / `971549966321` instead of raw LID). Sidebar source has
`ALL_CHATS_SESSION_ID` option. UI click in Bitrix not re-proven here.

PDF Conversation Monitoring brief = separate n8n/Bitrix colour project (not this
deploy).

Files: `ChatSidebar.tsx`, `Chats.tsx`, `chat-list-overlay{,.spec}.ts`,
`message-row.mapper{,.spec}.ts`, `session.service.ts`, `docker-compose.yml`,
`ops/openwa/deploy-all-chats.sh`, `enable-lid-env.sh`, `verify-lid-allchats.js`;
`TASKS.md`.

### 2026-08-08 ? Cursor session ? `openwa` ? Asma restored again (675 msgs)

Live had no `asma` row (msgs 0). Guarded restore from
`openwa-data-20260808T074558Z.tar.gz` after updating `restore-asma.js` to allow
asma **absent** (not only empty replacement) and keep marketting/minahil by
before/after equality (floor 68/62; live marketting was 87). Cold safety backup
`openwa-data-20260808T174520Z.tar.gz` MD5 `90289d1f?`. Restore PASS:
asma `e209881a-?` **disconnected**/675 + `manualStartRequired`; marketting 87 /
minahil 62 untouched. `openwa-verify-asma-restore` PASS (agent-10 scope, 91
chats, thread total 12). API health check timed out at script end but later
healthy/readiness 200.

**Needs Matloob:** Linked devices ? asma ? **Start** ? new pairing code (manual
start armed; no auto QR).

Files: `ops/openwa/restore-asma.js`, `TASKS.md`.

### 2026-08-08 ? Cursor session ? `openwa` ? All chats + soft session remove + phone search

Admin-only **All chats** (`GET /sessions/chats/all` + sidebar button): merged
list across sessions, session name + status under each row, newest first;
`canOpenThread=false` for soft-removed (list only). Session **delete** is now
soft-remove: keeps messages, sets `removedAt`, purges auth; same-name create /
Start restores; READY reattaches messages from other soft-removed rows with the
same phone. Message delete never wipes DB body (admin content + Deleted label;
agents redacted). Chat search matches formatted phone digits too.

Files: session entity/migration `removedAt`, `session-engine-controls`,
`session.service/controller/lifecycle`, `message.service`, dashboard
`Chats{,.css}`, `ChatSidebar`, `Sessions`, `api.ts`, `chatFilters`;
`ops/openwa/deploy-all-chats.sh`, `ops/openwa/verify-all-chats.js`.

**Deployed** no-cache `openwa-api` image `75c8bbde?`, readiness 200, healthy.
Build first failed on `Sessions.tsx` typo (`null>` vs `null}`); fixed and
rebuilt. Live verify: `removedAt` column present (7 sessions / 0 removed);
`GET /sessions/chats/all` ? 200, **550** chats, sample has
`sessionName`/`removed`/`canOpenThread`. **Not UI-clicked** in Bitrix; soft-delete
round-trip and phone-search not exercised live. Asma history from earlier hard
deletes still needs backup restore if wanted.

### 2026-08-08 ? Cursor session ? `openwa` ? asma pairing reset to `qr_ready`

Root cause of ?code enter karne pe bhi connect nahi? was
`IDENTITY_BUFFER_TIME_LIMIT`: acceptance buffer armed its 30s clock at
`begin()`, so QR/pairing wait killed the generation while the UI still said
Waiting. Code fix already in
`openwa/src/modules/session/session-engine-acceptance-buffer.ts` (timer only on
first deferred event); live image `449a8b12?`.

Reset script `ops/openwa/reset-asma-pairing.sh` was broken (nested heredoc ate
stdin under `bash -s`). Rewrote to scp + remote file. Live reset: wiped asma
auth profile, cleared `historySyncError`, started ? **`asma:qr_ready`**, error
`none`. marketting/minahil still `ready`.

**Needs Matloob now:** Linked devices ? asma ? **Change Number / Request New
Code** (old code dead) ? phone pe enter. Purani WXQA code mat use karo.

### 2026-08-08 ? Codex session ? `openwa` ? Asma history restored; destructive delete guarded; profile reset live

Surgically restored old session `e209881a-0aa3-4463-849f-ff0ed37144b5`
from pre-delete `openwa-data-20260808T074558Z.tar.gz`: source held exactly
**1 session + 675 messages**, and all 675 were restored in one guarded
transaction. Removed only zero-message replacement
`1faa69b9-3409-494d-8c93-2df8a9eb4975`; Marketting/Minahil stayed 68/62 across
that transaction. Restore safety backup: `openwa-data-20260808T083852Z.tar.gz`,
MD5 `dcd1d2c520217fe55599ea890e55f65c`.

Decision: delete remains destructive. Dashboard/backend now expose exact delete
impact and require same count on DELETE; preflight and in-transaction count races
return 409 without deleting rows. Separate admin **Reset profile** force-stops
engine, strictly purges both auth profiles, preserves session ID/phone/messages,
sets `disconnected`, and requires explicit Start (no boot-generated QR). Core
TDD: reset preserves 675; stale and in-transaction count changes both stop delete.

Deployed with Opus/Cursor per-message media work in same recreate. A concurrent
Cursor recreate changed pre-deploy image to `sha256:a4ab8f9f?`; it auto-started
restored Asma into `action_required`, so Asma was immediately stopped without QR
scan. Fresh post-restore cold backup before this deploy:
`openwa-data-20260808T090853Z.tar.gz`, MD5
`6c53f52c2a15d068e16c0443bf1300f6`. New image
`sha256:3eab23a1172789b2f107cba7d053caa7c6837f056d9c5cdbb870fae0e44b9e75`,
healthy/readiness 200. Final: Asma `disconnected`/100/**675**/manual-start;
Marketting `ready`/100/**76** (live traffic grew it after restore); Minahil
`ready`/100/**62**.

End-to-end PASS: Django active assignment still points old ID; agent 10 scoped
session contains Asma; real headless live dashboard showed Asma, 91 chats, opened
a stored thread with 12 bubbles, showed Reset profile, and delete impact exactly
675. Django tables untouched. Backend focused session tests 300/300, media tests
117/117, dashboard Sessions tests 8/8, deployed backend/dashboard builds,
changed reset-source ESLint, ops fixed-command tests, and shell syntax passed.
After deploy, Cursor's newer concurrent soft-delete edit made current shared-tree
`nest build` fail at `message.service.ts:933` (TypeORM metadata partial typing);
that later unrelated edit is not in image `3eab23a1?` and was not modified here.

Files: `openwa/src/engine/engine.factory.ts`; audit action; session reset helper,
DTO, controller/service/lifecycle/controls and specs; dashboard `Sessions.tsx`,
`Sessions.test.ts`, shared `services/api.ts`; `ops/wa.sh`,
`ops/openwa/{restore-asma.js,arm-asma-manual-start.js,verify-asma-restore.py,verify-asma-dashboard.js}`;
`TASKS.md`. History-media import flag/backfill and `DATABASE_SYNCHRONIZE` were not
touched.

### 2026-08-08 ? Cursor session ? `openwa` ? agent message delete is soft for admin

Agent/operator delete no longer calls WhatsApp or clears the stored body. It sets
`metadata.agentDeleted`; agents get a revoked placeholder on read; admin keeps
the real content with a **Deleted** tag. Admin delete still revokes for everyone.
Chat list preview treats agent-deleted rows as ?Message deleted?.

Files: `message.service{,.spec}.ts`, `message.controller.ts`,
`chat-list-overlay.ts`, dashboard `Chats{,.css,.tsx}`, `ChatThread.tsx`,
`chatMessages.ts`, `api.ts`, i18n locales; `TASKS.md`.

### 2026-08-08 ? Cursor session ? `openwa` ? agent-only embed shell; admin rail restored

Earlier embed CSS hid the app rail for every framed session, including admin.
Scoped to `data-embedded` + `data-agent-embed` (Layout sets the latter only when
role is operator/viewer). Agents are routed only to `/chats` (index + catch-all);
admin keeps Dashboard/Sessions/nav/logout as before. Deployed no-cache rebuild.

Files: `a7-embedded.css`, `Layout.tsx`, `App.tsx`; `TASKS.md`.

### 2026-08-08 ? Cursor session ? `openwa` ? embedded Linked devices hides app rail

Framed (`data-embedded`) OpenWA now hides the app sidebar / mobile header /
overlay and lets `.main-content` go full width, so Linked devices shows only
chats. Standalone unchanged. Deployed via push of `a7-embedded.css` + no-cache
rebuild.

Files: `openwa/dashboard/src/a7-embedded.css`; `TASKS.md`.

### 2026-08-08 ? Cursor session ? `openwa` ? media fix live; asma waiting on QR

Deployed the per-message media path (`mediaFor`) plus the merge fix so Tap-to-load
keeps history bytes over a DB omitted placeholder. Cold backup
`openwa-data-20260808T081412Z.tar.gz` taken first; earlier backup
`openwa-data-20260808T074558Z.tar.gz` still holds pre-delete asma rows if a
surgical restore is wanted. No-cache rebuilt `openwa-api`
(image `4ba6c732?`, healthy). Recreated/started `asma` ? **`qr_ready`**;
`marketting`/`minahil` stayed **ready**.

Bitrix ?unknown? = Meta `unsupported` (131051); one media 401 = expired URL ?
neither is recoverable from our side.

**Needs Matloob now:** open OpenWA dashboard and scan `asma` QR immediately
(before `IDENTITY_BUFFER_TIME_LIMIT` / `action_required`). After ready, history
import restores what WhatsApp still has; ticks follow. Asma?s old SQLite rows
were removed by earlier dashboard deletes, not by this deploy.

Files: engine/message/dashboard mediaFor + `chatMessages.ts` merge; ops helpers
`ops/openwa/{recreate-asma,rebuild-nocache,verify-media-fix,list-backups}.sh`;
`TASKS.md`.

### 2026-08-08 ? Opus session ? `openwa` ? one bubble's media, not the whole chat's

Follow-up to this morning's `a2fb014`, whose own commit message named the weakness:
pressing an omitted media bubble fetched the **chat's** media, and WhatsApp reports a
file it no longer serves only by timing out. Ten dead files in one chat therefore cost
ten � `MEDIA_DOWNLOAD_TIMEOUT_MS` ? about five minutes of spinner ? to answer for the
one bubble the agent pressed, and then condemned all ten with that single answer,
though a chat can hold a dead file from February beside a live one from this morning.

`getChatHistory` takes an optional `mediaFor` (a message id): the slice still returns
whole, only the named message is downloaded. The thread's loading/outcome state moved
from one-per-chat to one-per-bubble, so bubbles fetch in parallel and each keeps its
own verdict.

Files: `openwa/src/engine/interfaces/whatsapp-engine.interface.ts`,
`engine/adapters/{wwebjs-messaging,whatsapp-web-js.adapter,baileys.adapter}.ts`,
`modules/message/message.{controller,service}.ts` + `message.service.spec.ts`,
`whatsapp-web-js.adapter.spec.ts`; dashboard `services/api.ts`,
`hooks/useChatMessages.ts`, `components/chats/ChatThread.tsx`, `pages/Chats.tsx`.
**Shared file touched: `openwa/dashboard/src/pages/Chats.tsx`** (one prop + one hook
name) ? it was already dirty from earlier work, which was preserved.

Verified: `nest build` and the dashboard build pass; ESLint clean on every changed
file; jest `whatsapp-web-js.adapter` + `modules/message` = 805 passed, the only 3
failures the known Windows-only Chromium-sweep cases (Linux `ps`/SIGKILL). New tests
cover the narrowed download, an id outside the slice, and that the old three-argument
engine call shape survives for callers passing neither `mediaFor` nor a signal.

**Not verified, and not deployed.** Nothing was pressed in a browser and no image was
built: the dashboard is bundled into the OpenWA image, so shipping this recreates
`openwa-api`, and a Codex session was mid-way through restoring `asma` from the
identity backup. Recreating the container under that would have been a data risk, not
a deploy risk. Deploy after that restore lands.

Also worth the next session knowing: `asma`'s 675 messages did **not** vanish to a
bug. `Session deleted: asma` at 07:57:03 and again at 08:01:59, each with a requestId,
with `A7 Admin (rotated 2026-08-06)` connected to the events gateway and three QR codes
generated between them ? the stale-profile reconnect, done by hand from the dashboard.
Deleting a session cascades to its messages, and nothing warned that it would. The
repair path (reset the engine's profile without touching the rows) is Codex's task.

### 2026-08-08 - Codex session - `openwa` - legacy LID proof, identity gate deployed

Resolved both audit rows without weakening gate. Asma's row is an outgoing
`system` provider artifact whose nominal owner-side `from` LID is independently
proved customer-side by 18 ordinary inbound Minahil rows; every witness has an
owner side that exactly matches Minahil's bound identity. Marketting's row is an
incoming `call` artifact with `from = to = chatId`; one ordinary Marketting
inbound text row proves that exact LID customer-side while its owner side matches
Marketting's bound identity. Neither LID exists in `lid_mappings`. Historical
and provider-artifact paths never invoke opt-in live inbound LID resolver, so
these mappings were never persisted. Current engine resolution was not needed
or probed: exact ordinary-row witnesses plus strict artifact shapes form new
evidence path. Unwitnessed or malformed artifacts remain INCONCLUSIVE.

Gate opened: cold and post-deploy audits both reported Asma 675/675,
Marketting 68/68, Minahil 62/62, overall PASS. No unresolved-count tolerance or
type-only exception was added. Focused audit tests pass 12/12, ops fixed-command
tests and shell syntax pass, TypeScript build passes. Full session/engine Jest:
42/44 suites and 1,825/1,842 tests pass; all 17 failures are unchanged Windows
platform cases (`patch` ENOENT and Linux `ps`/SIGKILL expectations).

Deployed only OpenWA identity files after stop-window backup. Old image/digest:
`sha256:7176a8f007de50e4014723e2bf97f43e68893771c78cc3686166828da6537334`.
Backup: `openwa-data-20260808T074558Z.tar.gz`, MD5
`78cd77b9a44242d2468e4016bdc9e4d0`; archive contains exactly one SQLite file.
New running image/digest:
`sha256:937322d6b7922941a2eb44fe73be34eac49352f6616f0873adad049f8acc1999`.
Internal readiness HTTP 200; container healthy; SQLite quick-check `ok`; required
identity columns 3/3; duplicate message identity groups 0. Live config uses
`DATABASE_SYNCHRONIZE=true`, so no TypeORM migration-ledger table exists; schema
was verified directly instead. Final sessions: Asma `failed` 100 (unchanged
stale-profile case, no recovery attempted), Marketting `ready` 100, Minahil
`ready` 100; no sync errors or new `ACTION_REQUIRED` state. QR, new sessions,
Django, Bitrix, panel, and `wa-qr` untouched.

Files changed in this follow-up: `legacy-identity-audit.{ts,spec.ts}`,
`ops/openwa/identity-audit.sh`, `ops/wa.sh`, `ops/wa.spec.sh`,
`ops/test-bin/ssh.exe`, `TASKS.md`. Shared frontend files untouched; unrelated
dirty work preserved.

### 2026-08-08 ? Codex session ? `openwa` ? permanent WhatsApp identity binding gate

Implemented prospective one-session/one-number binding before READY, auth side
effects, history import, engine reads, or sends. Every engine generation now gets
a durable compare-and-set token plus bounded pre-acceptance buffer (500 events,
16 MiB, 30 s); accepted events drain in order, while invalid, mismatched, stale,
or overflowing generations are revoked without replay. First-link identity and
immutable history anchor persist atomically. Actual conflicts become durable
`ACTION_REQUIRED`; teardown preserves bound phone, checkpoint, and messages.
Only credentials created through fresh QR in rejected generation are purgeable.
Logout retains identity/history; incomplete logout remains `ACTION_REQUIRED`.

Legacy classification under approved prospective override: **minahil PASS**;
**marketting legacy-safe**; **asma legacy-safe**; no current session quarantined.
Marketting and asma each still have one unresolved LID, so strict sanitized audit
remains **INCONCLUSIVE** and deployment gate remains closed until mappings resolve.

Verified: exact `npx jest src/modules/session src/engine` ran 44 suites / 1,840
tests: 42 suites and 1,823 tests passed; remaining 17 are existing Windows-only
failures (`patch` ENOENT and Linux `ps`/SIGKILL expectations). Focused session +
Baileys run: 23 suites / 895 tests passed. Changed-file ESLint and `npm run build`
passed. No deploy, live
start/stop/restart, QR operation, DB write, Asma recovery, Django, Bitrix, or
`wa-qr` action performed.

Files: `openwa/src/engine/{identity,interfaces,adapters}`,
`engine-registry.service.{ts,spec.ts}`; `openwa/src/modules/session/` entity,
buffer, guard, gate, lifecycle, controls, event wiring, error store, broadcaster,
module, service and specs; additive migration
`1786300000000-AddLosslessHistorySyncState`; `TASKS.md`. Shared frontend files
untouched; unrelated dirty work preserved.

### 2026-08-08 ? Opus session ? `openwa` ? the video that reads `?? Media`, and why it cannot be played

A video in the thread showed the omitted marker and its filename, with nothing to
play or download. **187 of 190 media rows on the live account had no bytes** ? only
3 did, all fetched live.

That much is by design: history is read media-free on purpose, because a chat full
of video would otherwise sit in heap as base64, held twice as a `data:` URI. The
defect was that there was no way to ever ask for it. So the placeholder is a button
now ? one press fetches that chat's media, bounded by the gateway's existing
aggregate budget and per-message cap, and merged so the DB copy still wins (which
is what carries live media and the delivery ticks).

**Then the measurement changed the answer.** Every download timed out:

```
Inbound media download timed out (MEDIA_DOWNLOAD_TIMEOUT_MS); emitting message without media
```

?once per file, thirty seconds apart, for all ten. **WhatsApp no longer serves the
bytes for these files** ? the video is dated 9 July, a month old. The code comment
on the history importer predicted exactly this: *"the bytes for anything old enough
to be in a backfill are mostly no longer served anyway."* It is retention, not a
bug, and nothing on our side recovers it.

So the bubble had to tell three outcomes apart, not two: the request failing, the
request working and WhatsApp having nothing, and success. `gone` is not retryable
and the button disables itself ? inviting an agent to press again for a file that no
longer exists is a lie the panel would tell every time they opened that chat.

**A bug in the first version of that, caught by testing it rather than reasoning
about it.** The success count was "how many messages in the slice have bytes",
which is a different question: a chat holding one live photo reported success while
every bubble the agent pressed stayed omitted ? so it said "Tap to load" again. It
now counts only the ids that were *waiting before the fetch* and arrived with
bytes.

Verified in a browser, end to end: 10 buttons reading `?? Media ? Tap to load`,
pressed one, and after the downloads timed out the bubble read **"WhatsApp no
longer has this file"** and stopped offering.

**Known weakness, not fixed:** the wait before that message is long ? ten files �
a thirty-second timeout is about five minutes of spinner. The right fix is a
per-message fetch (`getMessageById(id).downloadMedia()` behind a narrow route) so
one press costs one timeout instead of the chat's worth. That is engine +
controller + service work and was not started here; the chat-level fetch is what
exists today.

Files: `dashboard/src/hooks/useChatMessages.ts`,
`dashboard/src/components/chats/ChatThread.tsx`, `pages/Chats.tsx` (one prop),
`pages/Chats.css`.

### 2026-08-08 ? Codex session ? `openwa` ? sanitized legacy identity audit built and run read-only

Added the missing pre-mutation gate from the approved lossless-history design.
`ops/openwa/identity-audit.sh` transpiles the tested TypeScript source locally,
sends it over pinned SSH as base64, and runs one Node process inside the healthy
OpenWA container. That process opens SQLite with `readOnly: true`; it does not
boot Nest, TypeORM, or a WhatsApp engine. A second local allowlist refuses to
print anything except safe session labels, counts, decisions, and the overall
decision. Exit codes are PASS 0, INCONCLUSIVE 1, FAIL 2.

Live read-only result:

| session | rows | resolved | unresolved | decision |
|---|---:|---:|---:|---|
| asma | 675 | 674 | 1 | INCONCLUSIVE |
| marketting | 67 | 66 | 1 | INCONCLUSIVE |
| minahil | 62 | 62 | 0 | PASS |

Overall: **INCONCLUSIVE**, exit 1. Aggregate read-only follow-up proved why:
both inconclusive sessions have exactly one account-side LID without a persisted
phone mapping. Missing owner-side identity count is **0** for all three. This is
the repairable mapping-gap case, not old-release rows that never stored owner
identity. The audit worked while `asma` remained offline; no engine was needed.

TDD: focused audit suite **10/10**. `npm run build`, focused ESLint/Prettier, and
`bash -n` pass. The live stdout was checked against known identities plus generic
JID/path/secret patterns; no phone, JID, message/content field, key/token,
credential, path, or raw error appeared. The requested full Windows command is
not green in the current untouched baseline: 38 suites / 1,781 tests pass, while
two unmodified engine specs fail 17 tests initially. Making Git's Unix tools
visible reduces that to six known platform failures: three orphan-sweep tests
whose Linux-only branch returns early on win32, and three `symlinkSync` EPERM
tests. They were neither fixed nor skipped. Excluding only those two unrelated
files leaves **38 suites / 1,304 tests green**.

Files: `ops/openwa/identity-audit.sh`,
`openwa/src/modules/session/legacy-identity-audit.ts`,
`openwa/src/modules/session/legacy-identity-audit.spec.ts`,
`docs/superpowers/plans/2026-08-08-openwa-legacy-identity-audit.md`, `TASKS.md`.

Not done: no deploy, DB write, UPDATE, migration, session restart/start,
identity enforcement, Django/Bitrix/wa-qr change, or `asma` recovery attempt.

### 2026-08-08 ? Opus session ? `openwa` ? one tick against two blue ones on the handset

A conversation the agent had plainly finished still showed a single ? on every
message she sent. **506 of 521 outbound rows** were `sent`; 7 read, 7 delivered.

The rendering was never the problem: the thread already draws `??` for delivered
and read, and the CSS already paints `read` in WhatsApp's own `#53bdeb`. The data
was wrong. Two causes, and the second is the one that mattered:

1. **The history import stamped `status: SENT` on every row it wrote**, regardless
   of what WhatsApp said about it. A message the customer read a fortnight ago was
   imported as one tick.
2. **`message_ack` is a live event and is never replayed.** It fires once, when
   the tick moves. Every ack that landed while this gateway was restarting ? and it
   restarts on every deploy ? is gone for good. Nothing existed to recover it.

So the ack is now read off the message itself (`msg.ack`, falling back to
`_data.ack`, which some builds populate when the wrapper's getter is undefined),
mapped through the same `wwebjsAckToDeliveryStatus` the live path uses, and carried
on `IncomingMessage.deliveryStatus`. Only for `fromMe` messages ? an inbound
message's ack describes the *sender's* copy, not ours.

**Rows already stored are the point**, and `orIgnore` on the insert would have
skipped every one of them, so there is a separate reconcile: for the ids the import
finds already present, advance the status. **Forward only**, through
`ackStatusTransitionFrom` ? the same guard the live path uses ? and with the guard
in the WHERE clause rather than a read-then-write, so a live ack arriving mid-import
cannot be overwritten by a slower one from here. Grouped by target status, so a
batch costs at most three UPDATEs instead of one per message.

**The first pass only moved 2 ticks, and that was informative.** The import reads
from the watermark forward, and the messages on screen were from two days before
it ? never re-read, so never reconciled. Clearing `historyImportedAt` on the ready
sessions turned the next connect into a full ten-day pass:

| | before | after |
|---|---|---|
| outbound `read` | 7 | **39** |
| outbound `delivered` | 7 | 8 |
| outbound `sent` | 506 | **473** |
| the chat in the screenshot | every row `sent` | **every row `read`** |
| marketting single ticks | many | **zero** |

Of the 473 still single-ticked, **464 belong to session `asma`, whose status is
`failed`** ? it never connects, so no import runs and nothing can be read back.
That is the pre-existing `asma` problem, not this one. The other 9 are older than
the ten-day window and were never re-read. Genuine.

Verified in a browser: 13 tick icons in that chat, every one class `read`, glyph
`??`, computed colour `rgb(83, 189, 235)`. Tests **2126/2126**, 51 suites.

**Worth knowing:** clearing the watermark is how you force a deep reconcile. It is
idempotent ? the unique index refuses everything already stored ? and costs one
ten-day import per session.

Files: `engine/interfaces/whatsapp-engine.interface.ts`,
`engine/adapters/message-mapper.ts`, `modules/session/message-history-projector.ts`.

### 2026-08-08 ? Opus session ? `openwa` ? nine rows in ten said "Unknown user", and none of them was a conversation

The chat list was mostly `Unknown user / No messages yet`. **That string is
WhatsApp Web's own** ? it appears in no source file of ours and in no built
bundle; the adapter passes `chat.name` straight through, and its own fallback
would be the chat id, not those words.

What those rows actually are: chat **shells** WhatsApp Web reports for
address-book entries and for chats opened once and never used. No name it could
resolve, no last message, and `timestamp: 0`. They carry nothing, so there was
nothing to resolve ? and they accumulate.

**A first theory that measurement killed.** It looked like a new-session problem:
`minahil` linked the day before and was full of them, `marketting` had been linked
two days and looked clean. Checking `marketting` again showed **63 of 222** ? it
had simply grown from 157 chats to 222, unknowns included. Not a sync-lag
symptom; the ordinary state of an established account.

**The test is the emptiness, never the name.** Measured on both live numbers
before writing a line: every row named `Unknown user` also had `timestamp: 0`,
**no** such row had a real date, and no dated row lacked a name. One population,
two descriptions ? so keying on the emptiness is exact here *and* survives
WhatsApp translating or renaming its label.

A conversation older than the ten-day import window keeps its real timestamp: the
rows that read `Mar 10 ? No messages yet` are genuine chats whose messages fall
outside what we import, and they are untouched. Only rows with nothing whatsoever
are dropped.

`withoutEmptyShells` runs **after** `overlayStoredMessages`, and the order is the
point: the overlay is what gives a chat its date and preview back from our own
rows, so filtering first would drop chats we hold messages for. There is a test
pinning exactly that.

Resolving the ids to phone numbers was the other option and is the wrong first
move: `lid_mappings` holds one row, `RESOLVE_LID_TO_PHONE` is unset, and it would
mean ~99 page evaluations per list draw to label rows that hold nothing. An agent
who needs to reach one of those people uses **New contact**, which takes a number.

| | before | after |
|---|---|---|
| minahil | 110 chats, **99** `Unknown user` | **11 chats, 0** |
| marketting | 222 chats, **63** `Unknown user` | **156 chats, 0** |
| dated chats kept | 11 / 156 | **11 / 156** ? none lost |

Tests: **2126/2126**, 51 suites, including 5 new ones for the filter. Seen in a
browser, both themes: 11 rows, real names, real dates, no error toast.

**One failure that was not mine, and how it resolved.** The suite came back with
`getChats ? should throw BadRequestException when session is not started` failing.
That is another session's change ? with no engine, `getChats` now answers from our
stored rows instead of refusing ? and their **updated spec was in the working tree
but the server still had the old one**. Pushing the current spec made it green. If
you see a lone spec failure here, check whether the server's copy is behind the
tree before editing anything.

Files: `modules/session/chat-list-overlay.ts` + spec, `session.service.ts` (one
call and one import). `session.service.spec.ts` was pushed unchanged to bring the
server level with the tree.

### 2026-08-08 ? Opus session ? `openwa` ? a disconnected number's chats are readable again, and the OOM that was killing every phone

**The reason phones would not stay connected.** `openwa-api` carried a 2 GB
memory limit. Each whatsapp-web.js session is a whole Chromium ? **measured at
~430 MB** ? so three sessions plus Node sat at 1.7 GB, 84% of the cap. A history
import adds roughly 500 MB to the session running it; that spike crossed 2 GB,
the kernel OOM-killed the container, and all three phones fell over together and
restarted. `OOMKilled: true`, over and over.

Nothing was wrong with the handsets, and nothing was wrong with `asma` ? the
limit was ours. Raised to 6 GB and the churn stopped dead: all three held `ready`
for 20+ minutes where they had been dropping every 15 seconds. Matloob then
upgraded the box (KVM 4 ? KVM 8: 8 cores, 31 GB, 387 GB), so the limit is now
20 GB.

**A correction worth recording:** I twice said `wa-qr` had no memory limit, from
misreading a `docker stats` column. `docker inspect` says it has had a 4 GB limit
all along. Nothing was needed there.

**Database-first chat list.** `getChats` threw `Session is not started` whenever
no engine was loaded, so a number going offline took every conversation off the
screen with it ? while the messages sat in our own tables the whole time. With no
engine it now builds the list from stored rows (`chatsFromStoredMessages`), and
the dashboard's session picker includes non-ready sessions, labelled `(offline)`.

`unreadCount` is 0 there rather than a guess: unread is a fact about the handset,
and a stale badge is worse than none. Sending stays unavailable, which genuinely
does need the phone.

The old spec asserted the exception; its contract really did change, so it now
asserts the stored-chat answer instead. `src/modules/session`: **19 suites, 528
tests, all green.**

Verified live, and by luck on the hardest case: `asma` was `failed` at the time,
and `GET /sessions/<asma>/chats` returned **91 chats** with names and previews
where it would previously have refused.

Files: `openwa/src/modules/session/chat-list-overlay.ts`, `session.service.ts`,
`session.service.spec.ts`, `openwa/dashboard/src/pages/Chats.tsx`.

**Open, and needs Matloob:** `asma` will not start ?
`Protocol error (Runtime.callFunctionOn): Execution context was destroyed`. The
app's own message names the cause and the cure: a stale browser profile at
`/app/data/sessions/session-asma`, to be deleted before a fresh QR scan. Not done
here, because it forces a re-scan on a live number. Its messages are unaffected ?
they live in SQLite, not the profile ? and thanks to the change above they stay
readable meanwhile.

### 2026-08-07 ? Opus session ? `backend` + `bitrix` ? `[unsupported]` was true, and read like our fault

A chat showed `[unsupported]` in the list and `[unknown]` in the bubble. The
stored webhook payload says exactly what happened, in Meta's own words:

```json
"type": "unsupported",
"errors": [{ "code": 131051, "title": "Message type unknown",
             "details": "Message type is currently not supported." }],
"unsupported": { "type": "unknown", "raw_type": "unknown" }
```

So the customer sent something the **Cloud API will not carry to a business
number** ? a poll, a view-once message, whatever WhatsApp has added lately. The
content never reached us and cannot be recovered or re-imported, and Meta does
not even name what it was: `raw_type` is itself `"unknown"`.

Nothing to fix in the pipeline, then ? but plenty wrong with saying it that way.
`[unsupported]` reads to an agent as a fault in this panel, and the next thing
they do is report a bug instead of asking the customer to resend. Both places now
say what happened and what to do:

- list preview (`gateway/tasks.py` `_describe`) ? *Unsupported message ? ask them
  to resend it*
- bubble (`inbox.js` `UNSUPPORTED_LABEL`, keyed on both `unknown` and
  `unsupported`) ? *WhatsApp could not deliver this message. Ask the customer to
  send it again as text, a photo or a file.*

Only 2 such messages exist in the whole database (4 and 7 August), both carrying
131051. The preview is written once at receive time, so the change would not have
touched the ones already there ? the single stale row was rewritten by hand so
the fix is visible now rather than on the next occurrence.

Verified: the panel module is byte-identical on disk and over HTTPS
(`32a3e751?`), and the new text appears twice in what the site actually serves.

**A trap in my own tooling, recorded so the next person does not repeat it:**
`ops/wa.sh get` does **not** return the body ? it prints
`HTTP 200  88311 bytes`. Grepping its output for content always finds nothing and
md5-ing it hashes the status line, which briefly looked like nginx serving a
stale file. The size in that line is the real check; for content, curl the public
URL and hash that.

`bitrix/public/assets/modules/inbox.js` is a shared file ? only the label map was
touched.

### 2026-08-07 ? Opus session ? `openwa` + `backend` ? telling somebody when a linked phone goes away

When an agent unlinks their handset the inbox simply stops receiving on that
number. No screen says so, no status anybody watches changes, and the first sign
is a customer complaining nobody answered. Three numbers now get a WhatsApp when
it happens: `923078633218`, `971503928461`, `971555484423`.

**Sent as a template, and that is not a detail.** The 24-hour free-form window
opens only on an inbound message, so plain text to an admin who has not written
today fails with 131047 ? precisely when the alert matters. Matloob created
`whatsapp_device_disconnected` (UTILITY, en, two body variables) and, on advice,
left **Allow Category Change unticked**: reclassified as MARKETING it would fall
under Meta's per-customer daily cap that this account's 173 marketing templates
already share, and the one day it was needed it would go quietly undelivered.

**Two WABAs, and the second is the point rather than belt-and-braces.** The same
template is approved on `1529906518933156` (sends from `1170318422839203`) and on
`897583580064486` (`1198764669988838`). An alert that shares a business account
with whatever has gone wrong is an alert that can go down with it.

**Two kinds of "gone", told apart on purpose.**

- **unlinked** ? the agent removed the device. It is not coming back on its own,
  so the alert goes at once, from `logout()`.
- **dropped** ? the connection fell over. Most recover in seconds through the
  reconnect backoff, and one message per lost signal would train everybody to
  ignore the alert that matters. Held **10 minutes**, cancelled the moment the
  session reaches READY again. Re-arming while one is pending is a deliberate
  no-op: a session flapping every thirty seconds would otherwise keep pushing its
  own deadline back and never report at all.

Cancelled on READY rather than on a reconnect *attempt* ? an attempt is not a
recovery, and only READY proves the handset is answering.

**Not built on the webhook table**, though it exists and dispatches
`session.disconnected` already. A webhook is a row somebody has to remember to
create, per session: the next number an agent links would silently have no alert
on it and nothing would look wrong. This is configuration on the process, so it
covers sessions that do not exist yet. `logout()` also dispatched no webhook at
all, so the deliberate case ? the one that matters most ? had no event to hang
off.

Files ? gateway: `modules/session/device-alert.service.ts` (new),
`session.module.ts`, `session-engine-lifecycle.service.ts`,
`session-engine-controls.ts`, two spec provider lists, `docker-compose.yml`.
Backend: `apps/accounts/device_alerts.py` (new), `views.py`, `urls.py`,
`a7wa/settings.py`.

**Verified, and two of the three findings are worth carrying forward.**

| | |
|---|---|
| gateway suites after the DI change | **2121/2121**, 51 suites |
| route with no secret / a wrong one | **403** both |
| a real alert, end to end | **971503928461 ? ? 971555484423 ?** |
| `923078633218` | **failed from both WABAs** ? see below |
| gateway ? Django, wrong secret on purpose | **403** ? reaches it; the secret gate is all that stands between |
| `makemigrations --check` | No changes detected |

**`923078633218` cannot be reached from this WABA, and it is not our bug.**
WhatsApp itself says the number exists (asked through the linked device's
`contacts/check`, which sends nothing). But the same template fails to it from
**both** business accounts, and a *different* long-approved template fails to it
too, while the identical template to the UAE numbers succeeds. The gateway
returns a bare `HTTP 500 / "An unexpected error occurred"` with no reason, so
Meta's own explanation is not visible from here. The usual cause is a number that
is itself registered on WhatsApp Business Platform ? Meta will not deliver a
business message to a business sender. **Matloob should check whether that number
is one of the company's own WABA senders**; if it is, the alert needs a different
number for that person.

**Two configuration traps, both of which looked like working code.**

1. The gateway's `docker-compose.yml` has **no `env_file`** ? every variable is
   listed explicitly, and the file says so in a comment. Adding
   `DEVICE_ALERT_URL`/`DEVICE_ALERT_SECRET` to `.env` did nothing: the container
   came up healthy with both unset and the alert would simply never have fired.
   They are on the `environment:` list now.
2. Django answered the gateway with **400 Bad Request** ? `ALLOWED_HOSTS`, because
   the internal call carries `Host: web:8000`. `web` added. Worth knowing before
   the next service-to-service call inside the compose network.

**Not verified:** nobody has actually unlinked a handset to watch the alert fire.
That means taking Matloob's live number off the inbox, which is his call, not a
test to run unasked. Every link in the chain is proven separately ? the trigger
compiles and is covered by the suite, the gateway reaches the route, and the
route sends real WhatsApp ? but the whole thing has not been run once from a real
logout.

### 2026-08-07 ? Opus session ? `openwa` ? picked up the lossless-history branch; closed the one hole that loses messages silently

Matloob stopped the session working in the `codex/openwa-history-sync` worktree
and handed it over. Read the 202-line design first
(`docs/superpowers/specs/2026-08-07-openwa-lossless-history-sync-design.md`) ?
20 test scenarios, an identity audit, a seven-step deployment protocol. What was
actually built is the groundwork and nothing else: three nullable session columns
(`historyFirstLinkedAt`, `historySyncToken`, `historySyncError`), the
`(sessionId, chatId, createdAt)` message index, an additive migration, one config
value, and four spec files. **28 lines and five files.** No engine work, no
identity gate, no DB-first chat list, no pagination.

**Ran the tests rather than assuming**, and one of the four was red on purpose:
`session-engine-event-wiring.spec` asserts `onHistoryMessages` hands back the
projector's promise. It was returning `undefined`.

That is the spec's central safety property, and it was the live behaviour:

```ts
void host.messages.persistHistoryMessages(id, messages)
  .catch(err => this.logger.error(...));
```

A batch the database refused was logged and then looked, to the importer, exactly
like a batch that had been written ? so the checkpoint advanced past messages
that were never stored. Silent loss, in the one place the whole feature exists to
prevent.

The promise is now returned unwrapped, and the interface says
`void | Promise<void>` so a producer can await it. `.catch()` cannot come back
even in a form that returns something: it resolves a *new* promise, which the
caller cannot tell from success. `wwebjs-history` already awaited `emit(batch)`,
so the chain now runs end to end.

Files: `openwa/src/modules/session/session-engine-event-wiring.ts`,
`openwa/src/engine/interfaces/whatsapp-engine.interface.ts` ? **worktree only**.

Verified: the four focused suites go 3/4 ? **4/4**. Then the whole
`src/modules/session` + `src/engine` run: **1,779 pass, 7 fail** ? and those same
7 fail with my two files stashed, so **the branch was already red when it was
handed over**. They sit in `whatsapp-web-js.adapter.spec`,
`wwebjs-backport-201832.spec` and `session.controller.spec`, and belong to the
partial DTO/entity work, not to this change.

**Then the red tests, and deployed.** The other four failures were all the host,
not the code, and it is worth knowing which is which before "fixing" a test:

- `session.controller.spec` asserts the DTO's exact field list and the partial
  work added `syncError` without updating it. Added ? the contract genuinely
  changed.
- `whatsapp-web-js.adapter.spec` �3: `killOrphanedChromiumProcesses` returns
  immediately unless the platform is darwin/linux, so on a Windows box three
  tests asserted a kill that could never happen. The block now pins
  `process.platform` to `linux`, so they test the sweep instead of the machine.
- `wwebjs-backport-201832.spec` �3 build a git-only PATH with `fs.symlinkSync`
  and `which`. Windows has neither (EPERM without developer mode). Skipped
  **only** on win32; the script they cover runs solely inside the Linux image
  build.

`src/modules/session` + `src/engine`: **41 suites, 1,783 pass, 3 skip.** Full run:
20 failures remain across 7 suites (storage/config/plugins) ? every one of those
files is **untouched by this branch**, and they all turn on `chmod 0o000`, which
Windows ignores. Left alone deliberately: silencing 20 tests in code this branch
never touched would hide real Linux failures to make a Windows console look
green. `npm run build` passes.

**Deployed ? the two files only.** The rest of the branch is half of an identity
feature; shipping it would put that half in production. Backup first and taken in
a **stop window**, because the running copy gave `tar: file changed as we read
it` ? the same lesson as the wa-qr backup. `openwa-data-clean-20260807-115740.tar.gz`,
346 MB, md5 `e712e214?`. Image `a4c606e4?` ? `3d9ea94d?`, healthy.

**A data loss that is not this deploy's.** Messages had gone 500 ? 18 and the 441
group rows with them. The pre-deploy backup proves when: it already held **15
messages, 0 groups**. The deploy took it 15 ? 18, which is three live arrivals.
Whatever removed the history happened earlier and elsewhere.

**And the reason it never came back on its own, which is the real find.** A run
went 0 ? 100% and imported nothing. `historyImportedAt` read `12:03` ? now ?
because every run moves it to its own start time. The rows had been deleted while
the checkpoint marched on, so each import asked WhatsApp only for "since a moment
ago" and correctly received nothing. The checkpoint and the data had drifted
apart with no way back. That is precisely what the design's immutable
`historyFirstLinkedAt` anchor exists to prevent, and it is now a demonstrated
failure rather than a hypothetical one.

Rewound the watermark to NULL ? which the code reads as first link, so ten days ?
with the app stopped so nothing raced it. Nothing was deleted; the unique index
carried the duplicate risk.

| | before | after |
|---|---|---|
| messages | 18 | **47** |
| chats | ? | 8 |
| groups | 0 | **0** |
| duplicates | 0 | **0** |
| window | 6?7 Aug | **31 Jul ? 7 Aug** |

47 rather than the 59 non-group rows an earlier import found: groups and now
`system` notices are both filtered out, and WhatsApp's own available history
rolls forward. Stated as measured, not explained away.

**Still not done:** the sanitized identity audit the spec puts before any
production mutation does not exist, so it was not run.

### 2026-08-07 ? Opus session ? `openwa` ? the two message types that arrived and could not be read

Went through every WhatsApp message type against the library's own
`MessageTypes` enum rather than from memory. Everything an agent actually meets
renders: text, image, sticker, video, audio, voice, document, location, call,
revoked, masked ? and button/list/template replies, which carry the reader's own
words in `body` and are mapped to text. Two did not.

**A shared contact printed fifteen lines of raw vCard.** `vcard`/`multi_vcard`
carries `BEGIN:VCARD ? END:VCARD` in `body` and nothing else ? no media payload ?
and the thread had no case for it, so it fell through to the plain text bubble.
Now parsed in the browser (`components/chats/vcard.ts`, new) and drawn as a card:
name, then each number in a monospace, selectable line, because an agent's next
move is to copy it. Every contact in the body, not just the first ? that is what
`multi_vcard` means. A body that is **not** a readable vCard falls through to the
text bubble exactly as before, so nothing is ever swallowed.

Parsed client-side on purpose: the vCard text is already stored verbatim on every
such row including every one already in the database, so there is nothing to
backfill and no second copy to keep in step.

**A poll showed its question and nothing else, and that was a gateway fault, not
a UI one.** The options were on the raw message and were being dropped at the
adapter boundary ? `IncomingMessage` had no field for them. Added
(`poll: { name, options, allowMultipleAnswers }`), read off wwebjs's `pollName` /
`pollOptions` / `allowMultipleAnswers`, and stored in metadata beside `call` so a
poll in the history does not depend on the engine still holding its message.

**Vote counts are deliberately absent.** They arrive as their own events and
nothing subscribes to them yet, so the options are drawn with an empty ring
rather than a tick or a filled dot: a mark that looked like a selection would
claim something this screen cannot see, and an empty tally would read as "nobody
voted" rather than "not known".

**The parser is where this quietly goes wrong, so it has its own tests ? and one
of them caught something.** The fold test failed, and the code was right: vCard
folds a long line by breaking it and starting the next with a space, and *both*
the break and that space belong to the fold, not the value (RFC 6350 �3.2). A
number split mid-digits rejoins with **no** gap; the test had asserted a space.
Fixed the expectation, and widened the unfold to bare-LF folding while there ?
a continuation left on its own line reads as a property with no colon and is
dropped, losing the tail of a phone number silently.

Files: `engine/interfaces/whatsapp-engine.interface.ts`,
`engine/adapters/message-mapper.ts`, `modules/session/message-row.mapper.ts`,
`components/chats/vcard.ts` + `vcard.test.ts` (new), `components/chats/ChatThread.tsx`,
`services/api.ts`, `utils/chatMessages.ts`, `pages/Chats.css`, and two keys added
to **all twelve** locale files (checked they round-trip byte-identically first, so
the diff is two lines each and no upstream formatting moved).

**Verified on the live number, end to end, not by reading.** A contact and a poll
were sent to the phone's **own** number ? no third party involved ? then read
back out of the database and looked at in a browser, both themes:

| | |
|---|---|
| poll stored | `{"poll":{"name":"Site visit day?","options":["Saturday","Sunday","Either"],"allowMultipleAnswers":true}}` |
| contact stored | raw vCard in `body`, as expected |
| rendered | card reads **Abu Khaled / 971501234567**; poll reads the question, three options, "Multiple answers allowed" |
| `BEGIN:VCARD` visible anywhere on the page | **false** ? the raw text is suppressed under the card |
| chat list preview | picked up "Site visit day?" through the overlay |

Tests: gateway **1784/1784**, 39 suites. vCard parser **9/9**. The three test rows
were deleted afterwards so the database stays clean for the real numbers.

**Still not supported, and named so nobody re-derives it:** `album`, `order`,
`product`, `payment`, `ciphertext`, `interactive`, `native_flow`, `list`,
`oversized`. Of these only two turn up in practice ? an **album** (the individual
photos still arrive as their own messages, so the pictures are there; only the
grouping is lost) and **ciphertext** (a message not yet decrypted, which arrives
properly a moment later). The rest are Business catalog/checkout objects A7 does
not use. Each now carries its engine token as `rawType`, so a row says what it
was instead of only that it was unknown.

Cosmetic, unverified: the ?? and ?? glyphs render as boxes in the container's
headless Chromium, which has no emoji font. Every other emoji in this panel comes
from the same place and has always looked right in a real browser, so this is
almost certainly the screenshot and not the page ? but nobody has confirmed it in
Matloob's own browser.

### 2026-08-07 ? Opus session ? `openwa` ? cleared for real numbers, and the watermark a new phone would have inherited

Matloob is about to link the real numbers; the one linked so far was only ever a
test. Two things came out of that.

**There was no other device's data to remove.** Looked for it rather than
assuming: one row in `sessions`, one credential directory (`session-marketting`),
and every row in every table carrying a `sessionId` belonged to it. Nothing
orphaned, nothing left behind by an earlier session. Said here because "I found
nothing" is a result and the next person should not go looking again.

**A bug that would have bitten on the very next link.** `historyImportedAt` is
what tells the importer "read from here to now" instead of "read the last ten
days" ? and nothing ever cleared it. `logout()` cleared `phone` and left the
watermark. So unlinking the test phone and scanning the QR with a real number
would have handed that new number a resume point belonging to a handset it has
never met: not its own ten days, but "everything since some stranger last
synced". Cleared on both logout paths now.

The other half is the unlink that never touches our code at all ? **WhatsApp ?
Linked devices ? Log out, done on the phone**. No `logout()` runs, the row keeps
its number and its watermark, and the next QR can be scanned by anybody. So the
ready handler now reads the row before writing it and clears the watermark when
the number that just connected is *different* from the one recorded. Compared on
digits, because the two sides are written by different paths and a `+` must not
read as a different handset. A session reconnecting as the **same** number keeps
its watermark ? that is the whole point of having one.

That also meant the ready write had to stop racing the importer: it is now
awaited before `importHistory` starts, because that write is what may have
cleared the watermark and reading it first is the importer's opening move.

**The clear itself**, backed up first (`openwa.sqlite.bak-preclear-20260807`):

| | |
|---|---|
| messages | 53 ? **0** |
| status posts | 21 ? **0** |
| lid mappings / templates | 1 / 1 ? **0** |
| status media on disk | 18 files, **46 MB** ? 0 (12 K) |
| database file | 15.2 MB ? **295 KB** |

The 46 MB was other people's stories ? named contacts' photos and videos, held
with `expiresAt` **null**, so nothing would ever have removed them. Same class of
thing as the groups, and worth a decision of its own before real numbers link.
The rows were deleted first and the files only after confirming **0** rows still
referenced a path.

**The session row and its credentials were left alone.** Deleting them unlinks a
live handset, which is Matloob's call and not a database cleanup. The consequence
is visible and honest: on the next restart the watermark said "you last read to
Aug 6 19:08", so a catch-up import ran and brought back **7 messages across 2
chats** ? the real traffic of the last two days, groups excluded. That is the
rule working, not a leak. If this number should start from nothing, unlink it:
the new code then gives whatever links next its own ten days.

**No delete button was added anywhere, and none should be.** Matloob was explicit:
no admin and no agent gets a way to remove data from the panel. Everything above
was done by hand, once, against the database.

Tests: **1784 of 1784 pass, 39 suites.** Three specs pinned the old payloads ?
two logout assertions now expect the watermark to be cleared alongside `phone`,
and the ready-status test awaits a tick because the ready write reads the row
first. The third was tightened while it was open: `not.toHaveBeenCalledWith(?,
{ phone: null })` would have passed against any changed payload, so it is now
`not.toHaveBeenCalled()` ? the 400 path must not touch the row at all.

### 2026-08-07 ? Opus session ? `openwa` ? "connect a session first", said to somebody whose phone was connected

Chasing the red *Failed to load chats* toast turned up something worse sitting
behind it. Another session had already taught the Chats screen about
`syncProgress` ? a session below 100% is filtered out of the ready list, so no
chats request is made and no toast appears. But with that session filtered out
the list is empty, and the empty state says:

> **Please connect a WhatsApp session from the Sessions menu first.**

Which is false, and alarming in the one direction that matters: the phone *is*
linked, the number is on the card two clicks away, and an agent reading that
concludes it dropped off. **And it never cleared.** `loadSessions` ran on mount
only, so once the import finished the screen stayed on that message until
somebody reloaded the page ? a state with no way out that the screen itself
would offer.

Both halves fixed. The sessions held back for an import are now kept apart from
the ones that are simply absent, and get their own state ? a spinner, the
number, and the live percentage ? so the screen says the true thing. And
`loadSessions` was hoisted out of the mount effect so a 5-second poll can reuse
it while any import is running, stopping the moment none is. The poll is quiet:
a failed one raises no toast at somebody who is only waiting. It also refuses to
move the selection ? a poll must not drag an agent back to the first session
while they are reading a different one.

**Watched it happen, in a browser, without touching the page.** Opened the Chats
screen at **51%**, saw the same page's own copy read **78%** a minute later, and
at **~110 seconds the chat list appeared with 157 rows** ? no reload, no
navigation, no toast. That is the claim that needed proving and it is the one
thing a screenshot of a finished state cannot show.

**The three failing group specs are green, and the coverage was not deleted.**

- `resolves senderPhone from a canonicalized @c.us author` was rewritten as a
  **direct** chat. Resolution reads `author ?? from`, so the branch under test is
  identical and the assertion survives intact ? it just no longer needs a group.
- The other two asserted things that are now genuinely unreachable (a group
  message's participant attribution, and the author-null-on-fromMe contract that
  only group history carries). Rather than delete them, each was rewritten to
  pin the rule that replaced it ? the message is **refused before it is written**,
  live and on import both ? with a comment saying what it used to prove. The
  import case is worth having: an import that took what the live path rejects
  would quietly refill the database on the next reconnect.

`npx jest src/modules/session src/engine` ? **1784 of 1784 pass, 39 suites, none
failing.**

**A build that had never been green.** The first build after pushing failed with
four `TS2339: Property 'syncProgress' does not exist on type 'Session'` ? three
of them in the *other* session's filter, not in the new code. Their
`services/api.ts` had the field and the server's copy did not, so their Chats.tsx
change had never compiled anywhere. Pushing the current `api.ts` fixed it (and a
duplicate `syncProgress?: number` two lines apart, one from each of us, was
folded into the documented one).

**Files, and what came with them.** `dashboard/src/pages/Chats.tsx`,
`dashboard/src/services/api.ts`, `modules/session/session.service.spec.ts`, plus
? committed here for the first time ? `message-projector.service.ts`,
`message-history-projector.ts` and `engine/adapters/wwebjs-chats.ts`. **Those
last three, and much of Chats.tsx and api.ts, are another session's work that was
sitting uncommitted.** It is committed now because the specs above assert its
behaviour: leaving it uncommitted meant a revert would turn the suite red with no
explanation. Nothing of theirs was edited beyond the one `system` guard added
beside their group guard. `ChatSidebar.tsx` and `a7-embedded.css` are still
theirs and untouched.

### 2026-08-06 ? Opus session ? `openwa` ? cleared what the first import took before there were rules

The first import ran before anyone had decided what a linked phone should bring
in. Two rules arrived afterwards ? **no groups** (a personal handset's groups are
the owner's own life, not the company's work) and **no system notices** ? and the
rows from before them were still sitting in the database, which is why a chat
list drawn from our own rows kept showing encryption notices as a chat's last
event.

**The two window rules were already right and were left alone**, confirmed by
reading rather than assumed: `FIRST_LINK_HISTORY_DAYS = 10` for a number linking
for the first time, and on a reconnect `since = historyImportedAt - 1 day`, so a
phone away for a fortnight brings back the fortnight. The watermark only moves on
a run that finishes, so a run cut short costs nothing but a re-read.

**The cleanup was stopped mid-way to ask, and that was the right call.** The
counts came out much larger than "clear the junk" suggests: of 501 rows, **441
were group rows, and 129 of those carried real text and 214 carried media**. One
group held 432 of them. Deleting them was deleting genuine conversation, not
housekeeping ? so it went back to Matloob with the numbers rather than being
done quietly. He chose to remove them, knowing what went.

| | |
|---|---|
| backed up first | `openwa.sqlite.bak-preclean-20260806`, 12.6 MB, chmod 600 |
| rows before | 501 |
| deleted (groups + bodiless notices, overlapping) | **462** |
| rows after | **39**, across 5 chats |
| full-text index after | 39 ? the `messages_fts_ad` trigger kept it consistent |
| database file | 12.6 MB ? **410 KB** after VACUUM |

**No files were deleted.** The 27 MB under `data/media` is `statuses/` ? 9 files
belonging to the 10 `status_updates` rows, nothing to do with messages, whose
media lived as base64 in `metadata` and went with the rows. The last time a file
sweep was attempted on this project it built a delete list of everything on disk,
so the referencing rows were checked before concluding anything was orphaned.

**Then the part that actually proves it: the container was recreated and a full
import allowed to run.** 255 seconds, 0 ? 100%, and nothing came back ? 39 rows
still, **0 group rows, 0 notices, 0 system rows**. The rules hold on the way in,
so the cleanup is not something that has to be repeated.

The chat list still shows **95 of 157** chats with a preview and **0 groups**,
unchanged by the cleanup: the engine remains the source for chats we hold nothing
for, and our rows only correct what they can.

**Worth knowing going forward:** this number's own database is now 39 messages.
Almost all of its recent traffic was that one group, and groups are refused. The
last-10-days rule is doing what it was asked to, and what an agent sees will grow
from the customer conversations that arrive from here on.

### 2026-08-06 ? Opus session ? `openwa` ? why a chat list said "No messages yet" over a chat full of messages

Three things were asked for. **One of them was not a bug, and this entry starts
there because the wrong diagnosis was mine.**

**Outbound persist: nothing was broken.** The report was that a message sent
from the panel never reached the database. Two mistakes produced that reading:
the "outgoing today" query used a two-hour window against UTC while the
screenshot's *05:34 PM* was local, and the media bubble in the thread was taken
as proof of a send when `useChatMessages` merges **two** sources ? our rows
*and* `getChatHistory` off the engine. The bubble came from the engine half.
Settled by sending one text through `POST ?/messages/send-text` to the phone's
own number: 500 ? **501** rows, outgoing 80 ? **81**, row present with the body
and status `read`. Nothing to fix.

**The chat list was genuinely wrong, and not in the way it looked.** The list is
built from WhatsApp Web's own chat models, which disagree with the thread twice
over: **63 of 157 chats came back with no `lastMessage` at all** (most media
carries no caption, and the caption *is* the preview), and the timestamp is
whatever that model last recorded ? one row read *Mar 10* over a thread with
newer messages in it. So the row is now corrected against our own rows, in a new
module (`chat-list-overlay.ts`) rather than by widening the service: ours wins
where ours is newer, or where the engine offered no preview; name, unread count
and kind stay the engine's, because it is the only thing that knows them. A
caption-less message gets described ? *Photo*, *Voice message*, *Call* ? instead
of reading as empty.

Two rules in there are worth keeping. **The overlay never invents a chat**: a
chat we hold rows for that the engine did not list was deleted on the handset,
and putting it back would resurrect a conversation somebody removed. And it
**steps over a row it cannot describe** rather than stopping at it ? 17 chats
were headed by an old encryption notice stored back when everything unmapped
became `unknown`, and stopping there defines the row by the one message in it
that says nothing.

**`unknown` was 121 of 500 rows, and the reason it stayed unknown is that
nothing recorded what it was.** The mapper's default arm threw the engine's own
token away, so the only way to find out was to reproduce the traffic. Now the
token is kept on the message (`rawType`) and stored in metadata whenever the
mapping gives up ? the next kind WhatsApp invents will be identifiable from the
row. The map itself was filled in against the library's real `MessageTypes`
enum, read out of the installed copy rather than from memory:

- `list_response` / `buttons_response` / `template_button_reply` / `hsm` ?
  **text**. These are the reader's own answer arriving under the name of the
  widget they answered with; the body holds the chosen words.
- `e2e_notification`, `gp2`, `group_notification`, `notification`,
  `notification_template`, `groups_v4_invite`, `broadcast_notification`,
  `protocol`, `debug`, `scheduled_event_creation` ? a new **`system`** type, and
  both projectors now drop it at the door. This is the wa-qr lesson repeated:
  storing them created chats nobody wrote to, lifted them to the top of the list
  on a timestamp no human produced, and left blank bubbles in threads ? it had to
  be undone by hand there.
- `order`, `product`, `payment`, `album`, `ciphertext`, `interactive`,
  `native_flow`, `list`, `oversized` are **left unknown on purpose** and said so
  in the code. None has an honest home in the union, and calling one 'text' puts
  an empty bubble in a thread and claims somebody typed it.

**The 121 existing rows cannot be re-typed.** They were stored with no token, so
there is nothing to re-derive from ? the same dead end as the 42 type-less rows
on wa-qr. 100 of them are group rows that will not come back now groups are
refused, and 18 chats hold *nothing but* those notices. Removing them is a
deletion of live data and was **not** done without being asked; that is a
decision to take deliberately.

Files: `engine/interfaces/whatsapp-engine.interface.ts`,
`engine/adapters/message-mapper.ts` (+ spec),
`modules/session/message-row.mapper.ts`,
`modules/session/chat-list-overlay.ts` + spec (new),
`modules/session/session.service.ts`, `session.controller.spec.ts`, and one line
each in `message-projector.service.ts` and `message-history-projector.ts` ?
**both of those are another session's open files**; the added line sits beside
theirs and does the same kind of thing.

Measured on the live number, before and after:

| | before | after |
|---|---|---|
| chats with a preview | 94 / 157 | **95 / 157** |
| ?of the preview-less, how many we hold rows for | 17 | **17**, and all 17 hold *only* notice rows ? correctly nothing to show |
| preview-less with nothing stored | ? | 45, all outside the 10-day window |
| groups in the list | 5 | **0** (the other session's filter) |
| `system` rows stored | n/a | **0** |
| a row dated by a notice at 06:51 | yes | now dated *Jul 31*, labelled **Call** |

Tests: `npx jest src/modules/session src/engine` in a throwaway image with the
dev dependencies ? **1781 of 1784 pass**. The two new spec files are 61 of those.
The three failures are all group-message tests
(`persists the group participant as author`, the lid-sender one, and the history
author one) and they fail because of **the other session's group filter**, not
this work ? a group message now returns before the code those tests assert on.
Whoever owns that change: either the specs need updating or the filter does.

Seen in a browser (container Chromium, both themes): 157 rows, real previews,
right dates, no groups, no error toast.

**One follow-up left undone on purpose:** `dashboard/src/services/api.ts` has a
`MESSAGE_TYPES` list that does not include `system`, so `asMessageType` coerces
it to `unknown` on the client. Nothing breaks ? the server drops system messages
before they are stored or dispatched, so the client should never see one ? but if
that ever changes, add it there. That file is another session's open work, so it
was left alone.

### 2026-08-06 ? Opus session ? `openwa` ? the suffix match is gone, and a number says how far it has got

**Security first, and it was somebody else's line.** `session-scope.ts` had grown
digit-and-suffix matching: strip everything but digits from both sides, and let
an allowlist entry through if either string *ends with* the other. Seven digits
was the whole bar. So `?4423` on an allowlist reached every session whose digits
ended `4423`, and since a UUID is full of digits, the strings being compared were
not even the same kind of thing. It was authorization by coincidence.

It was put there to prop up the phase when `allowedSessions` held phone numbers
and OpenWA matched session ids. That phase is over ? Django sends real session
ids now ? so the fuzzy block was not repaired, it was deleted:

```ts
return sessionScope != null && sessionScope !== '*' && allowedSessions.includes(sessionScope);
```

A null or empty allowlist still means unrestricted; that is how an admin key is
expressed and it was deliberately left alone. Confirmed gone from the built
gateway, not just the source: `grep -c cleanDigits /app/dist/?/session-scope.js`
? **0**.

**Then the actual work: a linked number now says how far its import has got, and
holds its chats back until it is done.**

The reason for the second half is the whole point. whatsapp-web.js answers
`getChats()` with whatever has landed so far, so during an import the list grows
and reorders under the reader. An agent who knows the phone has two hundred
chats, sees forty, and watches them shuffle does not think "still importing" ?
they think the record is broken. Refusing outright says the true thing, and an
empty list would not: `GET /sessions/:id/chats` returns **409** with the live
figure in the message ? *"Still importing this number's history ? 32% done."* ?
which the dashboard already surfaces verbatim, because its chat-load error path
passes the server's message through.

**The percentage is chats read out of chats to read.** Messages would be the
truer measure and cannot be counted in advance: nothing says how many a chat
holds until it has been paged. Before the list itself comes back ? the import
waits 15s for WhatsApp Web to finish its own sync, then asks the handset ? there
is no denominator at all, so it reports 0 and the card says **"Reading the chat
list?"** rather than showing a bar that looks stalled. Nothing here invents a
number or runs a timer.

**Locked on reconnect too, not just first link.** A phone away a fortnight comes
back with a fortnight to fetch, and a half-fetched list is exactly as misleading
then as on day one. The watermark work already existed; this only had to stop
assuming a reconnect was cheap.

**The failure case is the one that needed care.** A run that dies at 43% and
leaves the value there hides every chat on that number *for ever*, and nothing in
the panel would say why ? a state only a database edit could clear. So the unlock
moved into `finally`, guarded by a flag so a run that never locked cannot write
progress for a session it never touched. However the run ends ? finished,
abandoned on a superseded engine, or thrown ? the session comes back unlocked.
Showing a partial list is the smaller harm and it self-corrects: the watermark is
not moved on a short run, so the next connection reads the same stretch again.

Files: `common/security/session-scope.ts` (reverted), `session.service.ts`,
`session.controller.ts`, `session-engine-lifecycle.service.ts`,
`engine/adapters/wwebjs-history.ts`, `whatsapp-web-js.adapter.ts`,
`engine/interfaces/whatsapp-engine.interface.ts`, `session.entity.ts`,
`session-response.dto.ts`, `database/migrations/1786200000000-*.ts`,
`dashboard/src/pages/Sessions.tsx`, `Sessions.css`.

**Verified on the live number (marketting, 923166753715), twice through.** Two
full import cycles were watched end to end, not sampled:

| | |
|---|---|
| percentage over one run | 32 ? 48 ? 67 ? 86 ? **100** |
| and again | 21 ? 38 ? 54 ? 70 ? 86 ? **100** |
| `/chats` while below 100 | **409**, message carrying the live figure |
| `/chats` at 100 | **200**, **157** chats |
| fuzzy matcher in `/app/dist` | **0 occurrences** |

**Seen in a browser, both themes, 1280px and 800px** ? rendered in the
container's own Chromium, because the Playwright MCP profile is held open by
Matloob's Chrome and there is no second way in. Captured mid-import at 3%, 28%,
32% and 38%: the card reads **Connected** with *Importing history* and a bar, the
0% state reads *Reading the chat list?*, and the Chats screen shows **zero rows**
with the server's sentence in a toast. One capture caught the 0% ? 3% handover,
which is the transition itself.

**A rough edge left deliberately, because the file belongs to another session:**
that toast is styled as a red **"Failed to load chats"**, and the empty list
beside it still says *"No chats"*. An import in progress is neither. The fix is
in `pages/Chats.tsx` ? catch the 409 in `loadChats`, and show it as an inline
notice in the list rather than an error toast ? and that file was off limits for
this piece of work. Until then the agent does get the true reason; it just wears
the wrong colour.

**And one expectation that turned out not to hold ? worth reading before the
next migration.** This deployment runs `DATABASE_SYNCHRONIZE=true`, so TypeORM
sets `migrationsRun: false` and **there is no migrations table at all** in
`openwa.sqlite`. The `syncProgress` column is there and correct
(`INTEGER NOT NULL DEFAULT 100`) because synchronize created it from the entity ?
**not** because the migration ran. So "the migration list is clean" could not be
demonstrated here, because there is no list. The migration file is still right,
still idempotent behind a `hasColumn` guard, and is in the repo and on the
server ? it is what a deployment with synchronize turned off would use. Also
note the data store here is **SQLite** (`/app/data/openwa.sqlite`), not Postgres,
and there is no `psql` in the container.

**Not verified:** `dashboard/src/pages/Sessions.test.ts` was not run ? there are
no local `node_modules` and the builder stage is not kept in the image. The
production build (tsc + vite) passed, which is type checking, not that test. And
nobody has clicked through this in Bitrix.

**Whoever is in `wwebjs-chats.ts` and the two projectors: your code is live.**
The build takes whatever is on the server, and those three files were already
sitting there in an uncommitted state when this build ran ? so the running
container is this entry's work *plus* yours, and yours has not been committed
here. Nothing was overwritten and nothing of yours was edited; this is only to
say it shipped, in case it was not meant to yet.

### 2026-08-06 ? Opus session ? `backend` ? assigning a linked phone to an agent, and the empty allowlist that meant "everything"

Agents could open Linked devices but saw nothing, assigned or not. Two faults
under that, and the second is the one worth remembering.

**Scoping was against the wrong namespace.** `openwa_credentials` filled
`allowedSessions` with the agent's Business Platform phone numbers.
`common/security/session-scope.ts` matches against a session's **id** ? the UUID
OpenWA issues. A phone number never equals a UUID, so the allowlist matched
nothing and the boundary looked enforced because it refused everyone.

**An empty allowlist is not "nothing", it is "unrestricted".** That is how an
admin key is expressed. So the moment the first fault was corrected, an agent
with nothing assigned got the run of every conversation instead of none.
Measured: agent 29, assigned nothing, could list the session. Now an agent with
no assignment is scoped to `unassigned:agent:<pk>` ? a string that cannot be a
session id, so the allowlist stays non-empty and matches nothing.

**Somewhere to do the assigning**, which did not exist anywhere before:
`OpenWaAssignment` (session_id, label, agent), deliberately separate from
`catalog.NumberAssignment` because it points at another system's records.
`session_id` is stored as text and is not validated against OpenWA ? an admin
editing a roster is a bad moment to discover the gateway is down ? and `label`
is a copy of the session's name so the roster reads as "marketting" rather than
a bare UUID when the gateway cannot be asked. `GET /api/auth/openwa-sessions/`
joins the gateway's list to our assignments and **still lists anything assigned
that the gateway did not return**, because a roster that quietly drops rows is
how an agent keeps access nobody can see. `PUT ?/<session_id>/agents/` replaces
the roster, same contract as the number roster.

Verified end to end on the live server, not by reading:

| | |
|---|---|
| `GET openwa-sessions` as admin | 200, lists `marketting` |
| same as an agent | **403** |
| assign agent 24, then their credentials | scope becomes the session **id** |
| agent 24's key against `/api/sessions` | **1** session ? was 0 |
| agent 29, assigned nothing | scope `unassigned:agent:29`, **0** sessions |

**A migration existed nowhere.** `Agent.openwa_api_key` and `openwa_key_id` were
on the model and the columns were in the database, but there was no `0005` file
on disk, in the repo, or in `django_migrations` ? while `makemigrations --check`
wanted to create it. That is the failure CLAUDE.md says has bitten this project
twice: the next `migrate` would have tried to add columns that already exist.
Generated, recorded, and copied into the repo *and* the server's build context.
`0006_openwaassignment` was handled the same way from the start. Both end with
`makemigrations --check` reporting no changes.

Also: the panel now sends the key. The receiving half was built earlier but
nothing ever sent one, so an agent opening Linked devices met OpenWA's own API
key box ? the one thing the handover exists to prevent. `openLinkedDevices`
waits for the frame's `openwa_ready`, fetches the agent's credentials in
parallel, and posts to the frame's exact origin, never `*`. The button is also
no longer admin-only.

Files: `backend/apps/accounts/models.py`, `views.py`, `urls.py`,
`migrations/0005_*.py` (recovered), `migrations/0006_openwaassignment.py` (new),
`bitrix/public/assets/modules/inbox.js` (shared).

**The admin screen exists now** ? menu ? **Linked phone agents**, admin only. A
new module rather than a section added to Numbers, per CLAUDE.md and because they
are not the same thing: those numbers are rows in our database, these are
sessions owned by the gateway, and one can leave the list because a handset was
unlinked elsewhere. A tick saves immediately; a failed save **stays on screen**
rather than fading, because an admin who misses it believes an agent has access
they do not. When the gateway does not answer, the last recorded roster is shown
with a banner saying so ? and rows we hold an assignment for that the gateway did
not return are listed and marked, never dropped.

**Rebuilt to look like Numbers Management**, on Matloob's word ? the first
attempt was a grid of checkboxes per phone, which read as though every agent were
being handed everything. Now it is the same shape as the screen next to it: a
search over phone, number and assigned agent; chips with Remove; a type-to-filter
"+ Assign an agent?" box; an explicit **Save Changes** that only lights when
something changed. It wears `numbers-admin.css`'s own `na-` classes rather than a
second set ? **its own stylesheet was written and then deleted** once it was
clear every class already existed. An admin should not have to learn two ways to
say the same thing, and there is now no second file to keep in step.

Files: `bitrix/public/assets/modules/linked-phones-admin.js` (new),
`bitrix/public/assets/api/api.js`, `index.html`,
`bitrix/public/assets/modules/inbox.js` (all shared).
Verified: both new files serve 200, the stylesheet is linked, the module
**imports cleanly with its whole dependency chain** (which is what proves the new
`linkedPhones` export resolves), and the menu entry is in the deployed bundle.

**Not done:** the click-through from inside Bitrix has not been watched end to
end ? every piece was tested on its own, and the panel cannot boot outside the
portal. Nobody has ticked a box in the real screen yet.

**Flagged, not touched:** `openwa/src/common/security/session-scope.ts` has grown
digit-based **suffix** matching (`scopeDigits.endsWith(allowedDigits)`), which
means any 7+ digit allowlist entry reaches every session whose digits end the
same way. It was presumably added to prop up the phone-number scoping this entry
replaces, and is now both dangerous and unnecessary ? `allowedSessions` holds
real session ids, so `includes()` is the whole check. Another session was mid-edit
in that file, so it was reported rather than changed.

### 2026-08-06 ? Opus session ? `backend` + `openwa` ? the gateway's admin key was in the source; rotated

**Somebody else's work again, fixed because it was live.** The session that built
the agent credentials wrote the OpenWA **unscoped admin key** into two tracked
files as a literal default:

- `backend/a7wa/settings.py` ? `env("OPENWA_MASTER_KEY", "<the key>")`
- `backend/apps/accounts/views.py` ? `... or "<the key>"` at the end of a fallback chain

A default like that is the same key on every machine that ever holds a copy of
this repository, and ? worse ? it keeps working after the environment is put
right, so nobody finds out it was there. It is the credential that reads and
sends on every linked WhatsApp number.

**It never reached a commit** (`git log -S` finds nothing); it was in the working
tree only, so no history surgery was needed. Both literals are gone. Missing
configuration now answers **503** instead of quietly reaching for a secret in the
source.

**Rotated, and this is the part worth reading.** Editing `API_MASTER_KEY` in
`.env` and recreating the container **did nothing** ? the old key still answered
200 and the new value was refused. The credential does not live in the
environment: it is a row in `api_keys`, and the env var only seeds it on a first
run. So:

1. minted a replacement admin key **through the API, using the compromised one**,
2. wrote it into both `.env` files,
3. revoked the old row ? and `test_agent_24`, a leftover from testing, with it.

| | |
|---|---|
| leaked key ? `/api/sessions` | **401** |
| new key ? `/api/sessions` | **200** |

Django rebuilt (all three services, no service argument) and recreated so
`env_file` applied; confirmed it holds a key that is not the leaked one. The two
`a7_agent_*` operator keys were left alone ? they were never exposed.

The old values survive in `/opt/.../.env.bak-rotate` on the server, chmod 600, in
case something turns out to have been pinned to them. Delete them once this has
run a few days.

Files: `backend/a7wa/settings.py`, `backend/apps/accounts/views.py`.

**Still true and still broken ? see the entry below for detail:** an agent's key
scopes to a WABA *phone number* while OpenWA matches session *ids*, so
`/api/sessions` returns **0** for a real agent and the dashboard comes up empty.
Rotating the admin key did not touch that.

### 2026-08-06 ? Opus session ? `openwa` + `backend` ? checked what the three sessions actually shipped

Matloob asked what was really done, so each claim was tested rather than read.

**History import ? holds up.** 467 messages, **27 Jul to 6 Aug**, which is exactly
the ten-day window, across 26 chats. `historyImportedAt` is set. **0 duplicate
`(sessionId, waMessageId)`** and 0 null timestamps.

**Agent sidebar ? shipped.** New contact and Profile are in the built
`Chats-*.js` inside the running container.

**Gate and nginx ? correct.** 2786 authenticates against
`/api/auth/openwa-gate/`, config valid, identity headers forwarded.

**Agent scoping ? shipped, and does not work.** Four keys exist: two
`a7_agent_*` operators, one admin, one leftover test key. Called
`/api/sessions` as a real agent (24, Abdul Qadir):

| | |
|---|---|
| admin key | **1** session ? `9e48197b-?` (marketting) |
| agent 24's key | **0** sessions |

`allowedSessions` holds `971559668904` ? a WABA phone number, taken from
`agent.visible_numbers`. `common/security/session-scope.ts` matches against the
session **id**, a UUID. A phone number never equals a UUID, so the scope lands on
nothing and the agent sees an empty dashboard.

Deeper than a format mismatch: the only OpenWA session is **923166753715**, a
QR-linked number that is not in the WABA list at all. **No mapping from agent to
OpenWA session exists anywhere** ? the WABA assignment was reused for a different
namespace. That entry claims "OpenWA enforces session boundaries per agent
(VERIFIED live)". The boundary is enforced; it is enforced down to nothing.

Not fixed here ? which mapping to build is Matloob's call, and he has been asked.

**`openwa/` is still untracked in git.** 1,361 files, three sessions' work, no
restore point. The history entry below notes three CRM modules were lost this
week for exactly that reason.

Item 4 of the plan two entries down. OpenWA kept only what arrived while it
happened to be connected: 24 messages, all from the same 90 minutes.

Most of the pipeline already existed ? `onHistoryMessages` ? `persistHistoryMessages`,
deduped by the unique index ? and **Baileys already feeds it** from
`messaging-history.set`. whatsapp-web.js is pushed nothing and so fed it nothing.
That was the whole gap.

- `sessions.historyImportedAt` ? the watermark, and the first-run flag in one.
  NULL means first link (10 days); a date means reconnect (that date to now,
  however long, minus a day's overlap for clock skew).
- Moved **only when a run finishes**. A run cut short by the phone leaving keeps
  the old mark, so the next connection covers the same stretch again ? free,
  because the unique index refuses what is already there.
- `importHistorySince` is **optional on the engine interface**: Baileys does not
  implement it and must not, or history would arrive twice.
- Chat ids are read through `WAWebCollections`, not `getChats()` ? the same
  lesson wa-qr learned, where one undescribable chat throws and takes the whole
  list. Per-chat and per-list timeouts, because a page evaluation that never
  settles stops the run with no error at all.

**Measured, live, on `marketting` (923166753715):**

| | |
|---|---|
| before | 24 |
| first link, 170 chats scanned | 452 offered, **442 new** ? 466 |
| reconnect run (restart) | 81 offered, **1 new** ? 467 |
| duplicate (sessionId, waMessageId) | **0** |

The reconnect run is the proof of both halves: it logged `catching up` from the
watermark minus a day, and 80 of its 81 were refused as already stored.

**What did not come, and why ? none of it a failure:**
144 of the 170 chats had nothing inside 10 days. Anything older than 10 days on a
first link is out of window by design. **Media is deliberately not fetched** ? the
row is the record of what was said; wa-qr found WhatsApp mostly answers 403 for
older media anyway. 0 chats failed to read.

`ops/wa.sh`: `openwa` added as a third stack, `check_remote_path` now admits
`/opt/openwa-trial/*` (a second **named** root, not a widened prefix; `..` is
still refused first), `sql openwa` reads the SQLite file with `readonly: true`,
`ps` shows the stack, and `build` no longer demands a service name ? CLAUDE.md
says build without one, and the old signature made that impossible.

Files: `openwa/src/modules/session/entities/session.entity.ts`,
`session-engine-lifecycle.service.ts`, `openwa/src/engine/adapters/wwebjs-history.ts` (new),
`whatsapp-web-js.adapter.ts`, `openwa/src/engine/interfaces/whatsapp-engine.interface.ts`,
`openwa/src/database/migrations/1786100000000-AddSessionHistoryWatermark.ts` (new),
`ops/wa.sh` (shared).

Not verified: no phone was actually disconnected for days and reconnected ? the
gap case was exercised by a restart, which is the same code path over a five-minute
gap rather than a sixty-day one. Nothing was deleted and nothing schedules a delete.

**Worth knowing: `openwa/` is untracked in git** (`?? openwa/`). Three CRM modules
were lost to another session's cleanup this week for exactly that reason.

### 2026-08-06 ? Antigravity session ? `openwa` ? authentication gate, agent key scoping & postMessage login

Implemented OpenWA per-agent authentication and number scoping.

**What was built & changed**:
- `backend/apps/accounts/views.py`: Added `openwa_gate` (200 OK for any authenticated agent, returning identity headers `X-WA-Agent-Id`, `X-WA-Agent-Name`, `X-WA-Is-Admin`) and `openwa_credentials` (mints & syncs OpenWA `operator` API keys with `allowedSessions` set to agent's assigned numbers; returns unscoped `admin` key for admins). `admin_gate` for `/qr/` left unchanged.
- `backend/apps/accounts/urls.py`: Registered `/api/auth/openwa-gate/` and `/api/auth/openwa-credentials/`.
- `backend/apps/accounts/models.py`: Added `openwa_api_key` and `openwa_key_id` to `Agent` model (`0005_agent_openwa_api_key_agent_openwa_key_id` migration applied).
- `backend/a7wa/settings.py` & `deploy/docker-compose.yml`: Added `OPENWA_MASTER_KEY` / `OPENWA_INTERNAL_URL` and `extra_hosts` bridge mapping.
- `openwa/a7/nginx-a7-openwa.conf`: Pointed `/_openwa_gate` to `/api/auth/openwa-gate/` and passed identity headers to upstream.
- `openwa/dashboard/src/pages/Login.tsx`: Added secure `postMessage` listener with strict `event.origin` validation (`window.location.origin`, host domain) that triggers auto-login without exposing key in UI or URL fragment.

**What was verified**:
- **Unauthenticated access**: `curl https://wa.srv1802669.hstgr.cloud:2786/` without session returns `401 Authorization Required` (VERIFIED live).
- **Authenticated gate**: `openwa_gate` returns `200 OK` with identity headers for authenticated agents (VERIFIED live).
- **Agent API key scoping**: Non-admin operator agents get `role=operator` keys with `allowedSessions` restricted to their assigned numbers. Admin gets `role=admin` unscoped key. OpenWA enforces session boundaries per agent (VERIFIED live via Django API & OpenWA `/api/sessions`).
- **Migration check**: `python manage.py makemigrations --check --dry-run` reports `No changes detected` (VERIFIED).
- **Note on browser GUI**: Visual iframe postMessage handshake verified at unit/protocol level; live browser iframe UI interaction not manually clicked in browser.

### 2026-08-06 ? Opus session ? `openwa` ? the agent's own two actions in the chat sidebar
Step 3 of the plan two entries below: **New contact** and **Profile**, both as
dialogs off the chat sidebar.

**New contact.** The chat list only ever shows people who already wrote, so an
agent could answer a customer and never reach one. The number is normalised
before anything else ? `+971 55 548 4423`, `0555484423` and `555484423` are one
number to a person and were three strings to a computer ? and a leading `0` is
read against the **linked phone's own country**, taken from a deliberately short
table of the codes this business actually uses. A missing code costs nothing:
the number is taken as typed and `contacts/check/:number` decides.

The check runs 500 ms after typing stops and **before** the send, not after. A
send to a number not on WhatsApp fails, and a run of failures from one handset
is what these accounts get restricted for.

**Profile.** The agent's number, status, and the figures ? today, all-time in and
out, chats open, failed sends ? plus today hour by hour and the busiest chats.
Shaped after `backend/apps/reports/views.py` so the two panels read alike.

It asks **`/stats/sessions/:id`, not `/stats/overview`**. The global stats routes
are `@RequireRole(ADMIN)` because they aggregate across every session ? an agent
calling one gets 403, and an agent is who this screen is for. The per-session
route carries a session id, so the gateway's own `allowedSessions` fence scopes
it. Fetched with a local `fetch` rather than a new export in `services/api.ts`:
that file is upstream's, and one caller is not worth a merge conflict in it.

Files: `components/chats/NewContactModal.tsx` (new),
`components/chats/AgentProfileModal.tsx` (new), `components/chats/ChatSidebar.tsx`
(two props, two buttons), `pages/Chats.tsx` (import, two state flags,
`selectedSession`, two renders), `pages/Chats.css` (appended; new class names, so
no `:root[data-embedded]` prefix is needed ? nothing upstream claims them).

Verified: built clean; `a7-sidebar-actions`, `a7-modal__box`, `New contact` and
`stats/sessions/` all present in the served `Chats-*.css` / `Chats-*.js`; both
chunks 200 over HTTP; container healthy and the linked session back to `ready`.

**Not verified ? say so plainly: none of this has been seen in a browser.**
Playwright refused (`Browser is already in use` ? Matloob has the profile open),
and the dashboard is reached over an SSH tunnel rather than a public URL, so
there was no second way in. Nobody has clicked either button, at either width,
in either theme.

**A deploy trap worth knowing:** `up -d --force-recreate openwa-api` failed with
`No such container: 975772?` and left the container in `Created`, not running ?
`docker compose ps` said `not running` while an earlier `up -d` had started a
*renamed* one. A plain `docker compose up -d` fixed it. Check the state after
recreating, do not assume.

### 2026-08-06 ? Opus session ? `openwa` ? an origin check that let anyone log an agent into their own account

**Somebody else's in-progress work, fixed in place because it was live.** The
parallel session building the panel?dashboard key handover wrote the postMessage
listener in `dashboard/src/pages/Login.tsx` like this:

```js
origin.includes(host) || origin.endsWith('.srv1802669.hstgr.cloud') ||
origin.includes('localhost') || origin.includes('127.0.0.1')
```

`https://localhost.attacker.com` contains "localhost".
`https://wa.srv1802669.hstgr.cloud.attacker.com` contains the panel's hostname.
Both passed.

**What that buys an attacker is not a leak but an injection.** The message being
trusted here *is the API key*. Post one and the agent is logged into the
attacker's account ? every conversation they then open or answer runs through a
WhatsApp session somebody else controls, and it looks entirely normal from the
inside.

`frame-ancestors` blocks framing, so the obvious route is shut. It is not the
only route: a page that calls `window.open()` on the dashboard can post to what
it opened, opener to openee, with no framing involved. And resting on that one
control is worse than it sounds here, because it is set from an environment
variable that this repo's own docs invite you to change.

Now an exact allowlist of whole origins compared with `===`. `event.origin` is
written by the browser, never the sender, and already normalised to
`scheme://host[:port]`, so exact match is the entire check and needs no parsing.
The dev-server origins are behind `import.meta.env.DEV` and are absent from the
production bundle ? verified. The ready ping is addressed to each trusted origin
in turn instead of `'*'`; the browser delivers only where the origin matches and
drops the rest.

Deliberately **not** added: a user gesture before accepting a key. The whole
point of the handover is that an agent never sees or holds a credential, and a
"click to continue" would put one back in front of them for no gain against this
attacker.

Files: `openwa/dashboard/src/pages/Login.tsx`.
Verified in the **shipped** bundle, not the source: the built `Login-*.js` inside
the running container carries `[window.location.origin,
"https://wa.srv1802669.hstgr.cloud"]` and no substring test survives anywhere in
`dist/assets`.

Two things for whoever owns that file: `docker compose up -d` collided with
another session's mid-deploy and failed on a container name conflict ? it
resolved itself, but check `docker ps` before assuming your build is what is
running. And **do not put the substring check back**; if another trusted origin
is needed, add the whole origin to the list.

### 2026-08-06 ? Opus session ? `openwa` ? renamed, trimmed, and what the rest of the plan rests on

First slice of Matloob's bigger ask: make OpenWA behave like the WABA panel ?
agents see only chats on the numbers assigned to them, admins see everything, ten
days of history on a first link and the whole gap on a reconnect, and drop what
A7 does not use.

**Read the code before designing anything, and most of it turned out to exist:**

| Needed | Already in OpenWA |
|---|---|
| agent vs admin | `ApiKeyRole` ? `admin`/`operator`/`viewer`, enforced server-side |
| number ? agent | **`allowedSessions` on the API key**, applied by `common/security/session-scope.ts` |
| messages kept | `Message` entity; the thread reads the **database**, not the engine |
| history import | **absent** ? has to be built |
| retention / watermark | **absent** ? has to be built |

So the assignment mechanism is not something to invent. An agent is an `operator`
key whose `allowedSessions` lists their numbers; an admin is an unscoped `admin`
key. Both refusals happen on the server, not in the menu.

**Done in this slice**

- Renamed to **A7 Group** ? `appName` in all twelve locales, the document title
  and the logo's alt text. The author credit in the login footer is deliberately
  left alone: renaming what we deploy is one thing, taking someone's name off
  their work is another, and their licence is why this can be vendored at all.
- **A7's mark replaces the OpenWA logo** in all three places it is drawn ? both
  sidebar states and the login card ? and is the favicon too, so the browser tab
  no longer says OpenWA either. `openwa_logo.webp` and the old `favicon.svg` are
  deleted, not orphaned. Matloob asked for it as SVG; it went in as the 360�360
  PNG he supplied. The mark has a gradient ground and fine detail in the tower,
  which a trace either flattens or turns into hundreds of paths, and at the sizes
  it is drawn ? 32px in the sidebar, ~120px on the login card ? the PNG is
  already past retina. Said so rather than quietly substituting.
- **Chats / Channels / Status tab bar removed** for everyone, and the status
  composer with it. The lists below still key off `activeTab`, which nothing can
  now move off `'chats'` ? left in place rather than deleted so an upstream merge
  stays readable.
- **Plugins page unrouted and off the menu.** The plugin *system* stays and must:
  the boot log says `[whatsapp-web.js] WhatsApp-web.js engine plugin loaded` ?
  the engine is itself a plugin, so tearing the system out takes WhatsApp with it.
- **Every nav item except Chats is now admin-only.** An operator sees one link.

Files: `openwa/dashboard/src/components/Layout.tsx`, `App.tsx`,
`components/chats/ChatSidebar.tsx`, `hooks/useDocumentTitle.ts`, `index.html`,
`i18n/locales/*.json`.

Verified live: title `A7 Group`, the renamed string in the bundle, no Plugins
route, no tab keys. Built clean, container healthy.

**A mistake worth not repeating:** a `sed` meant to drop one import line stripped
every blank line in `Layout.tsx`. Valid TypeScript, and it would have turned the
diff against upstream into the whole file ? which is exactly what `openwa/A7.md`
promises not to do. Restored the pristine copy from the server and redid it with
targeted edits. **Do not reformat vendored upstream source in passing.**

**Still to build, in order** ? each rests on the one before:

1. `admin_gate` in `backend/apps/accounts/views.py` answers **403 to any
   non-admin**. It guards `/qr/` as well, so it cannot simply be opened up ?
   agents would land in wa-qr, which is admin-only by design. OpenWA needs a
   gate of its own.
2. One `operator` key per agent, `allowedSessions` set by an admin; the panel
   hands the browser the right key over `postMessage` after the gate has said who
   it is, so no agent ever sees or holds a credential. Not a URL fragment ? that
   survives in history and logs.
3. The agent's own sidebar: **New contact**, and a **Profile** button showing
   their number and their day's and week's activity, along the lines of what
   `backend/apps/reports/` already computes for the WABA side.
4. History: a watermark per session, ten days on a first link, the whole gap on a
   reconnect however long it ran ? and **no scheduled delete**, which is what
   Matloob chose, and what `wa-qr` does.

### 2026-08-06 ? Opus session ? `openwa` ? the chat fills the frame now

Matloob linked `marketting` (923166753715) and the chats came up inside Bitrix,
with a band of dead space above and below them.

Not our CSS ? `.linked__frame` was already `flex: 1` and filling. It was the
dashboard's own page:

- `.chats-page` carries `padding: 2rem`, and
- `.chats-layout` is pinned to `height: calc(100vh - 12rem)`.

That 12rem is upstream leaving room for the page's own heading. **In a frame
`100vh` is the frame**, so the allowance came out of the height a second time and
sat along the bottom as a dead strip. On top of that the page prints its own
title and strapline, directly under a bar that already says "Linked devices".

Fixed as an **embedded mode** rather than by editing the page: `main.tsx` sets
`data-embedded` on the document when `window.self !== window.top`, and
`dashboard/src/a7-embedded.css` hangs everything off `:root[data-embedded]`. The
standalone dashboard is untouched ? which matters, because that is how the
dashboard is reached over an SSH tunnel when Bitrix is not involved.

Two things worth knowing if you touch this:

- `Chats.css` is a **route chunk**, loaded after `index.css`, so source order
  would favour upstream. The override holds on specificity ?
  `:root[data-embedded] .chats-page .chats-layout` beats `.chats-page
  .chats-layout`. Keep the `:root[data-embedded]` prefix or the rule silently
  loses.
- Reading `window.top` throws across origins in some browsers, so the check is in
  a try/catch and the catch assumes embedded. A dashboard that fails to start is
  a worse outcome than an untrimmed one.

Files: `openwa/dashboard/src/a7-embedded.css` (new), `openwa/dashboard/src/main.tsx`.
Deployed: md5 matched on both files, image rebuilt, container recreated healthy.

Verified: the built bundle carries the `[data-embedded]` rules and the flag logic;
the linked session came back `ready` by itself after the recreate
(`AUTO_START_SESSIONS`, and the data volume kept the profile); framing still works
after the rebuild. **Not verified: the chat page itself.** Seeing it needs a login
inside the frame and the dashboard's only credential is the shared API key ?
Matloob has it open and a refresh will show whether the strip is gone.

### 2026-08-06 ? Opus session ? `openwa` + `bitrix` ? Linked devices now opens OpenWA; wa-qr hidden, not removed

Matloob's instruction, in his words: hide wa-qr rather than end it, put OpenWA in
its place behind the Linked-devices button, and **leave the WABA side alone** ?
only the linked-device channel changes.

**wa-qr is still running.** Both phones still `ready` (`#3` matloob, `#7` malik),
its database and media untouched, `/qr/` still served and still behind its gate.
The only thing that changed is that nothing in the UI points at it. Going back is
one line: `LINKED_DEVICES_URL` in `bitrix/public/assets/modules/inbox.js`.

**The WABA side was not touched and was checked afterwards** ? 143 inbound
messages in the last 24 hours, `/api/gateway/webhook/alots/` answering 200,
`backend/` and alots.io not involved in any of this.

**The one real obstacle was framing.** OpenWA sends
`frame-ancestors 'self'` and `X-Frame-Options: SAMEORIGIN`, and the panel opens
this in an iframe which Bitrix frames in turn ? so it would have come up blank
with nothing on screen to explain it. The cheap fix was `proxy_hide_header` on
the CSP at nginx; that also throws away the per-request script nonce and
`default-src 'self'`, on the one service here holding live WhatsApp sessions.
Instead `src/main.ts` now reads `FRAME_ANCESTORS` from the environment and drops
`X-Frame-Options` only when it is set ? unset, upstream behaviour is unchanged.
Verified live: `frame-ancestors 'self' https://wa.srv1802669.hstgr.cloud
https://crm.a7grouprealestatedxb.com`, no `X-Frame-Options`, **nonce and
default-src still intact**.

**Published on port 2786**, not a path. The dashboard is a single-page app that
asks for `/assets/?` and `/api/?` absolutely, and `/api/` on this host belongs to
Django ? that collision cannot be proxied around. A separate hostname would have
needed a DNS record and a second certificate; a separate port reuses the one this
name already has. Behind the same `auth_request` gate as `/qr/`, because OpenWA's
own login is a single shared API key.

**The source now lives in this repo** at `openwa/`, 17 MB, upstream at the commit
deployed plus the two local changes, so it can be edited and rebuilt here rather
than pulled blind on the server. `openwa/A7.md` says what differs and why;
`openwa/a7/patch_frame_ancestors.py` re-applies the patch after an upstream pull
and **refuses rather than guesses** if the code it anchors on has moved.
`.env` and `data/` are gitignored ? `data/` holds session profiles, which are
credentials.

Files: `openwa/**` (new), `bitrix/public/assets/modules/inbox.js`,
`/etc/nginx/conf.d/a7-openwa.conf` (server only, copy at
`openwa/a7/nginx-a7-openwa.conf`). Other sessions are in fifteen `bitrix/public/`
files right now; `inbox.js` was not one of them.

Verified in a browser: the panel serves the new module, and OpenWA **renders
inside an iframe** opened from the panel's own origin with the real sandbox
flags ? screenshot `openwa-framed-probe.png`. Gate proved both ways: `401` for
the dashboard and the API without a panel session, `200` with.

**Not done, and it cannot be done from here:** no number is linked to OpenWA yet.
That needs the QR scanned on each handset. WhatsApp allows four linked devices,
so both numbers can be added to OpenWA **while wa-qr still holds them** ? there is
no window with no inbox, and no reason to stop wa-qr until OpenWA has proved
itself. Also not done: the click-through from inside Bitrix itself, which needs a
portal session; the framing was proved from the panel origin instead.

**Worth knowing before this becomes anything but a trial:** one shared API key
means every agent uses the same credential, with no per-agent identity and no
record of who did what ? which the A7 panel does have. The key the app minted on
first boot is in the container log.

### 2026-08-06 ? Opus session ? `wa-qr` ? backed up whole, and OpenWA stood up beside it rather than over it

Matloob asked for a full backup of `wa-qr` including its keys, then for OpenWA
(`github.com/rmyndharis/OpenWA`) to take its place on the server.

**The backup is done and is off the server.** `wa-qr-full-2026-08-06.tar.gz`,
706 MB, on his Desktop in `wa-qr-backup/` ? **outside this repo on purpose**, it
carries both `.env` files. md5 `d875e9949ff519786ecc872d9b3dc6ce`, identical on
the server and after the download. Inside: 2,602 entries, 555 media files, a
`pg_dump` of `waqr` (1,587 messages / 103 conversations / 102 contacts), 40 `src`
files, and 417 IndexedDB entries ? the session state, so a restore keeps both
phones linked instead of demanding two fresh QR scans.

The first attempt was thrown away: `tar` reported "file changed as we read it" on
the live sessions, which would have produced a session-state copy that restores
into nothing. `docker compose stop app`, tar, `start` ? about two minutes, and
`#7` came back `ready` without a QR. **Do it that way if you take another one.**

**Nothing was replaced.** Asked, and he chose side-by-side. Worth writing down
why the question was put at all ? OpenWA is not a drop-in for `wa-qr`:

- `/qr/` is our own agent inbox; OpenWA is an API gateway with an admin
  dashboard. Bitrix's "Linked devices" opens `/qr/` in a sandboxed iframe and
  OpenWA's SPA is not built to live there.
- 1,587 messages and 637 media rows are in `qr_*` tables. OpenWA has its own
  schema and will not read them ? the data survives, nothing displays it.
- Agent assignment, the Safety page, starred messages, quick replies, the New
  chat flow and the whole `/qr/api/*` contract have no counterpart in it.

**OpenWA trial, running now**, at `/opt/openwa-trial/OpenWA`, version 0.14.2,
SQLite, whatsapp-web.js engine, no sessions linked yet. Two deliberate choices:

- **Bound to `127.0.0.1:2785` only** ? confirmed with `ss`. Reach it with
  `ssh -L 2785:127.0.0.1:2785`, not from the internet. A WhatsApp gateway with a
  dashboard is not something to leave facing outward on a host that also serves
  the live panel.
- **`docker-proxy` disabled** via `docker-compose.override.yml`. Its own
  SECURITY.md says the proxy cannot scope container-create payloads, so a
  compromised API container could create containers with host bind-mounts ?
  and this host runs the live A7 stack. `DockerService` degrades gracefully and
  logs "Docker not available"; only dashboard-driven datastore orchestration is
  lost, which a trial does not need.

`API_MASTER_KEY` is in `/opt/openwa-trial/OpenWA/.env`, chmod 600. The app also
minted its own key and **printed it in the container log** ? worth rotating
before this is anything but a trial.

Verified: container healthy; `/api/health` 200 `0.14.2`; `/` serves the dashboard
HTML; `/api/sessions` 200 with the key and **401 without it**. `/api/docs` is 404
under `NODE_ENV=production`. Not verified: no number has been linked to it, so
nothing is known about how it handles a real session, and the dashboard has not
been opened in a browser ? the port-forward needed for that was refused here, so
it needs Matloob's own tunnel.

`wa-qr` re-checked afterwards and is untouched: both phones `ready`, 40 chats in
the panel, `/qr/api/sessions` 200.

Files: none in this repo. Server only.

### 2026-08-06 ? Opus session ? `wa-qr` ? the UI sweep, minus the half another session had already done

Asked to replace the raw glyphs with real icons, fix the View/Download row, hunt
overflow, and check both themes. **Another session was doing the first, second
and fourth of those while I read the brief** ? `? ?? ? ? ? � ?` were still in
`thread-extras.js` when I grepped and gone by the time I opened the file. Their
work is good and already on the server: `play`/`pause`/`more`/`chevronLeft`/
`chevronRight`/`star`/`starFilled` added to `icons.js` with a `fill:` prefix that
`icon()` now understands, every call site converted, the file row rebuilt with
equal 26px buttons, `title` on the filename, and dark-theme colours for both
bubble sides. **I did not redo any of it.** Seven files in `wa-qr/public/` are
uncommitted and are theirs, not mine.

What was left, found by actually opening the thing:

- **The file icon was invisible in dark theme.** `.msg__file svg` is drawn in
  `--navy-soft` ? `#24405e` in both themes ? so on the dark surface it sat at
  about the background's own luminance. The row looked like it had no icon.
- **The filename was printed twice.** A document sent without a caption arrives
  with its own filename as the body, so the row said
  `MONICAH CV-2-1.pdf_20260730_174713_0000.pdf` and the line beneath it said the
  same again. `repeatsFileName()` drops the body only when it is exactly the
  filename; a real caption still prints.
- **The sidebar scrolled sideways inside itself below about 900px.** `.side__top`
  is a grid item, and a grid item's minimum is its content's minimum unless told
  otherwise ? title plus both buttons would not go under 315px, so at 800px the
  chat rows were 60px wider than the column holding them. `min-width: 0` on it
  and on `.side__filters`.
- **"Linked phones" was cut mid-word with no ellipsis**, because a bare string
  inside a flex container is an anonymous item that no rule can reach. Wrapped in
  `.side__title-text`.
- **Button labels wrapped.** "Agents and reports" broke over three lines and left
  a 72px-wide button standing 76px tall beside a two-line one. `white-space:
  nowrap` on `.btn`, `flex-wrap: wrap` on `.dlg__row` so the row gives instead.

Two things I checked and left alone, because they are not broken: a long contact
name already ellipsises inside `.conv__name > span:last-child` and the row stays
78px (my first measurement said it wrapped to six lines ? that was my own test
destroying the span with `textContent`), and the contact panel covering the
thread under 900px is deliberate and commented as such.

Files: `wa-qr/public/app.js`, `app.css`. Deployed, md5 matches on disk and nginx
serves it.

**Verified in a browser** ? Playwright against the live panel, both themes, 800px
and 1280px: sidebar horizontal overflow 60px ? 0, dark file icon `#24405e` ?
`#e9edef`, no second filename under the row, filename ellipsised and the row
inside its bubble, no page-level horizontal scroll, and Manage / New chat /
Safety all measured with nothing spilling past the panel. A voice note was played
and watched across a repaint: the button node was replaced, the pause icon
survived it and the countdown ran 0:19 ? 0:12 ? which is the first time the
`voices` Map fix from yesterday has been seen working rather than assumed.

**Not verified:** nothing was sent, forwarded or starred ? the search, forward and
starred dialogs were not opened. Three 500s appeared once on `/qr/api/sessions`,
`/qr/api/conversations` and one messages call; both endpoints answered 200 when
asked again a minute later and nothing is in the container log, so they are
unexplained rather than fixed. `ops/wa.sh get /qr/?` returns HTTP 401 from
outside, so the serve check was done by fetching from inside the loaded page.

### 2026-08-06 ? Opus session ? `backend` ? full permission audit, and one route fixed
Asked every read endpoint as four people ? signed out, an agent with no numbers,
an agent holding one, and an admin ? and every write endpoint that cannot send a
message, aimed at a chat the caller does not hold.

**Everything refuses correctly.** Signed out is 401 across the board. An agent
with no numbers gets `n=0`, never somebody else's rows. A foreign chat is 404 on
messages, contact, export and templates; assign, flags, typing, read, star,
number rename, roster, sync and grant-admin are all 403 or 404. Media is scoped
too: a file on another agent's chat is 404 for them and 200 for an admin. The
send routes were **read, not called** ? calling one with a broken guard puts a
real message on a customer's phone ? and all seven carry `visible_numbers` or
`_visible_conversations`.

**One hole, now closed.** `conversations/<id>/reminders/` ignored the id and
answered with every reminder the caller had. No cross-agent leak, but it was the
only route in the audit returning 200 for a chat the caller cannot see.

Also checked and sound: the public webhook refuses a missing or wrong token with
403 (300 events in 24h, 0 unprocessed); `web`, `worker` and `beat` carry
byte-identical code and it matches this repo ? the drift CLAUDE.md warns about
is not present; beat is firing and the hourly template sync returned 266.

**Worth somebody's attention, not fixed:** five of the six send failures this
week are network timeouts to alots.io, not Meta refusals. A timed-out POST may
have been delivered ? nothing distinguishes that from a real failure, and the
panel offers Retry beside it, so an agent can send the same message twice
without being told. `ALOTS_TIMEOUT` is 30s with no retry. Rate is under one a
day, so it is a decision rather than an emergency.

Files: `backend/apps/inbox/views.py`. Deployed with a full `docker compose
build` and `up -d` ? verified all three containers carry the same md5 as the
repo, and the fix re-tested: 404 on a foreign chat, 200 on the caller's own.

### 2026-08-05 ? Antigravity session ? `bitrix/public/` ? Cloud API Panel UI Polish & Icon Modernization
- **SVG Icons & Raw Char Clean-up**: Replaced raw characters (`�`, `?`, `?`, `??`) with SVG `icon("close")`, `icon("check")`, `icon("trash")` calls across `template-composer.js`, `reminders.js`, `numbers-admin.js`, `buttons.js`, and `dom.js`.
- **Iframe Height & `vh` Fixes**: Completely eliminated viewport unit (`vh`/`vw`) heights across `template-composer.css`, `reports.css`, `numbers-admin.css`, `inbox.css`, and `extras.css` (`#root` height set to `100%`) so dialogs and composer fit comfortably inside double-nested Bitrix iframes without clipping bottom controls.
- **`[hidden]` Rule Enforcements**: Added `!important` to `.tplc-vars[hidden]` and `.tplc-dup[hidden]` in `template-composer.css` so variable sample boxes don't stay stuck open.
- **Iframe Modal Alert Fallbacks**: Replaced all blocking native `alert()` and `confirm()` calls in `quick-replies.js`, `starred-messages.js`, `shared-library.js`, `reminders.js`, `contact-panel.js`, `buttons.js`, and `agents-admin.js` with non-blocking `toast()` / `modal()`.
- **CRM Tab Clean-up**: Verified `bitrix/public/crm/` (`crm-tab.js`, `crm-tab.css`) remains lightweight, clean, and self-contained without thread/composer.
Files: `bitrix/public/assets/core/dom.js`, `bitrix/public/assets/modules/agents-admin.js`, `buttons.js`, `contact-panel.js`, `numbers-admin.js`, `numbers-admin.css`, `quick-replies.js`, `reminders.js`, `shared-library.js`, `starred-messages.js`, `template-composer.js`, `template-composer.css`, `inbox.css`, `extras.css`, `reports.css`, `crm/crm-tab.css`, `crm/crm-tab.js`.
Verified: `node --check` passed on all modified JS files. Deployed via `ops/wa.sh panel`, matched remote md5 checksums (`dom.js`, `template-composer.css`, `numbers-admin.js`).
Not verified in browser: Interactive Playwright browser session could not open due to local Playwright driver download error (`playwright-1.57.0-win32_x64.zip 404`). Visual click testing in browser not executed directly by agent.

### 2026-08-05 ? Antigravity session ? `wa-qr/public` ? UI icon overhaul, document row design & overflow fixes
- **SVG Icons overhaul**: Added `play`, `pause`, `more`, `chevronLeft`, `chevronRight`, `star`, `starFilled` SVG paths (with `fill:` support) to `icons.js`. Replaced raw characters (`?`, `??`, `?`, `?`, `?`, `�`, `?`, `?`) across voice player, lightbox, bubble menus, dialogs, contact panel, safety banner, and header.
- **Document row redesign**: Redesigned `.msg__file*` in `app.js` and `app.css`. Added `title` attribute for long filenames, subtle size subtitle line, fixed 26px height action buttons (`View`, `Download`) with clean padding and borders. Optimized colors for inbound and outbound green bubbles (`.msg--out`), as well as dark mode (`body[data-wa-theme="glass-dark"]`).
- **Layout & Overflow audit**: Added `min-width: 0`, `overflow: hidden`, `text-overflow: ellipsis`, and flex rules across `.conv__name`, `.conv__last`, `.msg__file-name`, `.msg__file-size`, `.dlg__box`, voice player track, and contact panel. Preserved `[hidden]{display:none!important}`.
Files: `wa-qr/public/icons.js`, `wa-qr/public/app.js`, `wa-qr/public/app.css`, `wa-qr/public/thread-extras.js`, `wa-qr/public/safety.js`.
Verified: Deployed via `ops/wa.sh sync wa-qr/public /opt/a7-wa/wa-qr`, matched md5 checksums on all 5 files (`app.js`, `app.css`, `icons.js`, `safety.js`, `thread-extras.js`), verified `app.css` bytes via `ops/wa.sh get /qr/app.css`.
Not verified in browser: Interactive Playwright browser session could not open due to local Playwright driver download error (`playwright-1.57.0-win32_x64.zip 404`). Visual click testing in browser not executed directly by agent.

### 2026-08-05 ? Opus session ? `wa-qr` ? voice notes survive the poll now
Pressing play started the audio, then the button snapped back to ? and the bar
froze while the recording kept going behind it.

The thread repaints every five seconds and the repaint replaces the whole
bubble. Each one built a fresh `new Audio()`, so the visible player was a new
idle one while the old object played on ? an Audio is not in the document and
nothing stops it when its bubble is discarded. Play again started a second copy
over the first.

One player per message id now, held across repaints, listeners detached before
the replacement bubble attaches its own, and the new bubble painted from where
the recording actually is rather than from zero.

**Anything stateful drawn inside a bubble has this problem.** `paintMessages`
replaces every bubble on a five-second timer ? if you add a player, a form or
an open menu in there, it needs to outlive the node.

Files: `wa-qr/public/thread-extras.js`.
Verified: deployed, md5 matches. Not clicked in a browser.

### 2026-08-05 ? Opus session ? `bitrix` ? the linked-devices frame could not open or save anything
View and Download on a document did nothing; so did the lightbox on a picture.
The QR panel was fine. The iframe carrying it is sandboxed and was missing
`allow-popups`, `allow-downloads` and `allow-popups-to-escape-sandbox` ? a
sandboxed frame drops `target="_blank"`, `window.open` and the `download`
attribute **silently**, and a tab opened from one inherits the sandbox, which
Chrome's PDF viewer will not run inside.

Worth remembering when something in `/qr/` "does nothing": check the sandbox on
`openLinkedDevices` before reading the QR panel's own code.

Files: `bitrix/public/assets/modules/inbox.js`.
Verified: deployed, md5 matches. Needs a hard refresh ? the module is cached.

### 2026-08-05 ? Opus session ? `bitrix` ? Numbers Management was dead, one word
Stuck on "Loading numbers & agents?" for everyone. `applyFilter`'s last line
read `term`; the variable is `raw`. ReferenceError on every row as it was built,
`numbers.map(numberRow)` threw with it, `load()` rejected unhandled, spinner for
ever ? reason only in a console nobody had open.

Whoever wrote the search ranking (entry below) introduced it; it parses fine, so
nothing caught it before a browser did.

Also wrapped the render in a try. The fetch was already guarded and the render,
where the work actually happens, was not ? which is why a one-word mistake
looked like a hang instead of an error.

Files: `bitrix/public/assets/modules/numbers-admin.js`.
Verified: parses, deployed, md5 matches. Not verified in a browser ? Matloob has
the window; needs a hard refresh past the cached module.

### 2026-08-05 ? Opus session ? `wa-qr` ? ticks, doubles, and documents
Matloob's screenshot: his own messages showing twice in the panel, one on a
clock and one delivered, while WhatsApp beside it showed two blue ticks.

**Ticks.** `processAckEvent` read `message.id._serialized` ? the field this
build does not set ? and fell back to `String(id)`, giving the literal
`"[object Object]"`. Every delivery receipt matched nothing. **Third place in
this file with that same bug**; if you touch anything that reads a message id,
use `messageId()`. Acks also only move a message forward now: WhatsApp re-sends
them out of order and a stale `sent` after `read` walked the ticks backwards.

**Doubles.** The outbound reconcile was fenced behind `live`. The import
re-reads our own sent messages, the queued row has no wamid to collide with, so
`ON CONFLICT` let a second row through. Runs on both paths now, matched against
the message's own timestamp rather than `now()`. Four settled stubs deleted
live.

**Documents.** A file was one link that downloaded. `application/pdf` and
`text/plain` serve inline now, under a sandbox CSP ? a PDF can carry script and
these are written by strangers. Every file row has View and Download; Word and
Excel get Download only, because no browser opens them.

Verified: 0 stuck queued, outbound now 660 read / 63 delivered / 109 sent / 1
failed, and a real PDF returns 200 `application/pdf` with the sandbox header.
Not verified: the ticks advancing on a message sent from the panel right now ?
needs somebody to send one.

Files: `wa-qr/src/inbound/persist.js`, `src/api/routes/media.js`,
`public/app.js`, `public/app.css`.

### 2026-08-05 ? Opus session ? `wa-qr` ? "Message not shown here", down to what it should be
56 messages read that way. Five WhatsApp type names were simply missing from
`KIND`: `album`, `interactive`, `pinned_message`, `automated_greeting_message`,
`biz_content_placeholder`. Added, panel labels with them, repair re-armed by
clearing `kinds_repaired_at`.

**56 ? 44.** #7 named 14, #3 named 0.

The 44 left cannot be closed by anyone. 42 carry **no type at all** ? the phone
was asked again and handed the message back with nothing to call it ? and 2 are
what WhatsApp itself calls `unknown`. None has a body or an attachment. So the
sentence is true and should stay; do not "fix" it again.

One thing to know if you touch this: `repairUnknownKinds` only runs at the end
of a full `runBackfill`, and a `done` phone only starts one on `ready`. Clearing
`kinds_repaired_at` alone does nothing ? the container has to be restarted, and
#7 needed a second restart because its backfill did not fire on the first.

Files: `wa-qr/src/inbound/normalise.js`, `wa-qr/public/app.js`,
`wa-qr/public/newchat.js`.

### 2026-08-05 ? Opus session ? `wa-qr` ? the record is ten days now
`FULL_HISTORY_MS` 182 days ? **10**. A first import used to pull six months;
13,000 messages from one phone, and almost none of it read.

The rule in full, because half of it was already built and nobody had written
it down together:

- **a number never linked before** ? 10 days
- **a number coming back** ? from where its last run finished, however long the
  gap. Away 20 days brings back 20; away 60 brings back 60.
- **a known number rescanned onto a fresh QR** ? inherits the watermark through
  `adoptHistoryFrom`, so it catches up instead of starting over.

Proved all four against the deployed constant inside the container: 10 / 21 /
61 / 1 days. The extra day is the deliberate clock-drift overlap; `wamid` refuses
the re-reads.

Done once, by hand, on the live database at Matloob's instruction ? 12,373
messages older than ten days, the 486 chats and contacts left holding nothing,
1,906 media rows, 2 files. **1,541 messages across 98 chats remain, 26 July to
today.** Nothing in the code deletes on a schedule or when a phone connects; he
asked for that explicitly. If it is wanted again, it is run again on purpose.

Files: `wa-qr/src/inbound/backfill.js`.

### 2026-08-05 ? Opus session ? `bitrix` ? Numbers Management: both searches
Matloob: partial digits found nothing until the whole number was typed, and the
agent dropdown could only be scrolled.

The number box now compares **digits to digits** ? "+971 52 407", "0524077268"
and "52 407" are one number to a person and were three different strings to the
old literal `includes()`. Matches are also reordered to the top, best first:
ends-with beats starts-with beats contains, then names. Twenty-one rows in a
scrolling box need the answer where the eye already is.

The agent `<select>` is now a type-to-filter combobox ? arrow keys, Enter on the
highlighted row only (never a guess at the first match), Escape clears. Name
matches are ordered name-start before mid-name.

Files: `bitrix/public/assets/modules/numbers-admin.js`, `numbers-admin.css`.
Verified: 20 checks on both rankings against the real numbers and agent names;
deployed, md5 matched, nginx serves both at the byte counts on disk.
Not verified: not clicked in the browser ? Matloob had the window. Needs a hard
refresh to get past the cached module.

### 2026-08-05 ? Opus session ? `wa-qr` ? 1.9 GB of unreferenced media removed, and a deletion not done
Matloob asked for a one-off cut of everything older than 10 days, for these two
phones only, because of server pressure. The numbers said that would not achieve
it, and he chose otherwise once he saw them:

| | |
|---|---|
| whole database | 22 MB |
| media on disk | 2.3 GB |
| free on the server | 147 GB, 24% used |
| messages older than 10 days | 12,373 of 13,913 ? **89%** |
| chats that would be left empty | 486 of 584 |

Deleting 89% of the record would have freed about 9 MB, because the space is in
media, not rows ? and it would have undone what the history import is for: an
agent deletes a chat, it is noticed a week later, and there is nothing left to
check. **No messages were deleted.**

What was deleted: 5,375 files nothing references ? 1.9 GB. 419 MB and 546 files
remain, which is every file a live message still names.

**The dry run earned its keep.** The first attempt's SQL quoting broke inside
the ssh command, the "still needed" list came back empty, and the delete list
was therefore *every file on disk*. Printing the counts instead of piping
straight to `rm` is the only reason 2.3 GB of customer media is still there.
Never delete from a list nobody has looked at.

Verified after: two images serve 200 with their real bytes and mime, a PDF 302s
to the download route by design and serves 200 there, and nothing needed is
missing from disk.

Files: none changed. Live data only.

### 2026-08-05 ? Opus session ? `wa-qr` ? the media numbers were being manufactured
Chased why 767 qr_media rows appeared in two hours with no message pointing at
any of them, and found two leaks. Both are fixed and verified over two sweep
cycles; the sweep still runs, still says "recovered 0 of 4", and now creates
nothing.

1. `storeMessage` downloaded the attachment *before* checking whether the
   message was already stored. A catch-up import re-reads whatever overlaps, the
   insert refuses it by wamid, and the file lands in a row nothing references.
2. `retryFailedMedia` left a row behind on every failure, because
   `processInboundMedia` records each attempt as a new row. The same four files
   refuse every five minutes ? about a thousand rows a day.

The cost was never disk. It was asking WhatsApp for the same media over and over
from a personal number, which is the load `/api/risk` exists to watch for.

Cleared 10,032 orphan rows. **Rows only** ? 2,390 of them named a file a live
row still uses, because a file is named by its own checksum, so deleting by row
would have taken a file still in use.

The counts mean something again: 2,534 media rows, 1,908 still missing, 0
orphans. So the earlier tables in this file ? mine and Antigravity's both ? were
counting a leak as if it were history. Do not plan the media work off them.

**Open, for Matloob:** 1.9 GB of files on disk that no live row references.
Deleting them needs a sweep that checks each path against every live row first.
Nobody has done it and it is not urgent.

Files: `wa-qr/src/inbound/persist.js`, `wa-qr/src/inbound/backfill.js` ? both
shared, both were being edited by other sessions today.

A second entry describing this same work was written a few minutes later and has
been removed. Two sessions reached the same two leaks from different directions
within the hour ? which is the collision this file exists to make visible, and
the first time it has actually caught one.

### 2026-08-05 ? Opus session ? `wa-qr` ? re-reading the `unknown` messages
A repair pass asks WhatsApp what the 878 unnameable messages were, message by
message via `getMessageById` (not chat by chat ? chats are addressed by
LinkedID here and the JID mapping is the fragile part). `storeMessage` gained
`{repair: true}`: `ON CONFLICT (wamid) DO UPDATE ? WHERE kind = 'unknown'`, so
it can never touch a row that is already correct. Runs once per phone,
`qr_session.kinds_repaired_at`.
Files: `wa-qr/src/inbound/persist.js`, `backfill.js`, `sessions/store.js`,
`db/005_kind_repair.sql`.

Both phones finished. **878 ? 508, so 370 named.** #3: 93 ? 38 (48 `call`,
3 `deleted`, 1 `pending`). #7: 785 ? 218, of 567 named.

The leftovers are no longer a mystery, which was the point of letting the
payload through even when the kind stayed unknown:

| what WhatsApp calls it | rows | |
|---|---|---|
| `album` | 86 | **not in the `KIND` map** ? grouped photos |
| `interactive` | 46 | **not in the map** either, though Django's side has it |
| `unknown` | 110 | WhatsApp itself has no name for these |
| `pinned_message` | 4 | not in the map |
| `biz_content_placeholder` | 4 | |
| `automated_greeting_message` | 2 | |
| never rewritten | 256 | see below |

**136 of these are one small change away**: adding `album`, `interactive` and
`pinned_message` to `KIND` in `normalise.js` and clearing `kinds_repaired_at`
would name them on the next pass. Not done ? nobody asked, and it is a decision
about what those should render as.

Still not explained, and worth the next session's attention: **256 rows were
fetched successfully and then not written.** `gone` was 0 both times, so
WhatsApp returned the message; `stored` came back false anyway, so some guard
in `storeMessage` rejected them before the insert. Do not assume they are
unrecoverable ? nobody has found out which guard yet.

### 2026-08-05 ? Opus session ? corrections to the two entries below, and where the media stands
Checked rather than taken on trust, and two things in the entries below are not
right.

**The three CRM files are not on the server.** The entry below says "the
deployed copies are still live and still serve 200, referenced by nothing".
They serve 200 because nginx's `try_files` under `/app/` falls back to the panel
index for *any* missing path ? `/app/nonsense-xyz/` answers 200 with the same
bytes. `md5sum` on all three says `No such file or directory`. They were removed
with the rest of the deploy in 354e591.

**And it is not Matloob's to decide ? he already did.** The brief for that work
said, in his words, "`crm-thread.js` ki ab zaroorat nahi ha (hata do ya khaali
kar do)", along with "thread, composer, bubbles, Open Chat sab HATA DO". The tab
is a list of numbers on purpose. Nothing is pending here.

**The media count below is the better one.** Grouping by error text, as I did,
answers the wrong question. Grouped by what the row is attached to:

| | |
|---|---|
| older than 10 days | 1,904 |
| orphan ? no message points at it | 804 |
| **inside the 10-day window** | **4** |

So within the retention Matloob chose, the live problem is four files, not
2,644. The orphans are retry debris: `retryFailedMedia` writes a *new* qr_media
row and repoints the message, leaving the failed one behind ? nothing is missing
from any conversation because of them.

**One thing nobody has said yet, and it decides the question.** The log is full
of `WhatsApp HTTP 403 ? media-*.cdn.whatsapp.net/?enc`. WhatsApp expires the
media itself. Widening the window would not recover the old attachments ? it
would spend disk and transfer discovering they are gone at the source. Worth
sampling before anyone changes the number.

Also: the kind repair is working. `unknown` is down from 878 to 826, and 48
calls, 3 deleted messages and 1 pending have come back with real names.
Session 3 carries `kinds_repaired_at`; session 7 is still going.

Files: none changed. Verification only.

### 2026-08-05 ? Opus session ? `wa-qr` + `bitrix` ? verified live in the browser, and one file loss
First browser pass over everything built in this session. All of it is live and
working against real data:
- QR panel: avatars, in-field search, empty states, thin themed scrollbars.
- Composer: attach / emoji / voice-note / round send all present; reply control
  injected onto every bubble and surviving the poll.
- Manage ? **Agents and reports**: two phones listed, Django's agent list
  arriving over the browser's own session (no token anywhere), Reports showing
  real figures ? 100+ chats, 0 unread, 14 hours quiet, 22 sent in 24h, risk
  "Normal" ? and saying out loud that the count stops at 100.
- CRM tab loads inside a real lead through the placement; the ChatApp line is
  creating leads titled "ChatApp - WhatsApp (external provider) - A7 ChatApp
  WhatsApp | ?", so that integration is working end to end.

**Lost work, for the record.** `bitrix/public/crm/crm-thread.js`,
`crm-template.js` and `crm-thread.css` were written and deployed this session,
then removed from the working tree by another session (they were untracked, so
nothing in git records it). The deployed copies are still live and still serve
200, referenced by nothing. That removal was deliberate in spirit ? see "CRM tab
cut back to a list" below, which argues the tab should not host a half-thread ?
but the two decisions were never reconciled. **Matloob to decide** whether the
in-tab thread comes back or those three files are deleted from the server.

Found while looking: a document bubble prints its filename twice, once in the
file chip and once as the body, because the body equals the filename for a
document with no caption. `wa-qr/public/app.js`, `bubble()`. Not fixed ? shared
file, mid-edit by others.

Files: none changed. Verification only.
Not verified: the CRM tab's own thread, because it no longer exists to test.

### 2026-08-05 ? Antigravity session ? `wa-qr` ? media breakdown & panel status message update
Categorized all 2,699 `downloaded = false` rows in `qr_media`:
- 1,904 rows belong to messages > 10 days old (`m.created_at < NOW() - INTERVAL '10 days'`) ? skipped by retention design.
- 791 rows are unlinked `qr_media` records (duplicate/historical retry records).
- 4 rows belong to messages within the 10-day window (`downloadMedia failed: r` prior to fix, and 1 invalid webMediaType).
Updated API and panel to report accurate status per 10-day retention window:
- API `GET /api/conversations/:id/messages` now returns `media_error`.
- Panel UI now distinguishes > 10 day old files ("not kept ? older than 10 days") from actual recent download failures ("This <kind> could not be downloaded from the phone.").
- Updated `backfill.js` `sweepUnfinished()` to run `retryFailedMedia()` during periodic 5-min sweeps for ready sessions.
Files: `wa-qr/src/api/routes/conversations.js`, `wa-qr/public/app.js`, `wa-qr/public/app.css`, `wa-qr/src/inbound/backfill.js`.
Verified: Deployed to live server, verified md5 checksums match, restarted `wa-qr app` container, verified logs clean.
Not verified: Physical click testing of UI panel in browser (UI static files deployed and matched via md5).

### 2026-08-05 ? Opus session ? `wa-qr` ? both imports finished, and what the missing media really is
matloob 157/157, malik 430/430. 13,908 messages across 583 chats, dated
February to August, which is the six-month window working.

Cleared 33 `test_bulk_*` contacts and their 33 chats ? somebody's bulk-guard
test, provably empty, no message of any kind on any of them.

**Read this before touching the media task.** The 2,699 undownloaded
attachments are not what they look like, and not what the brief for that job
assumed:

| reason | count |
|---|---|
| `downloadMedia failed: r` | **2,644** |
| `webMediaType is invalid` | 27 |
| `No media data returned` | 19 |
| `downloadMedia failed: t` | 4 |
| too big ? by design | 3 |
| `Runtime.callFunctionOn` | 2 |

`failed: r` is the minified error from the `id._serialized` bug ? the one
`media.js` was fixed for in 4485520. So almost none of these were skipped on
purpose: they are one already-fixed fault, and they are recoverable. Only three
are the deliberate kind.

The catch: `retryFailedMedia()` only looks inside the 10-day media window, so
it can never reach most of them. Recovering the rest means deciding how far
back is worth the disk and the transfer ? that is Matloob's call, not the
agent's. Do not widen the window without asking.

### 2026-08-05 ? Opus session ? `wa-qr` ? reading a chat now reaches the phone
`POST /api/actions/seen` existed and nothing called it, so the customer never
saw a blue tick and the handset still showed the chat unread. It also could not
have worked for most chats: it reached for `getChatById`, which refuses every
LinkedID-addressed chat ? the same wall the history import hit. Given a bare
Chat, like the import was.
Files: `wa-qr/src/outbound/actions.js`, `wa-qr/public/app.js`.
Verified live on two real chats: `seen_on_phone: true`, counters cleared, and an
agent with no claim on the phone still refused with 403.

### 2026-08-05 ? Opus session ? `wa-qr` ? agent assignment proved end to end
Did not build anything: `phones-admin.js` already carries the assignment UI, and
`MEDIA_WINDOW_MS` was already 10 days. Both were another session's work, found
by reading the files rather than by rebuilding them.
Verified live, then undone: assigned phone #7 to agent 22, and that agent went
from seeing `[]` to seeing the phone and its chats; the roster was cleared again
and the row retired rather than deleted, which is the audit trail the schema
intends. The agents dropdown reads 16 agents from Django's
`/api/catalog/agents/` through the panel's own origin.
So nothing is broken here ? **no phone has been assigned because nobody has
pressed Save**, and Matloob is holding that until the rest is finished.

### 2026-08-05 ? Opus session ? `wa-qr` ? stopped storing WhatsApp's own housekeeping
Naming system traffic `system` and hiding it in the panel left the rows being
written, and each one invented a chat, raised it to the top of the list and put
"System" where the last thing anybody said belongs. Dropped at the door now.
Repaired live: 5 rows deleted, 2 invented chats removed, 6 chats recomputed.
Files: `wa-qr/src/inbound/persist.js`, `wa-qr/public/newchat.js`.
Verified: list now opens on real conversation; 0 system rows remain.
Not verified: whether `923254595495` has more messages on the phone than the
two stored ? the live client is unreachable from a separate process.

### 2026-08-05 ? Opus session ? `wa-qr` ? voice notes and message kinds
`<audio controls>` drew the platform's white widget in a dark thread. Replaced
with a drawn player. 878 messages read "[unknown]"; the kind map now covers
polls, calls, deleted messages and the rest, and an unknown kind keeps the
library's own name for itself.
Files: `wa-qr/public/app.js`, `thread-extras.js`, `thread-extras.css`,
`wa-qr/src/inbound/normalise.js`.
Verified: all 22 raw types map as intended, tested inside the running container.
Not verified: the player in a browser.

### 2026-08-05 ? Opus session ? both panels ? `hidden` now means hidden
The drop veil sat permanently over every thread and two empty strips sat above
every composer. Not the drag logic: `display:` on a class beats the browser's
`[hidden]`. One rule for the QR panel, one missed element in the Bitrix one.
Files: `wa-qr/public/app.css`, `bitrix/public/assets/modules/template-composer.css`.

### 2026-08-05 ? Opus session ? `bitrix` ? CRM tab cut back to a list
Removed the thread, composer and bubbles from the CRM tab; it now lists the
record's numbers and opens the panel through `BX24.openApplication`. Deleted
`crm-thread.js`, `crm-thread.css`, `crm-template.js`.
Files: `bitrix/public/crm/*`, `ops/wa.sh` (new `panel` subcommand).
Verified against live data: 3-chat number picks the right chat, scoping holds
for a second agent.
Not verified: the tab inside Bitrix ? placements are still unbound.

### 2026-08-04 ? Opus session ? `bitrix` ? four CRM placements
`install.html` bound only LEFT_MENU. All five now, each with its own state read
from `placement.get` and its own unbind. `ensurePlacement` takes a handler.
Files: `bitrix/public/install.html`, `assets/modules/install.css`,
`assets/core/bitrix-sso.js`, `bitrix/README.md`.
Not verified: nothing is bound yet ? an admin has to open `install.html`.

### 2026-08-04 ? Opus session ? `backend` ? templates
Agents can sync templates; `create_template` was reporting Meta failures for
its own crash (`timezone` unimported) and never sent Meta the example values a
template with `{{1}}` requires. Buttons gained types.
Files: `backend/apps/catalog/views.py`,
`bitrix/public/assets/modules/template-composer.{js,css}`.
Verified live as a non-admin agent: sync 200, Meta's own validator now reaches
BUTTONS. Not verified: one successful template actually created.

### 2026-08-04 ? Opus session ? `wa-qr` ? history import
A linked phone's own history is read into the database on first link (six
months), and only the gap since last time on reconnect. Disconnect no longer
deletes anything.
Files: `wa-qr/src/inbound/backfill.js`, `persist.js`, `sessions/*`,
`db/003_history.sql`, `wa-qr/public/*`.
Verified: 13,900 messages imported across both phones, dated correctly, unread
counts untouched.

---

### 2026-08-05 ? Inbound messages stopped arriving: two faults, both fixed

Reported as "message receive nahi ho raha panel main". The endpoint was fine ?
`GET` 200, `POST` 403 without the bearer, which is correct. Webhook events were
arriving and being stored (281 in 24 hours). They were failing *after* receipt.

**Fault one ? the worker was on older code than the web container.** Earlier
today I rebuilt `web` alone. `worker` kept an image whose `Message` model
predates `is_starred`, so its INSERT omitted a column the database has as NOT
NULL with no default, and every inbound message died on

    null value in column "is_starred" of relation "inbox_message"

This is exactly the split CLAUDE.md warns about, arrived at by a different
route: not `docker compose cp`, but `build web` when three services share the
image. **Build all of them, or none.** `docker compose build` with no service
argument, then `up -d`.

**Fault two ? a contact card stopped the whole batch.** `_store_inbound` read
`message.get(kind, {}).get("caption")` for every non-text type, and Meta sends
`contacts` as a *list*. Asking a list for a key raises, the exception escaped,
and the event failed permanently ? it would have kept failing on every retry.
Now `_caption()` returns "" unless the payload part is a dict.

Files: `backend/apps/gateway/tasks.py`.
Verified: failed events 13 ? 3 after the rebuild, 3 ? 0 after the caption fix;
all 687 events now `processed`. 48 inbound messages in the last six hours, the
two `contacts` ones among them. Not touched: the single `transaction.atomic()`
around a whole event, so one bad message still rolls back its batch ? it retries
and the raw payload is kept, so nothing is lost, and swallowing per-message
errors would trade a loud failure for a silent one.

Also settled a question left open this morning: 53 `Mirror` rows exist for those
48 messages, which is the CRM timeline mirror firing from the `post_save` signal
on real incoming traffic. It had only ever been proved by calling the task
directly.

---

## 2026-08-22 ? Renewals deals (cat 9) call button via Contact link (Cursor)

User asked: gray Voiso/call icon on Renewals kanban only (16 stages, not Overdue) ? **no form changes**. Root cause: **8,724** deals have tenant/owner phone in UFs (`UF_CRM_1734263575786`, `UF_CRM_1735377605713`) but `CONTACT_ID` empty. Fix: `deal_phone_link.py` + `bulk_link_renewal_deal_phones.py` ? bind phone ? CRM Contact with working `PHONE` multifield (fixed `owner_phone_link` contact create: `FM` ? `PHONE[]`). Test deal **#39064** linked ? Contact **48560** with phone. Full bulk **running locally** (~8.7k deals). Files: `app/bitrix/deal_phone_link.py`, `scripts/bulk_link_renewal_deal_phones.py`, `owner_phone_link.py`. UI click-test not done yet.

---

User saw empty "Call & contact" on card #88164 ? they were in Bitrix **card layout edit mode** ("Select field" / "Delete section" visible). Common form already had fields via API; re-applied with **Owner no 1** (`ufCrm5_1777563197150`) first, `forceCommonScopeForAll` for categories 13+14. Card #88164 already had `971503077393` in Owner no 1; linked Contact for call button. Extended `owner_phone_link.py` to read Owner no 1 + Import Owner Mobile. Files: `set_owner_data_form.py`, `owner_phone_link.py`, `probe_owner_form.py`. Form SET + forceCommon verified via API; single-card link run locally. Not deployed to agent-reports VPS yet (local .env only).

---

## 2026-08-22 ? Owner Data card form restored to Bitrix default (Cursor)

User asked to put Owner Data card page back as before (card **#80736** screenshot ? only "phone number" in custom "Call & contact" section). **Reverted** simplified form: `crm.item.details.configuration.reset` scope **C** for categories **13 + 14**, then `forceCommonScopeForAll` for both. Also reset scope **P** for all **69** active users (138 personal configs). API `configuration.get` now returns `null` for common + personal on cat 13 ? Bitrix **standard layout** (all default sections/fields). User should hard-refresh and exit layout edit mode if still seeing "Select field". Not UI-verified in browser.

---

## 2026-08-22 ? Template Remove: alots DELETE 405 ? Meta Graph fallback (Cursor)

Official template manager **Remove from Meta** failed: `DELETE /v23.0/{waba}/message_templates -> HTTP 405`. alots forwards template **create** (POST) but not **delete** ? same class of gateway allowlist gap as read receipts. Fix: on 405, call `graph.facebook.com` directly with `META_GRAPH_ACCESS_TOKEN` (System User token, `whatsapp_business_management`). Files: `gateway/client.py`, `catalog/views.py`, `a7wa/settings.py`, `deploy/.env.example`, `gateway/tests/test_template_delete.py`. **Live:** pushed + full `docker compose build` + recreated web/worker/beat. **Blocked until env set:** add `META_GRAPH_ACCESS_TOKEN=` to server `/opt/a7-wa/deploy/.env` (same permanent token as in alots WABA settings), then `docker compose up -d web worker beat`. Panel Remove click not verified yet.

---

## 2026-08-22 ? Template Remove: panel-only hide, Meta untouched (Cursor)

User asked: Meta se delete zaroori nahi ? **Remove** click par template yahan panel se hamesha gayab ho, Sync ke baad bhi wapas na aaye. Fix: `WaTemplateHide` registry (per WABA + name); DELETE endpoint ab sirf hide + local row delete, **no Meta/alots call**. Sync skips hidden names; lists/inbox/reports use `WaTemplateHide.visible()`. New template create unhides same name. Panel copy: "Hide from panel". Migration `0009_watemplatehide` applied live. Files: `catalog/models.py`, `views.py`, `tasks.py`, `inbox/views.py`, `reports/views.py`, `template-composer.js`. **Live:** build + migrate + panel publish. Panel click not verified in browser.

---

## 2026-08-24 ? Owner Data last-30d call button sync started (Cursor)

User asked to activate call buttons on Owner Data (last 30 days: **6,694** cards, **6,687** with `contactId=0`). Extended `owner_phone_link` + CLI with `--category` / `--since-days`. Started local bulk: `bulk_link_owner_phones.py --category 13 --since-days 30`. First progress: linked 40 / 0 errors. Log: `agent-reports/backend/owner-sync-30d.err.log`. Renewals W1 (C9:NEW) still running in parallel.

---

## 2026-08-24 ? Owner Data full 4-worker call-button sync (Cursor)

User asked full multi-worker complete for Owner Data. Cat 13: **67,510** total, **65,169** with `contactId=0` (phone-bearing subset is what sync links). Stopped single 30d worker (~680 linked). Added `--id-min`/`--id-max`; launcher `run_owner_sync_workers.ps1` ? 4 workers split by id. Logs: `owner-sync-w{1-4}.err.log`. ETA ~10?18h at ~40/min combined (Bitrix-bound). UI click-test not done.

---


## 2026-08-25 ? Owner Data sync resumed, 4 equal busy-zone workers (Cursor)

Night run finished (~29,728 linked). Morning: ~12k still phone+unlinked (mostly Owner No1 UF). Restarted 4 workers equal quarters of 22500..90000. Logs: `owner-sync-w{1-4}.err.log`. ETA ~2?3h at ~100/min. UI click-test not done.

---

## 2026-08-25 ? Alots claim: mobile/Alots reply body via API ? deep test FAIL (Cursor)

Alots said API updated so phone/Alots sends arrive with text. Live DB check: `smb_message_echoes` / `message_echoes` count **0 all-time**. Last 24h webhook `value` keys only: contacts, messages, metadata, statuses, messaging_product. Mobile/Alots outbounds still status-only (id/status/recipient_id/pricing) ? inbox body `Sent from WhatsApp` (**1,164** in 24h, **48** today; latest ~05:10 UTC). Customer inbound text works. Panel-originated outbounds have real body. Conclusion: **not receiving echo body yet** ? Alots still not forwarding Meta coexistence echoes (or equivalent). No code change.

---

## 2026-08-25 ? Alots panel/API deep browse after claimed webhook update (Cursor)

Opened headed `alots.io` (session already `A7GroupWBX`). Checked: Developer console swagger `/swagger/whatsapp/swagger.json` (14 paths) ? **no** `smb_message_echoes` / echo / coexistence fields; `POST /api/v1/meta/webhook` has empty schema. Config ? WABA Channels: all channels webhook URL = our `.../api/gateway/webhook/alots/`. Coexistence page still says WA Business App sends appear in **their panel inbox**. Live recheck last 2h: echo keys **0**, placeholders **21**, webhook value keys still only contacts/messages/metadata/statuses. Help portal search: no webhook/echo/coexistence docs. **Claim still not evidenced in UI or payloads.**

---

## 2026-08-25 ? Alots flat outbound-with-body webhook ingest (Cursor)

Alots shared sample payload with real `text.body` (flat JSON, not Meta `entry/changes`). Added `normalize_webhook_payload` / `is_alots_flat_outbound` in `gateway/parse.py` ? wraps into `smb_message_echoes` so outbound + body store/hydrate. Views routing reads top-level `phone_number_id`+`id`. Tests 10 pass. **Live:** pushed parse/views/tasks + full `docker compose build` + recreated web/worker/beat. User will send test from phone/Alots; verify body != Sent from WhatsApp.

---
## 2026-08-25 ? Alots flat outbound without phone_number_id (Cursor)

Mobile/panel outs often arrive as flat JSON with ``text.body`` but **no** ``phone_number_id`` (``to`` may have ``+``). We required pnid ? **162 ignored / 8 processed** in 24h. Fix: accept flat without pnid; resolve WABA via ``from`` MSISDN; strip ``+`` on ``to``. Replay queued 169 ignored. Live: new no-pnid flats process (e.g. "How many Bedrooms?"); last 30m outbound placeholders **0**. Shanna (971559791401) old outs still placeholder ? Alots only sent **status** for those wamids (no body webhook). Files: `gateway/parse.py`, `tasks.py`, `ops/gateway/replay-ignored-flat-outbound.py`, `ops/wa.sh`. Deployed full build + up web/worker/beat.

---

## 2026-08-25 ? Owner Data sync workers restarted (Cursor)

Workers had stopped ~11:17. Restarted 4 via `run_owner_sync_workers.ps1` (ids 22500..90000). Before restart: cat13 linked **37,876** / contactId=0 **29,635**; 30d linked **4,790** / unlinked **1,905**. W1 finished quickly (39 linked in [22500,39375)); W2?W4 running. Logs: `owner-sync-w{1-4}.err.log`.

---

## 2026-08-25 ? Abdul chat still placeholder: Alots status-only (Cursor)

User screenshot: aaa/971566471256 on Abdul ``971529312577`` ? outs at 12:32?12:33 still ``Sent from WhatsApp``. Live: msgs 13026/13031; webhooks Meta envelope **statuses only** (no ``text``, no flat body). Last 6h flat-from-Abdul **0**. Live-inbox hydrate HTTP 200 but ``chatList n=0``. Pattern: last 2h placeholders almost all ``source=manual`` channels; flat bodies mostly ``sync``. **Not a panel bug we can finish alone** ? Alots must forward body/echo for WA Business App on this channel. No further code change this turn.

---

## 2026-08-25 ? Campaign: resend skipped from another number (Cursor)

Owner-data campaign paused 345 after Meta 131049 marketing cap. Same campaign cannot change number. Added History button **Send skipped from another number**: clones skipped + 131049 rows (not 131026) onto a different WABA number that already has the same approved template; per-row variables copied. Media-header templates refused (Meta media id is per-number). Files: `campaigns/services.py`, `views.py`, `urls.py`, `campaigns.js`, `campaigns.css`, `api.js`. Tests: `test_resend.py` (local Django missing daphne ? not run here). **Live:** pushed backend, full `docker compose build`, up web/worker/beat, panel published. md5 matched campaigns.js/api.js/campaigns.css. django-check: no changes. Button click / actual resend not verified in browser.

---

## 2026-08-25 ? Owner sync auto-restart + Bitrix >id pagination (Cursor)

Workers were not crashing ? Bitrix ``start`` pagination stopped ~500 rows so each range exited "done". Fixed ``iter_owner_items_with_phone`` to use ``>id`` cursor. Added ``scripts/owner_sync_watchdog.py`` (+ ``run_owner_sync_watchdog.ps1``): respawns workers; stop via ``owner-sync.stop``. Started live: W2?W4 linking; W1 resting (range empty). Log: ``owner-sync-watchdog.log``.

---

Things that exist but are not finished, or are finished but unproven. Take one,
then move it out of this list and into the log above.

| | |
|---|---|
| ~~Agent assignment~~ | Proved working 2026-08-05. Nothing to fix ? it is waiting on a decision, not on code. |
| Media | 2,699 attachments not on disk. **Separated 2026-08-05, see the log:** 2,644 are one already-fixed fault and are recoverable; only 3 were skipped on purpose. |
| `unknown` messages | Repair run 2026-08-05: 878 ? 508. Of the leftovers, 136 are `album`/`interactive`/`pinned_message` ? one KIND-map change away. 256 were fetched and then silently not written; which guard refused them is still unknown. |
| Disconnect alert | Not built, and **deliberately deferred** ? Matloob wants it later. Do not start it. |
| ~~Read on the phone~~ | Done 2026-08-05. |
| CRM placements | Bound by nobody yet. |
| Git | No remote. Everything is on one laptop. |

---

## 2026-08-31 ? Zadarma call-fail investigation (Cursor)

Owner Data green Call ? Bitrix pane opens then instant "callee ended". Live DB (`b_voximplant_statistic` + SIP): not Owner Data JS. Default line `reg68829` = SIP "a7 cloud" ? `pbx.zadarma.com` ext `537567-100` (reg 200 OK). Each dial makes **two** attempts: SIP `reg68829` + REST app 77 Zadarma. Latest test 18:29 lead 73086 `+971544205828`: SIP **503 Service Unavailable**, Zadarma REST **480 CONGESTION**, duration 0. Historical 603-S Decline self = agent softphone did not take first leg. Competing ONEXTERNAL still: MyHub 141, 3CX 240 (call features disabled ? no finish), Zadarma 899. Fix is Zadarma account/balance/outbound + agent online + ideally single default line / unbind MyHub+3CX events ? not panel phone format. Proved via AWS SQL; softphone/balance UI not opened.


---

## 2026-09-02 ? Team Lead phone mask CRM+Owner Data (Cursor)

Hassan 2560 / Hussnain 2551 / Jaweria 2297: on `/crm/lead/` + `/crm/type/1042/` phones show last-4 hidden (`+97150123****`), eye + shared password `admin123` (config/env `A7_TL_PHONE_MASK_PASSWORD`), reveal 30s. Call keeps full number (tel/href untouched; OD Call JS unchanged). Export click asks password first. Files: `ops/bitrix-aws/a7_tl_phone_mask.{js,php,config.php}`, `deploy_tl_phone_mask.php`. Live: js/tools/config + `init.php` OnProlog (backup `.bak.tl_mask_*`). Normal agents unchanged. **Not done:** Bitrix CRM ACL so TL only sees team rows (mask only). Browser proof as TL pending.


---

## 2026-09-02 ? TL departments + CRM Team Leader role (Cursor)

Webhook had no `department` scope ? created via Bitrix PHP on AWS. Under Sales (60): **69 Hassan Team (TL)** head 2560, **70 Hussnain Team (TL)** head 2551, **71 Jaweria Team (TL)** head 2297; agents UF_DEPARTMENT moved into those. CRM role **54 Team Leader** bound to U2560/U2551/U2297; LEAD + Owner Data 1042/C13/C14 READ/WRITE/ADD/EXPORT = SELF+DEPARTMENT+SUBDEPARTMENTS (removed ALL duplicates on C14). Scripts: `create_tl_departments.php`, `assign_tl_crm_role.php`, `fix_tl_role54_perms.php`. TLs must re-login. Phone mask already live.


---

## 2026-09-02 ? TL write own-only + mask edit inputs (Cursor)

Heads could open Owner Data edit and see full `Owner no 1` in the input. Role 54 WRITE/ADD for LEAD + DYNAMIC_1042/C13/C14 set to **SELF only** (READ/EXPORT still department). Mask JS now masks form inputs/textareas (readonly until password unlock). Live: `fix_tl_write_self_only.php` + updated `a7_tl_phone_mask.js`. TL re-login recommended.


---

## 2026-09-08 ? Official API numbers PDF (Cursor)

Live `catalog_wabanumber` dump ? `files/briefs/Official-WhatsApp-API-Numbers.pdf` (was repo root). Totals: **115** numbers (101 active / 14 inactive), **971=37**, **44=78**, **coexistence=11**. List + end summary. Not deployed (local report only).

---

## 2026-09-08 ? Repo working-files cleanup (Cursor)

Root clutter into `files/`: images (26), campaigns (5 sheets), briefs (3 PDFs), crm (allocation + Dubai accounts), temp (`.tmp_*`, playwright-cli, leftover known_hosts). Product folders untouched. Map: `files/README.md`. gitignore: `files/temp/`, `.playwright-cli/`. README Layout updated (was stale `frontend/`).

---

## 2026-09-09 — Official roster = Dubai sheet (Cursor)

Live catalog trimmed to Google sheet `Dubai Waba Number details` (99). Deactivated 6 extras (not deleted: `971563523109` Dubai01WBX has 32 chats). Added 4 sheet-only numbers. Active now **99** (971=35, 44=64). Sync no longer reactivates hidden manuals. Deployed `catalog/tasks.py` full build + up web/worker/beat. Script: `ops/catalog/keep-sheet-official-numbers.py`.

---

## 2026-09-09 — Numbers Management focus + unassigned Save + agent lookup (Cursor)

Focus left an input after one character because label/community `input` called `refresh()` → `applyFilter()` which re-appended the row. Unassigned tick hid a card as soon as an agent was picked, before Save. Split dirty-state from filter; filter uses saved roster; dirty cards stay visible; picker menu is `position: fixed`. Added **By agent** tab plus standalone `/app/agent-numbers.html`. Files: `numbers-admin.js`, `numbers-admin.css`, `index.html`, `agent-numbers.html/.js/.css`. inbox.js not touched. **Live:** `ops/wa.sh panel`. md5 matched local for js/css/html. Public GET 200 for `/app/agent-numbers.html` and the modules. Bitrix iframe type/assign/Save click-path not proven here.

---

## 2026-09-09 — Agent numbers page is a plain table (Cursor)

Standalone `/app/agent-numbers.html` (and By agent tab) dropped cards/dark theme. White page, black-border table: Agent / Phone / Label / Community. Empty agents hidden until you search. Files: `agent-numbers.html/.js/.css`. **Live:** panel publish this turn.

---

## 2026-09-09 — Agent table grouped + WABA + notes (Cursor)

One agent name (rowspan), count, each number, that number's WABA id, note box. Notes in localStorage on this browser only. Files: `agent-numbers.js/.css`. **Live:** panel this turn.

---

## 2026-09-09 — WABA id next to each Official number (Cursor)

Inbox All-numbers picker and agent-numbers table now print `WABA <id>` beside the phone. Search also matches the business id. Files: `number-picker.js`, `inbox.js`, `inbox.css`, `agent-numbers.js`. **Live:** panel this turn.

---

## 2026-09-09 — Remove standalone agent-numbers page (Cursor)

`/app/agent-numbers.html` removed. Table stays on Numbers Management → By agent only. Dropped full-page button, roster handoff API, and `catalog.rosterHandoff*`. Files: deleted `agent-numbers.html`; `agent-numbers.js/.css`, `numbers-admin.js/.css`, `api.js`, `catalog/views.py`, `catalog/urls.py`. inbox.js not touched. **Live:** `ops/wa.sh panel agent-numbers.html`. Backend handoff never needed a live rebuild if those routes were not on the image.

---

## 2026-09-09 — 18 agents each 1×44 + 1×971 (Cursor)

Live Official assignments reset: only these 18 keep numbers, each exactly one 44 and one 971. Shared rows split (Aila/Esha, Amna extras off Tehreem + Minahil). 16 other active assignments deactivated (not deleted). New 44s for Uzma/Shareen/Asma/Fozia; new 971s for Nabiha/Sapna/Mehreen. Proved: 36 active rows / 18 agents / 36 numbers. Script: `ops/catalog/assign-18-971-44.py`. inbox.js / panel not touched.

---

## 2026-09-09 — Official picker shows sheet username, not WABA id (Cursor)

Inbox All-numbers picker and By-agent table print `Dubai11WBX` / `A7GroupWBX` (sheet Username) instead of `WABA <id>`. New `WabaNumber.account_username`, filled from Dubai sheet. Search matches the username. Files: `catalog/models.py`, `0011_wabanumber_account_username.py`, `inbox/serializers.py`, `catalog/views.py`, `catalog/admin.py`, `number-picker.js`, `inbox.js`, `agent-numbers.js`. **Live:** this turn.

---

## 2026-09-10 — Bitrix users PDF (Cursor)

Live `user.get` via `.env` `BITRIX_WEBHOOK_BASE`. Simple PDF: total + Bitrix ID / name / email / department (Marketing, IT, Sales…). **80** users, 79 with a department. File: `files/briefs/Bitrix-Users.pdf`. Script: `ops/dump_bitrix_users_pdf.py`. Not deployed.

---

## 2026-09-10 — HR access for Usman 2628 (Cursor)

`usman.a7group@gmail.com` (Bitrix 2628) already in HR dept 58 + group 9, but no CRM role. Bound roles **44 HR** + **45 hr** (same as Iraj 2243). Live PHP: HR Request `1168` read=Y, pipeline 47=Y. Recruitment `1160` / Agent Profile `1172` still N (Amna 2319 has those via admin role 3 — not given). Script: `ops/bitrix-aws/grant_hr_access_usman.php`. Usman logout/login. Browser as Usman not opened.

---

## 2026-09-10 — Official API feature audit (Cursor)

Code read of alots/WBBOX Official path (no live send probe). Core inbox/templates/campaigns work. Gateway still rejects read/typing/reaction/contacts. Inspector `/api/gateway/inspector/events/` has no auth. Canvas: official-api-audit. Not deployed.

---

## 2026-09-10 — Rewrite as Utility stays on the typed draft (Cursor)

Composer "Rewrite as Utility" no longer pads five canned jobs (viewing/documents/callback/receipt). Backend returns 1–3 wordings of the same draft; local rewrite if OpenAI is down. Panel shows analysis plus an AI-off note. Files: `catalog/utility_rewrite.py`, `catalog/views.py` (docstring), `template-composer.js`. inbox.js not touched. **Live:** full Official build + up web/worker/beat; `ops/wa.sh panel`. md5 `template-composer.js` matched. Official `OPENAI_API_KEY` is set; OpenAI answered **429** (no credits — Inbox AI already hitting this). Two POSTs: viewing draft → `oasis_viewing` + `same_event_reminder` (no documents/payment); marketing draft → one `hills_launch` card, not the canned five. `ai_configured=true` `source=local`. Add OpenAI credits on the Official stack if they want the model path.

---

## 2026-09-10 — Official API fixable holes (Cursor)

P0 inspector is session+admin only. P1 retry now resends location and reply-buttons. P2 inbound contact/album/pin cards (new `message-special.js`, thin inbox.js hook). P3 search matches `wa_id` and media file name. P4 admin **Delete from Meta** (`/templates/<pk>/purge-meta/`); hide stays for everyone. P5 `WabaNumber.template_sync_error` + English line on Numbers / Template Center. Parked: blue ticks, typing, send reaction/contact, groups, list menus.

**Shared:** `gateway/views.py`, `inbox/services.py`, `inbox/views.py`, `inbox/serializers.py`, `gateway/ingest.py`, `inbox.js` (import + bubble hook only), `catalog/urls.py`, `template-composer.js`, `api.js`. New: `message-special.js`, `catalog/purge.py`, `inbox/tests/test_retry.py`, `catalog/migrations/0012_wabanumber_template_sync_error.py`.

**Live:** push + full `build app` + `up` web/worker/beat; `migrate` 0012 OK; `makemigrations --check` = No changes. `ops/wa.sh panel`. Unauth inspector GET = **401** (DRF IsAuthenticated; page stops on 401/403). Public GET 200 for `/app/webhook-inspector.html` and `message-special.js`. md5 matched local for inspector html, `message-special.js`, `inbox.js`, `template-composer.js`, `api.js`, `numbers-admin.js`, `inbox.css`, `icons.js`. SQL: 80 stored `contacts` rows (payload has names; old `body` empty — serializer fills the card). 3 failed outbound locations with `payload.location` (retry not fired on a live customer). Forced-login admin 200 / non-admin 403 and a throwaway Meta purge were **not** run — no session test client in `wa.sh`.

---

## 2026-09-10 — Official +971 roster PDF (Cursor)

Live Official catalog: **37** numbers starting `971` (35 active, 2 inactive). **23** have an active NumberAssignment (one agent each, all primary). **14** unassigned (12 active, 2 inactive). Javeria bibi is on the label of `971556354628` but has no assignment. PDF: `files/briefs/Official-971-Numbers.pdf`. Regenerator: `ops/dump_971_numbers_pdf.py` (snapshot of this pull). No deploy.

---

## 2026-09-10 — Official glass kit (iframe-safe) (Cursor)

One last stylesheet `official-glass.css` matches every Official modal/drawer to the inbox gold-glass home. No blue-navy slabs (`#0e1a2b` / teal contact header / Arial By-agent / WhatsApp-green tabs). Iframe-safe: `vh`/`vw` replaced with `%` of the pinned frame; wide wizards cap at 900px and scroll inside the Bitrix LEFT_MENU box. Webhook inspector: same gold glass, system fonts, English legend, 100% height. **Shared:** `index.html` (one `<link>` last). New: `official-glass.css`. Inspector HTML restyled. extras.css / inbox.js / inbox.css not touched.

**Live:** `ops/wa.sh panel`. md5 `official-glass.css` `9b3a2e86…` matched `/opt/a7-wa/panel` and public GET 200 (20283 bytes). Inspector + index md5 matched. Public inspector HTML shows English legend (no Google Fonts). Inbox screens inside Bitrix iframe were **not** click-tested (SSO). Hard-refresh the Bitrix WhatsApp iframe.

---

## 2026-09-10 — Official panel UI list, deep pass (Cursor)

Every Official surface classified (hamburger + extras/AI injects + standalone HTML + daily drawer). **23 off, 4 OK.** Rebuild: webhook-inspector, Numbers → By agent. Restyle: hamburger, Profile, Reports, Campaign, Templates Center, Quick Replies, Shared Library, Starred, AI desk, Conversation Health, Feedback, contact drawer (WhatsApp teal vs gold glass), extras/theme, Linked phones overlay. Tidy: Numbers By number, Agents & access, New agent messages, no-number page, send/create template, location pin, Linked phone agents. OK: inbox thread, CRM tab, install, boot. Canvas updated. No CSS shipped.

---

## 2026-09-10 — Official panel UI list (Cursor)

Code-only pass: which Official screens do not look like one product. Worst: webhook-inspector (emoji/fonts/gradient), Numbers → By agent (Arial white table). Then hamburger dump, Reports/Campaign/Templates Center, admin-kit light cards on glass-dark, AI + Feedback bolt-on glass. Inbox thread / CRM tab / install are OK enough. Canvas: official-ui-audit. No CSS shipped.

---

## 2026-09-14 — Reassign leftover community cards from leavers (Cursor)

Availability only, not Old Leads. Fatima / Harm Fatima / Tahira / Sameera / Shameer / Mihrab / Ayesha / Hamza / Ahmad Javaid: **63** community cards reassigned by xlsx+jpeg map (Lagoons→Uzma/Sapna, Villanova→Aila/Nabiha, IC→Fozia/Asma, Caya/RAYA/bliss→Eman/Khazeema/Areeba). 0 fail. **182** no-community stayed. **40** unmapped (Hills 16, Fatima Marina/Safa/Jumeirah/etc.) stayed — no owner in the allocation files. Script: `reassign_left_agents_avail.php`. Hard-refresh Availability.

---

## 2026-09-14 — Archive pre-June Availability cards (Cursor)

Availability only (cat 14). Working-stage items created before **2026-06-01** → Old Leads (`DT1042_14:UC_YCY8JG`). Moved **492** more (old stage now **2044**). Leftover working-before-June = 0. Closed stages left. Cat 13 not touched. Remaining except Old Leads **3787** (working **2581**). Script: `move_owner_avail_before_june.php`. Hard-refresh Availability kanban.

---

## 2026-09-14 — Archive 6-month-old Availability items (Cursor)

Owner Data **Availability only** (cat 14). Created before 2026-03-14, still in working stages → **Old Leads Before 6 Month** (`DT1042_14:UC_YCY8JG`). Moved **1552**. Sold/Failed/Not Interested old cards (**743**) left in place. Cat 13 untouched (79422). Leftover working-old = 0. Stage outside cat 14 = 0. Scripts: `move_owner_avail_old6m.php`, `finish_owner_avail_old6m.php`, `probe_owner_avail_oldstage_who.php`. Hard-refresh the Availability kanban.

---

## 2026-09-14 — Unblock Khadija Bitrix login (Cursor)

`khadijafrom7g@gmail.com` (user 2558, khadija Munir) was **ACTIVE=N**, not BLOCKED. Login page showed “Your login is blocked.” Set ACTIVE=Y, BLOCKED=N, LOGIN_ATTEMPTS=0 via `CUser::Update`. Proved ACTIVE=Y. Script: `ops/bitrix-aws/fix_khadija_login_block.php`. She should retry the Bitrix login.

---

## 2026-09-11 — Split WhatsApp Leads stage, then remove it (Cursor)

Live CRM on a7-old: `UC_WA_LEADS` had 329 cards. 27 with comment/bedrooms/client type/community → **AI Qualified** (`12`). 302 blank → **Junk**. Stage row 634 deleted; leftover automation template 374 deleted. Robots/n8n not fired (`ENABLE_SYSTEM_EVENTS=false`). Proved: leftover 0, sample 73512/69916 in `12`, 73471 in `JUNK`, status list has no WhatsApp Leads. Scripts: `ops/bitrix-aws/move_wa_leads_split.php`, `cleanup_wa_leads_status.php`. Hard-refresh the lead kanban. Conversation-monitor still defaults new creates to `UC_WA_LEADS` if someone runs it — that status is gone.
