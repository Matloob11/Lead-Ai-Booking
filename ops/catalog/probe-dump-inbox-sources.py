# Read-only, run through `ops/wa.sh probe-dump-inbox-sources`: prints source
# files exactly as the running web image has them (base64), so a stale local
# checkout can be brought level with the server before editing. A fixed list:
# the files the 2026-10 visibility change touched. Our own code only.
import base64
import hashlib
import pathlib

ROOT = pathlib.Path("/app")
FILES = (
    "apps/gateway/ingest.py",
    "apps/inbox/consumers.py",
    "apps/inbox/events.py",
    "apps/inbox/models.py",
    "apps/inbox/views.py",
    "apps/inbox/visibility.py",
    "apps/inbox/tests/test_visibility.py",
    "apps/inboxai/views.py",
)
for rel in FILES:
    path = ROOT / rel
    if not path.is_file():
        print("MISSING", rel)
        continue
    data = path.read_bytes()
    print("FILE", rel, hashlib.md5(data).hexdigest(), len(data))
    print(base64.b64encode(data).decode("ascii"))
print("PROBE_OK")
