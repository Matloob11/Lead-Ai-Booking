# Structure — file index

## `scripts/fixes/` — live writes to Bitrix

| File | Purpose |
|------|---------|
| `fix_agent_owner_data_perms.php` | Role **36**: add Owner Data `DYNAMIC_1042` + C13 + C14 personal READ/WRITE/ADD (+ C14 stage READ). Clears cache. Verifies sample agents. |
| `fix_agent_lead_crm_perms.php` | Role **36**: add LEAD, CONTACT, COMPANY, DEAL (+ QUOTE helpers) personal perms. Clears cache. Verifies Uzma/mehnaz/etc. |

Both upsert into `b_crm_role_perms` (insert or update). Safe to re-run.

## `scripts/probes/` — read-only diagnosis

| File | Purpose |
|------|---------|
| `probe_agent_owner_access.php` | Who has which CRM roles; all `*1042*` role perms; `canReadItemsInCategory` for agents vs heads. |
| `probe_agent_lead_access.php` | Role 8 vs 36 LEAD/CONTACT/DEAL; agent `canRead` LEAD. |
| `probe_agent_role36_lead.php` | Dump LEAD+1042 rows for roles 6/8/36/43/54. |
| `probe_agent_role36_detail.php` | Role 36 full entity summary; mehnaz LEAD check; category list for 1042. |

## `scripts/verify/` — acceptance

| File | Purpose |
|------|---------|
| `verify_head_vs_agent_scope.php` | Asserts heads have **department** attrs; agents **self-only**; item `canRead` own=Y teammate=N head=Y. Prints `ALL CHECKS PASSED` or failures. |

Update the `$teams` / `$agentsOnly` arrays in this file when Team Divide changes.

## `scripts/related-tl/` — copies of earlier TL work

Not moved out of `ops/bitrix-aws/` (still live there). Included so this zip is self-explanatory.

| File | Purpose |
|------|---------|
| `fix_tl_visibility_deep.php` | Set UF_DEPARTMENT, rebuild access codes, role 54 READ=D WRITE=A, rebuild attrs. |
| `fix_tl_role54_perms.php` | Clean duplicate role 54 READ rows; SETTINGS self/dept/subdept. |
| `fix_tl_perms_deep.php` | Deeper TL perm surgery. |
| `verify_tl_final.php` / `verify_tl_access.php` | TL-only verification. |
| `probe_owner_kanban_perms.php` | Owner Data cat 13 kanban / role 54 probe. |

## `reference/`

| File | Purpose |
|------|---------|
| `teams-and-roles.json` | Machine-readable teams, role IDs, entity/category IDs, DB table names. |

## Docs

| File | Purpose |
|------|---------|
| `README.md` | Product summary + rules of the road |
| `HOWTO.md` | SSH / `sudo -u bitrix php` runbook |
| `STRUCTURE.md` | This file |
