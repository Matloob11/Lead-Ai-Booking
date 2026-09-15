#!/usr/bin/env bash
# Live prove: Owner Data phone match from inside openwa-api.
set -euo pipefail
HOST="root@187.127.123.235"
KEY_FILE="C:/Users/Matloob/.ssh/hostinger_codex"
KNOWN_HOSTS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/known_hosts"
OPENWA_DIR="/opt/openwa-trial/OpenWA"
KNOWN_HOSTS_WIN="$KNOWN_HOSTS"
if command -v wslpath >/dev/null 2>&1; then
  case "$KNOWN_HOSTS" in
    /mnt/*) KNOWN_HOSTS_WIN=$(wslpath -w "$KNOWN_HOSTS") ;;
  esac
fi
SSH=(ssh.exe -i "$KEY_FILE" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS_WIN")

PHONE="${1:-971559525201}" # known Owner Data sample (Ahsan Abbas)

"${SSH[@]}" "$HOST" "cd '$OPENWA_DIR' && docker compose exec -T openwa-api node -e \"
const base=(process.env.BITRIX_WEBHOOK_BASE||'').replace(/\\/+\\\$/,'');
const typeId=Number(process.env.BITRIX_OWNER_DATA_TYPE_ID||1042);
const phone=process.argv[1];
const fields=['ufCrm5_1768317611513','ufCrm5_1769416533028'];
const candidates=[Number(phone)];
if(phone.startsWith('971')&&phone.length>9) candidates.push(Number(phone.slice(3)));
(async()=>{
  for (const field of fields) {
    for (const value of candidates) {
      const res=await fetch(base+'/crm.item.list.json',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({entityTypeId:typeId,select:['id','title'],filter:{[field]:value}})});
      const data=await res.json();
      const items=(data.result&&data.result.items)||[];
      if(items.length){ console.log('owner-match', JSON.stringify({phone,field,value,id:items[0].id,title:items[0].title,entityType:'DYNAMIC_'+typeId})); process.exit(0);} }
  }
  console.log('owner-match-none', phone);
  process.exit(2);
})().catch(e=>{ console.error(e); process.exit(1); });
\" '$PHONE'"

bash ops/wa.sh openwa-state 2>&1 | head -8
