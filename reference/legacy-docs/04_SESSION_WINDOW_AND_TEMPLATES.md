# 04 - 24-Hour Session Window & Template Engine Specification

## 1. Business Rules
WhatsApp Business Policy strictly enforces conversation session limits:
- **Session Open**: Customer initiates message -> 24-hour window starts.
- **In-Session**: Agents can send free-form text, images, voice notes, PDFs.
- **Session Expired**: Exactly 24 hours after customer's last message. Free-form messaging is blocked.
- **Session Re-Opening**: Outbound Meta-Approved HSM Template message sent by agent, OR customer replies.

---

## 2. Dynamic Variable Substitution Logic
Meta templates contain variable placeholders in body or headers:
- Template: `"Dear {{1}}, your appointment is scheduled for {{2}}."`
- Parameters array: `["Mr. Smith", "Monday 3 PM"]`
- Final Output: `"Dear Mr. Smith, your appointment is scheduled for Monday 3 PM."`

---

## 3. Embedded Agent UI Widget (`a7_waba_widget.html`)
The side-panel UI widget embedded inside Bitrix provides:
1. **Live Countdown Timer**: Displays exact remaining time in 24h window (e.g., `04h 12m remaining`).
2. **Template Dropdown**: Loads synced Meta-Approved Templates.
3. **Dynamic Variable Inputs**: Generates input fields for `{{1}}`, `{{2}}` based on chosen template.
4. **Live Preview**: Real-time message card rendering.
5. **One-Click Send Button**: Submits payload to local Django API endpoint `/api/v1/waba/templates/send/`.
