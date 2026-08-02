# Doc 51 — Duplicate-Client Detection

> One customer sometimes contacts two or three A7 agents. They compete, undercut price, and
> the deal breaks or margin is lost. The company must know **instantly** and decide who keeps
> the client.
> Related: [11 Multi-number](11-multi-number-management.md) · [20 Backend](20-backend-architecture.md) · [30 DB schema](30-database-schema.md)

---

## 1. The problem in one line

Same customer number → two different A7 agents at once → internal price war. **One customer,
one agent, decided by management — not by whoever shouts loudest.**

---

## 2. Definition of "duplicate"

A customer is a duplicate when the **same `wa_number`** is in an **active** conversation with
**more than one agent** within a configurable recent window.

- "Active" = last inbound/outbound within `settings.duplicate_window` (e.g. 7–14 days). Old,
  closed relationships don't count.
- Because customer identity is keyed on `wa_number` (UNIQUE in `customers`), a single number
  maps to one `customers` row — the duplicate signal comes from **contact across numbers /
  reassignment history**, not from two customer rows.

> Two interpretations, both handled:
> 1. The customer messages **two different company numbers** owned by different agents.
> 2. Internally the same customer is being worked/claimed by two agents (assignment conflict).

---

## 3. The logic (runs in the detection pipeline)

On every inbound message ([Doc 20](20-backend-architecture.md) §3.5, step 2):

```
1. Resolve the customer by wa_number.
2. Find all agents who have had ACTIVE contact with this number in the window:
   - the current assigned_agent_id, AND
   - any other agent whose number this customer also messaged (via messages.number_id → agent),
   - plus any recent reassignment history.
3. If distinct active agents > 1  →  DUPLICATE.
```

Set `customers.duplicate_flag = true` and record which agents are involved.

---

## 4. What happens on a duplicate

1. Set `duplicate_flag = true` on the customer.
2. Create a `duplicate` **alert** with payload `{ customer, agents: [A, B] }`.
3. Push `alert:duplicate` over Socket.IO to **both agents' manager(s)** and the dashboard:
   *"Client +9715XXXX is talking to Agent A and Agent B."*
4. Show an **amber banner** in each involved agent's chat window ([Doc 40](40-frontend-web-app.md)).
5. Management decides who keeps the client → **re-assign** in one click.

---

## 5. Resolution (re-assignment)

- Admin/manager picks the winning agent.
- Backend updates `assigned_agent_id` (and keeps the pinned `assigned_number_id` for continuity,
  or re-homes consciously if needed — [Doc 11](11-multi-number-management.md) §4).
- Writes an `audit_log` row (`action = reassign`, who/from/to).
- Clears `duplicate_flag` once resolved.
- The losing agent's access to that chat is removed (least access).

---

## 6. Edge cases

| Case | Handling |
|------|----------|
| Same customer messages the **same** agent's two numbers | Not a duplicate (one agent). |
| Customer went cold, returns after months to a new agent | Old contact outside the window → not flagged; normal re-engagement. |
| Genuine household (family shares a number) | Management judgement on re-assign; system just surfaces it. |
| Rapid back-and-forth reassignment | Audit log preserves the full trail. |

---

## 7. Config

- `settings.duplicate_window` — how recent counts as "active" (default e.g. 10 days).
- Whether to auto-flag or require an inbound to re-check (default: check on every inbound).

---

## 8. Bitrix linkage

- Write `Duplicate Alert (Y/N)` to the contact's custom field ([Doc 60](60-bitrix24-sync.md)).
- On resolution, update the assigned-agent field in Bitrix too.

---

## 9. Testing checklist

- [ ] Same number active with two agents raises exactly one duplicate alert.
- [ ] Both managers + dashboard receive the alert live.
- [ ] Amber banner shows in both agents' chat windows.
- [ ] One-click reassign updates the agent, writes audit, clears the flag.
- [ ] Losing agent can no longer open the chat.
- [ ] Contact within one agent (two of his numbers) is NOT flagged.
- [ ] Contact outside the active window is NOT flagged.
- [ ] Duplicate flag reaches Bitrix custom field.

---

*Next: [Doc 52 — Competitor-Agent Detection](52-competitor-detection.md).*
