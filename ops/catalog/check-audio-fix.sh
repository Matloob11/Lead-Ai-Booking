#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
ops/wa.sh sql app "SELECT downloaded, count(1) AS n FROM inbox_mediaasset WHERE mime_type LIKE 'audio%' GROUP BY 1 ORDER BY 1"
ops/wa.sh sql app "SELECT id, downloaded, size_bytes FROM inbox_mediaasset WHERE id = 337"
ops/wa.sh retry-failed-audio
