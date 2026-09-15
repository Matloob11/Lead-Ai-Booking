# HOWTO — run on Bitrix AWS

## Prerequisites

- SSH host alias **`a7-aws`** (or equivalent) to the CRM server  
- User that can `sudo -u bitrix`  
- Scripts are PHP CLI; they bootstrap Bitrix via `/home/bitrix/www`

Bitrix document root permission: run as **`bitrix`**, not root alone:

```bash
sudo -u bitrix php /path/to/script.php
```

## Deploy a script then run

From your laptop (repo root or this folder):

```bash
# example: verify
scp scripts/verify/verify_head_vs_agent_scope.php a7-aws:/tmp/verify_head_vs_agent_scope.php
ssh a7-aws "sudo -u bitrix php /tmp/verify_head_vs_agent_scope.php"
```

```bash
# example: re-apply agent LEAD perms (idempotent)
scp scripts/fixes/fix_agent_lead_crm_perms.php a7-aws:/tmp/fix_agent_lead_crm_perms.php
ssh a7-aws "sudo -u bitrix php /tmp/fix_agent_lead_crm_perms.php"
```

## Diagnosis flow (Access Denied again)

1. `probe_agent_owner_access.php` or `probe_agent_lead_access.php`  
2. Confirm user roles — agents should show `36:Agent@G11`  
3. Confirm `b_crm_role_perms` has rows for role 36 + entity (`LEAD` or `DYNAMIC_1042_C14`)  
4. Re-run the matching **fix_*** script  
5. `verify_head_vs_agent_scope.php`  
6. User **logout / login**

## After permission changes

Always clear caches (the fix scripts already call `BXClearCache` + managed cache clean).  
Still ask the user to re-login — Bitrix session can keep old permission bags.

## Changing teams

1. Edit `reference/teams-and-roles.json`  
2. Edit `$teams` in `scripts/verify/verify_head_vs_agent_scope.php`  
3. Edit `$teams` in `scripts/related-tl/fix_tl_visibility_deep.php` if departments/UF_HEAD need sync  
4. Re-run TL visibility fix **only** if department membership changed  
5. Re-run verify

## Do / Don’t

| Do | Don’t |
|----|--------|
| Keep agents on ATTR=`A` (personal) | Give agents ATTR=`X` / ALL |
| Keep heads on ATTR=`D` + dept SETTINGS | Put agents on role 54 |
| Probe → fix → verify | Edit UI roles blindly without verify |
| Re-login after fixes | Assume `restart` alone refreshes CRM perms |

## ATTR cheat sheet

| ATTR | Meaning (legacy Bitrix CRM) |
|------|------------------------------|
| `A` | Personal / assigned to me |
| `D` | Department (+ often SETTINGS for SUBDEPARTMENTS) |
| `X` | All |
| `null` + SETTINGS JSON | Newer model (`SELF`, `DEPARTMENT`, …) |

## DB touch points

- `b_crm_role` / `b_crm_role_relation` / `b_crm_role_perms`  
- `b_user_access` (access codes after department change)  
- `b_crm_lead`, `b_crm_dynamic_items_1042`  
- `b_crm_access_attr_dynamic_1042` (list filters for Owner Data)

Prefer the PHP scripts over raw SQL unless you know the Bitrix permission cache implications.
