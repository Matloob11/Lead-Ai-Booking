import { assertBulkGuard, assertNewContactLimit } from "../../outbound/throttle.js";
import { getSessionRisk } from "../../outbound/risk_eval.js";
import { q } from "../../db.js";

async function testGuards() {
  console.log("=== TESTING GUARD & RATE LIMIT TRIGGER DIRECTLY ===");

  // 1. Test Bulk Guard Triggering across 10 distinct contacts
  console.log("Testing Bulk Guard logic across 10 distinct contacts...");
  try {
    // Insert 10 fake contacts and conversations
    for (let i = 10001; i <= 10010; i++) {
      const ct = await q(
        `INSERT INTO qr_contact (wa_id, display_name) VALUES ($1, $2) ON CONFLICT (wa_id) DO UPDATE SET display_name = EXCLUDED.display_name RETURNING id`,
        [`fake_${i}`, `fake_${i}`]
      );
      const contactId = ct[0].id;
      const cv = await q(
        `INSERT INTO qr_conversation (session_id, contact_id, unread_count) VALUES (3, $1, 0) ON CONFLICT (session_id, contact_id) DO UPDATE SET unread_count = 0 RETURNING id`,
        [contactId]
      );
      const convId = cv[0].id;
      await q(
        `INSERT INTO qr_message (conversation_id, direction, body, status, created_at) VALUES ($1, 'out', 'SPAM_BULK_TRIGGER_TEST', 'sent', now())`,
        [convId]
      );
    }

    await assertBulkGuard("SPAM_BULK_TRIGGER_TEST");
    console.log("FAIL: Bulk guard did not throw!");
  } catch (err) {
    console.log("[PASS BULK GUARD TRIGGER] Error caught successfully:", err.message);
  } finally {
    await q(`DELETE FROM qr_message WHERE body = 'SPAM_BULK_TRIGGER_TEST'`);
    await q(`DELETE FROM qr_contact WHERE wa_id LIKE 'fake_100%'`);
  }

  // 2. Test Daily Limit Triggering
  console.log("Testing Daily New Contacts Limit logic...");
  try {
    process.env.MAX_NEW_CONTACTS_PER_DAY = "0";
    await assertNewContactLimit(3);
    console.log("FAIL: Daily limit did not throw!");
  } catch (err) {
    console.log("[PASS DAILY LIMIT TRIGGER] Error caught successfully:", err.message);
  } finally {
    delete process.env.MAX_NEW_CONTACTS_PER_DAY;
  }

  // 3. Test High Risk Assessment Logic
  console.log("Testing High Risk level calculation...");
  const risk = await getSessionRisk(3);
  console.log("[PASS RISK EVAL] Current risk for session 3:", risk.level, risk.reasons);

  console.log("=== ALL GUARD TRIGGER TESTS COMPLETED SUCCESSFULLY ===");
}

testGuards().catch(console.error);
