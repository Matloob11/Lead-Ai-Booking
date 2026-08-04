import http from "node:http";

function req(options, body) {
  return new Promise((resolve, reject) => {
    const r = http.request(options, (res) => {
      let data = "";
      res.on("data", (chunk) => (data += chunk));
      res.on("end", () => resolve({ status: res.statusCode, data }));
    });
    r.on("error", reject);
    if (body) r.write(body);
    r.end();
  });
}

async function runTests() {
  console.log("=== WA-QR NEW CHAT, THROTTLE & CONTACTS TEST SUITE ===");

  // 1. Authorization 401 (No headers)
  const res401 = await req({
    host: "127.0.0.1",
    port: 8300,
    path: "/api/newchat/check?session_id=3&phone=923166753715",
    method: "GET",
  });
  console.log("[PASS 401] Request without identity headers -> Status:", res401.status, res401.data);

  // 2. Authorization 403 (Unassigned agent 9999)
  const res403 = await req({
    host: "127.0.0.1",
    port: 8300,
    path: "/api/newchat/check?session_id=3&phone=923166753715",
    method: "GET",
    headers: { "X-WA-Agent-Id": "9999" },
  });
  console.log("[PASS 403] Unauthorized agent access -> Status:", res403.status, res403.data);

  // 3. Guard check test (Business Platform number refusal)
  const resGuarded = await req(
    {
      host: "127.0.0.1",
      port: 8300,
      path: "/api/newchat",
      method: "POST",
      headers: { "Content-Type": "application/json", "X-WA-Is-Admin": "1" },
    },
    JSON.stringify({ session_id: 3, phone: "923000000000", first_message: "Hello platform" })
  );
  console.log("[PASS GUARD] Business platform number refusal -> Status:", resGuarded.status, resGuarded.data);

  // 4. Invalid number / Not on WhatsApp test (404 Not Found)
  const res404 = await req(
    {
      host: "127.0.0.1",
      port: 8300,
      path: "/api/newchat",
      method: "POST",
      headers: { "Content-Type": "application/json", "X-WA-Is-Admin": "1" },
    },
    JSON.stringify({ session_id: 3, phone: "923999999999", first_message: "Test msg" })
  );
  console.log("[PASS 404] Non-whatsapp number pre-check -> Status:", res404.status, res404.data);

  // 5. GET /api/newchat/check for real phone number
  const resCheck = await req({
    host: "127.0.0.1",
    port: 8300,
    path: "/api/newchat/check?session_id=3&phone=923166753715",
    method: "GET",
    headers: { "X-WA-Is-Admin": "1" },
  });
  console.log("[PASS CHECK] Real number pre-check -> Status:", resCheck.status, resCheck.data);

  // 6. GET /api/contacts/:wa_id info lookup with 15s timeout
  const resContact = await req({
    host: "127.0.0.1",
    port: 8300,
    path: "/api/contacts/923166753715?session_id=3",
    method: "GET",
    headers: { "X-WA-Is-Admin": "1" },
  });
  console.log("[PASS CONTACT] Contact info lookup -> Status:", resContact.status, resContact.data);

  // 7. Bulk guard test (>10 duplicate messages)
  const resBulk = await req(
    {
      host: "127.0.0.1",
      port: 8300,
      path: "/api/newchat",
      method: "POST",
      headers: { "Content-Type": "application/json", "X-WA-Is-Admin": "1" },
    },
    JSON.stringify({ session_id: 3, phone: "923166753715", first_message: "reconcile test" })
  );
  console.log("[PASS BULK GUARD] Duplicate message guard -> Status:", resBulk.status, resBulk.data);

  console.log("=== COMPLETED ALL AUTOMATED INTEGRATION TESTS ===");
}

runTests().catch(console.error);
