# Bitrix24 Local Application — A7 WhatsApp Inbox

Left menu mein **WhatsApp** item, jo hamara apna panel iframe mein kholta hai, aur
agent ki pehchaan Bitrix se hi ho jaati hai (koi alag login nahi).

```
Bitrix left menu "WhatsApp"
        │  POST (AUTH_ID, member_id, DOMAIN, PLACEMENT=LEFT_MENU)
        ▼
https://wa.srv1802669.hstgr.cloud/app/          ← nginx static (bitrix/public/)
        │  BX24.init() → BX24.getAuth()
        ▼
POST /api/auth/bitrix/ {AUTH_ID, member_id, DOMAIN}   ← Django, session cookie set
        ▼
GET /api/auth/me/ · /api/catalog/numbers/ · … · wss://…/ws/inbox/
```

Handler page static hai — POST body parse nahi karta. Bitrix ka JS SDK wahi teen
values `BX24.getAuth()` se de deta hai
([docs](https://apidocs.bitrix24.com/sdk/bx24-js-sdk/system-functions/bx24-get-auth.html)),
is liye panel ko Django ke andar rakhne ki zaroorat nahi rahi — `backend/` bilkul
alag rehta hai.

---

## Files

| File | Kya hai |
|------|---------|
| `public/index.html` | LEFT_MENU placement handler — SSO boot + connection diagnostics. Chat UI yahin aayegi. |
| `public/install.html` | Install handler — paanchon placements bind karta hai, `placement.get` se asli haalat dikhata hai, har row ka apna unbind. |
| `public/crm/index.html` | CRM detail-tab handler — chaaron CRM placements isi par khulte hain. |
| `public/assets/core/bitrix-sso.js` | BX24 load/init, `getAuth`/`refreshAuth`, `ensurePlacement`, session bootstrap, CSRF-aware `apiFetch`. |
| `public/assets/modules/panel.css` | Shell styling (navy/gold). |
| `public/assets/modules/install.css` | Sirf install screen ki placement table. |
| `deploy/a7-wa-panel.location.conf` | nginx `location /app/` block — haath se `a7-wa.conf` mein daalna hai. |
| `deploy/deploy-panel.sh` | `public/` ko `/opt/a7-wa/panel/` par rsync karta hai. |

---

## Deploy (server side) — pehla step

1. nginx block add karein: `deploy/a7-wa-panel.location.conf` ka content
   `/etc/nginx/conf.d/a7-wa.conf` ke **443 server block** mein, `location / {}` se
   **upar** paste karein.
2. `nginx -t && systemctl reload nginx`
3. `./bitrix/deploy/deploy-panel.sh`
4. Check: `curl -I https://wa.srv1802669.hstgr.cloud/app/` → `200`, aur
   `curl -X POST -I https://wa.srv1802669.hstgr.cloud/app/` → bhi `200`
   (POST par 405 aaya to Bitrix ka handler khulega hi nahi).

---

## Bitrix24 par local app register karna

**Portal:** https://crm.a7grouprealestatedxb.com → *Applications → Developer resources →
Other → Local application* (self-hosted 26.x mein *Integrations → Other* bhi ho sakta hai).

| Field | Value |
|-------|-------|
| Application name | `A7 WhatsApp Inbox` |
| Uses only API | **unchecked** (hamein UI chahiye) |
| Handler path (Application URL) | `https://wa.srv1802669.hstgr.cloud/app/` |
| Initial installation path | `https://wa.srv1802669.hstgr.cloud/app/install.html` |
| Menu item / icon | optional — asli item `placement.bind` se aata hai |
| Scope | `placement`, `user`, `crm` |

- `placement` ke bagair `placement.bind` fail karega (`ACCESS_DENIED`).
- `user` is liye ke backend `AUTH_ID` ko portal par `user.current` call se verify
  karta hai — yehi cheez token ko forge hone se rokti hai.
- `crm` sirf CRM tabs ke liye. Tab isi se lead/deal/contact/company ka `PHONE`
  field parhta hai. Iske bagair tab bind to ho jata hai magar khali rehta hai.

Save karne par Bitrix **Client ID (`client_id`)** aur **Client secret** dikhata hai.
Ye dono **backend session ko `.env` ke zariye** dein — chat/commit mein na likhein.

App banne ke baad `/marketplace/app/<ID>/` kholein: Bitrix `install.html` chalayega,
wo `LEFT_MENU` bind kar ke `installFinish()` call karega. Left menu refresh par
**WhatsApp** item aa jata hai.

> Re-install ya handler URL badalne ke baad `install.html` dobara khol lena kaafi
> hai — already-bound placement ko wo success maanta hai.
>
> Iske alawa `index.html` khud bhi har **Bitrix admin** ke load par `ensurePlacement()`
> chalata hai: agar menu item gayab ho ya purane handler URL par atka ho to wo
> chupchap dobara bind kar deta hai. Yani manual install step ab lazmi nahi.

### Is portal par jo cheez lagi hui hai (2026-08-02)

| Cheez | Value |
| --- | --- |
| App ID | `76` (`/marketplace/app/76/`) |
| `client_id` | `local.6a6f610dbf9b18.33835228` |
| Scope | `crm, placement, user` |
| Placement | `#282` — `LEFT_MENU` → `https://wa.srv1802669.hstgr.cloud/app/` |

**`crm` scope ab zaroori hai — hatana nahi.** Yahan pehle likha tha ke app ise
kabhi use nahi karta aur agli baar form khulne par hata dena behtar hai. Wo CRM
tabs se pehle ki baat thi; ab tab isi scope se numbers parhta hai.

---

## CRM detail tabs

Left menu ke ilawa, app har CRM detail screen par ek **WhatsApp** tab lagata hai.
Tab us record ke phone numbers uthata hai, `/api/inbox/lookup/` se poochta hai ke
un numbers se koi chat pehle se hai ya nahi, aur jawab wahin dikha deta hai — bina
agent ko inbox tak jaane ke.

| Placement | Kahan | Handler |
| --- | --- | --- |
| `CRM_LEAD_DETAIL_TAB` | Lead | `…/app/crm/` |
| `CRM_DEAL_DETAIL_TAB` | Deal | `…/app/crm/` |
| `CRM_CONTACT_DETAIL_TAB` | Contact | `…/app/crm/` |
| `CRM_COMPANY_DETAIL_TAB` | Company | `…/app/crm/` |

Chaaron ka handler **ek hi** page hai. Page `BX24.placement.info()` se pooch leta
hai ke wo kis screen par khula hai, aur usi hisab se `crm.lead.get`,
`crm.deal.get`, `crm.contact.get` ya `crm.company.get` chalata hai. Deal ke paas
apna phone nahi hota — wo apne juday hue contact ya company se number leta hai.

### Scope

`crm` chahiye, aur `placement` bind karne ke liye. Ye dono app ke Bitrix form
mein hain (ooper wali table dekhein).

### Lagana aur hatana

`…/app/install.html` kholein. Wahan paanchon placements ki ek list hai — har row
apni asli haalat `placement.get` se parh kar dikhati hai, na ke us se jo abhi bind
call ne kaha:

- **Bound** — isi handler par laga hua hai
- **Not bound** — laga hua nahi
- **Bound elsewhere** — kisi purane handler URL par laga hai (app ki jagah badli
  thi). Row us purane URL ka naam bhi leti hai.

Har row ka apna **Bind** / **Unbind** button hai. Sirf CRM tabs hatana aur left
menu rakhna — ya ulta — isi tarah hota hai.

> `ensurePlacement()` bind se pehle usi placement ke purane handler ko unbind
> karta hai. Is liye app ka URL badalne ke baad `install.html` dobara khol lena
> kaafi hai: purani binding khud saaf ho jati hai, warna har lead mein ek marra
> hua tab reh jata.

### Jo tab nahi kar sakta

- **Record par koi phone nahi** — tab yehi kehta hai. Lookup chalta hi nahi.
- **Deal par koi contact ya company juda nahi** — same, alag jumle ke saath.
- **Number kisi bhi format mein** — lookup aakhri **9 hindson** par match karta
  hai, is liye `+971 55 548 4423` aur `0555484423` ek hi chat par pahunchte hain.
- **Number jis se koi chat nahi** — tab wo numbers dikhata hai jin par is agent
  ka access hai, taake wahan se baat shuru ki ja sake.
- **Doosre agent ki chat** — nazar nahi aayegi. `/api/inbox/lookup/` sirf
  `visible_numbers` par scoped conversations lauta ta hai, yani wohi numbers jo
  is agent ko assign hain.

---

## Verify — 2026-08-02 ko live confirm hua

Left menu → **WhatsApp** → panel khula, teenon step ✓, agent `Admin Abdul Malik`
(Agent ID 2) identify hua. Yani BX24 token → Django session → catalog call, poori
chain iframe ke andar chal rahi hai aur third-party session cookie bhi tik rahi hai.

Do cheezein data side par abhi baaqi hain (backend/admin ka kaam, panel ka nahi):
`is_wa_admin` is user par `false` hai, aur us ko koi number assign nahi — is liye
panel "koi number assign nahi" dikhata hai.

## Verify (kisi bhi waqt dobara)

1. Bitrix mein left menu → **WhatsApp** → panel khulta hai.
2. Teenon step ✓ hone chahiyein: *Bitrix token → Panel session → Numbers*.
3. Agent ka naam aur uske numbers dikhna chahiyein; admin par gold **Admin** pill.
4. Do alag Bitrix users se kholein — dono ko apna apna naam/numbers milne chahiyein.

Koi step ✕ hua to page par exact `code` + detail aa jata hai (`sdk_timeout`,
`no_auth`, `http_401`, `cookie_blocked`…) — wahi report karein.

---

## Backend session ke liye requests

**Neeche ke chaaron ✅ ho chuke hain** (backend session ne 2026-08-02 ko confirm kiye,
aur live test mein chalte hue verify bhi ho gaye). Yahan record ke liye rakhe hain —
inmein se koi bhi wapas toota to panel foran `http_403`/`cookie_blocked` dikhayega.

Panel static hai, is liye ye chaar cheezein Django side par honi zaroori hain:

1. **`POST /api/auth/bitrix/` par `@csrf_exempt`.** Pehli load par koi `csrftoken`
   cookie hoti hi nahi aur static page mein template token inject nahi ho sakta.
   Ye endpoint waise bhi CSRF-proof hai — credential khud `AUTH_ID` hai, cookie nahi.
2. **`GET /api/auth/me/` par `@ensure_csrf_cookie`.** Panel isi response se
   `csrftoken` uthata hai aur baad ke har POST par `X-CSRFToken` bhejta hai.
   Warna `/send/`, `/start/` sab 403 denge.
3. **Unauthenticated par `401` JSON**, redirect nahi — panel `401`/`403` ko
   "SSO chala do" ka signal maanta hai.
4. **`AUTH_ID` ko portal par verify karein**: `GET https://{DOMAIN}/rest/user.current.json?auth={AUTH_ID}`
   aur uske `ID`/`member_id` ko request ke `member_id` se match karein. Bagair iske
   koi bhi POST karke kisi bhi agent ka session le sakta hai.

### Khula sawaal — WA admin kaun hai

Portal ka Bitrix admin (`Admin Abdul Malik`) auto-provision to ho gaya, lekin
`/api/auth/me/` us par `is_wa_admin: false` deta hai. Transfer dialog aur admin-only
screens isi flag par chalengi, to backend/admin mein tay karna hoga ke WA admin kaun
hai — Bitrix ke admin flag se derive hoga ya Django admin mein manually set hoga.

Note: menu item bind karne ka gate **ye flag nahi** hai — uske liye `BX24.isAdmin()`
istemal hota hai, kyunki `placement.bind` Bitrix ki permission hai, hamari nahi.

## Known risk — third-party cookies

Panel `wa.srv1802669.hstgr.cloud` ka iframe `crm.a7grouprealestatedxb.com` ke andar
chalta hai, to session cookie browser ki nazar mein **third-party** hai. `SameSite=None;
Secure` set hai (settings mein confirm kiya), jo Chrome/Edge par kaam karta hai —
lekin **Safari aur Firefox default par ise block karte hain**, aur wahan panel
`cookie_blocked` error dikhayega.

Agar agents Safari/Firefox use karte hain to backend ko `/api/auth/bitrix/` se ek
short-lived token bhi return karna hoga jo panel `Authorization` header mein bheje.
Ye jaan boojh kar nahi banaya — team Chrome/Edge par hai, aur Chrome par live test
mein cookie theek chal gayi.
