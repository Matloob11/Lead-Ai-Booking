#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
ops/wa.sh up app beat >/dev/null
ops/wa.sh sql app "SELECT id, request_body->>'to' AS sent_to, response_body->'contacts'->0->>'wa_id' AS wa_id FROM gateway_apicall WHERE path LIKE '%/messages' ORDER BY id DESC LIMIT 3"
ops/wa.sh sql app "SELECT m.id, m.status, m.error_code, left(m.error_detail,80), m.wamid IS NOT NULL AS has_wamid FROM inbox_message m JOIN inbox_conversation c ON c.id=m.conversation_id JOIN inbox_contact ct ON ct.id=c.contact_id WHERE ct.wa_id='971559298388' ORDER BY m.id DESC LIMIT 5"
