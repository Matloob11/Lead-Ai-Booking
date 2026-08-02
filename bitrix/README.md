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
| `public/install.html` | Install handler — `placement.bind(LEFT_MENU)` + `installFinish()`. Unbind button bhi isi par. |
| `public/assets/bitrix-sso.js` | BX24 load/init, `getAuth`/`refreshAuth`, session bootstrap, CSRF-aware `apiFetch`. |
| `public/assets/panel.css` | Shell styling (navy/gold). |
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
| Scope | `placement`, `user` |

- `placement` ke bagair `placement.bind` fail karega (`ACCESS_DENIED`).
- `user` is liye ke backend `AUTH_ID` ko portal par `user.current` call se verify
  karta hai — yehi cheez token ko forge hone se rokti hai.

Save karne par Bitrix **Client ID (`client_id`)** aur **Client secret** dikhata hai.
Ye dono **backend session ko `.env` ke zariye** dein — chat/commit mein na likhein.

Phir **Install** dabayein: Bitrix `install.html` kholega, wo `LEFT_MENU` placement
bind karke `installFinish()` call karega. Left menu refresh par **WhatsApp** item
aa jayega.

> Re-install ya handler URL badalne ke baad `install.html` dobara khol lena kaafi
> hai — already-bound placement ko wo success maanta hai.

---

## Verify

1. Bitrix mein left menu → **WhatsApp** → panel khulta hai.
2. Teenon step ✓ hone chahiyein: *Bitrix token → Panel session → Numbers*.
3. Agent ka naam aur uske numbers dikhna chahiyein; admin par gold **Admin** pill.
4. Do alag Bitrix users se kholein — dono ko apna apna naam/numbers milne chahiyein.

Koi step ✕ hua to page par exact `code` + detail aa jata hai (`sdk_timeout`,
`no_auth`, `http_401`, `cookie_blocked`…) — wahi report karein.

---

## Backend session ke liye requests

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

## Known risk — third-party cookies

Panel `wa.srv1802669.hstgr.cloud` ka iframe `crm.a7grouprealestatedxb.com` ke andar
chalta hai, to session cookie browser ki nazar mein **third-party** hai. `SameSite=None;
Secure` set hai (settings mein confirm kiya), jo Chrome/Edge par kaam karta hai —
lekin **Safari aur Firefox default par ise block karte hain**, aur wahan panel
`cookie_blocked` error dikhayega.

Agar agents Safari/Firefox use karte hain to backend ko `/api/auth/bitrix/` se ek
short-lived token bhi return karna hoga jo panel `Authorization` header mein bheje.
Ye abhi banaya nahi gaya — pehle Chrome par chala kar dekhte hain.
