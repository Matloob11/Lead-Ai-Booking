# Bitrix CRM Access — Heads vs Agents

Handoff package for **A7 Group** Bitrix24 CRM visibility:

| Who | Sees |
|-----|------|
| **Team Leaders (heads)** | Own + **whole team** Leads & Owner Data (department scope) |
| **Agents** | **Only own assigned** Leads, Owner Data, Contacts, Companies, Deals |

CRM: `https://crm.a7grouprealestatedxb.com`  
Owner Data SPA: `entityTypeId=1042` (categories **13** Owner Data, **14** Availability)

---

## What broke (2026-09)

Agents opened Owner Data / Leads and got **Access Denied**. Heads were fine.

**Root cause:** CRM role **36 (Agent)** bound to intranet group **G11** had almost no CRM entity permissions (only a few unrelated SPAs). Role **54 (Team Leader)** already had department-scoped READ.

**Fix applied live:**

1. Role 36 → personal (`ATTR=A`) perms for `DYNAMIC_1042` + C13 + C14  
2. Role 36 → personal perms for `LEAD`, `CONTACT`, `COMPANY`, `DEAL` (+ quote helpers)  
3. Verified: agents self-only; heads department; item-level teammate deny / head allow

---

## Folder map

```
bitrix-crm-access/
├── README.md                 ← you are here
├── STRUCTURE.md              ← file-by-file index
├── HOWTO.md                  ← how to run scripts on AWS
├── reference/
│   └── teams-and-roles.json  ← head/agent IDs, roles, tables
└── scripts/
    ├── fixes/                ← apply permission changes (LIVE WRITE)
    ├── probes/               ← read-only diagnosis
    ├── verify/               ← prove head vs agent scope
    └── related-tl/           ← earlier TL department setup (copies)
```

Give someone **this whole folder** (zip is fine). They need SSH to the Bitrix AWS host (`a7-aws`) and `sudo -u bitrix php …`.

---

## Roles that matter

| Role ID | Name | Who | Scope |
|--------:|------|-----|-------|
| **54** | Team Leader | Hassan 2560, Hussnain 2551, Jaweria 2297 | READ=`D` (self + dept) |
| **36** | Agent | Group G11 (most sales agents) | READ=`A` (self only) |
| 8 | Sales Agent | Few users / dept codes | Template we copied for agents |
| 6 | Employee | Group G12 | Almost no CRM entities |

Details + team rosters: `reference/teams-and-roles.json`

---

## Safe update order

1. **Probe first** (`scripts/probes/`) — never skip if Access Denied returns  
2. **Fix** (`scripts/fixes/`) — writes `b_crm_role_perms`  
3. **Verify** (`scripts/verify/verify_head_vs_agent_scope.php`) — must print `ALL CHECKS PASSED`  
4. Tell agents / heads to **logout → login** (or hard refresh)

Do **not** give agents `ATTR=X` or `ALL` — that shows company-wide data.

---

## Related work still under `ops/bitrix-aws/`

Phone mask for TLs, Voiso/Zadarma Owner Data Call, kanban probes, etc. stay in the main repo `ops/bitrix-aws/`. This package is **CRM role visibility only**.

Old paths like `ops/bitrix-aws/fix_agent_*.php` are stubs that point here.
