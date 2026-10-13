# Read-only, run through `ops/wa.sh probe-backend-md5`: md5 of every source
# file in the running web image (apps/, a7wa/), to find drift between the
# server and a local checkout before editing. Prints paths and hashes only.
import hashlib
import pathlib

root = pathlib.Path("/app")
for base in ("apps", "a7wa"):
    for path in sorted((root / base).rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix not in {".py", ".html", ".txt", ".json"}:
            continue
        data = path.read_bytes()
        print("MD5", hashlib.md5(data.replace(b"\r\n", b"\n")).hexdigest(), path.relative_to(root).as_posix())
print("PROBE_OK")
