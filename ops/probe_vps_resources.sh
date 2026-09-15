#!/bin/bash
# Read-only host + container resource snapshot for A7 WA VPS.
set -euo pipefail

echo "========== HOST =========="
hostname
date -u
echo
echo "--- CPU ---"
nproc
lscpu 2>/dev/null | grep -E 'Model name|CPU\(s\)|Thread|Core|MHz|Socket' || true
uptime
echo
echo "--- Memory (MB) ---"
free -m
echo
echo "--- Swap ---"
swapon --show 2>/dev/null || true
echo
echo "--- Disk ---"
df -h / /opt /var/lib/docker 2>/dev/null || df -h /
echo
echo "--- Load / pressure (if available) ---"
cat /proc/loadavg
grep -E 'MemTotal|MemAvailable|MemFree|Buffers|Cached|SwapTotal|SwapFree' /proc/meminfo
echo
echo "========== DOCKER =========="
docker info 2>/dev/null | grep -E 'CPUs|Total Memory|Server Version|Containers' || true
echo
echo "--- docker stats (now) ---"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}' 2>/dev/null || true
echo
echo "========== COMPOSE LIMITS =========="
for d in /opt/a7-wa/deploy /opt/a7-wa/wa-qr /opt/openwa-trial /opt/a7-wa/agent-reports/deploy; do
  if [ -d "$d" ]; then
    echo "--- $d ---"
    grep -nE 'mem_limit|cpus|memory|deploy:|resources:' "$d"/docker-compose*.yml "$d"/compose*.yml 2>/dev/null || echo "(no mem/cpu limits in compose files)"
  fi
done
echo
echo "========== TOP MEM PROCESSES =========="
ps aux --sort=-%mem | head -20
echo
echo "========== OOM / recent kills =========="
dmesg -T 2>/dev/null | grep -iE 'oom|killed process|Out of memory' | tail -20 || journalctl -k -n 200 --no-pager 2>/dev/null | grep -iE 'oom|killed process' | tail -20 || echo "(no OOM lines found)"
echo
echo "DONE"
