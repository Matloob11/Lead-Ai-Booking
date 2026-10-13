#!/bin/bash
# Install minute cron for background Assign-to-team jobs (bitrix user).
set -eu
LINE='* * * * * /usr/bin/php -f /home/bitrix/www/bitrix/php_interface/a7_team_assign_cron.php >/dev/null 2>&1'
TMP=$(mktemp)
crontab -u bitrix -l 2>/dev/null | grep -v a7_team_assign_cron.php > "$TMP" || true
echo "$LINE" >> "$TMP"
crontab -u bitrix "$TMP"
rm -f "$TMP"
echo "cron installed:"
crontab -u bitrix -l | grep a7_team_assign || true
