"""Owner Data sync supervisor: 4 id-range workers, auto-restart on exit.

Stop by creating ``owner-sync.stop`` next to this backend folder
(or pass --once for a single pass per worker with no restart).

  python scripts/owner_sync_watchdog.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
STOP_FILE = BACKEND / "owner-sync.stop"
WATCH_LOG = BACKEND / "owner-sync-watchdog.log"
SCRIPT = BACKEND / "scripts" / "bulk_link_owner_phones.py"

SPLITS = (
    (1, 22500, 39375),
    (2, 39375, 56250),
    (3, 56250, 73125),
    (4, 73125, 90000),
)

RESTART_DELAY_SEC = 20
POLL_SEC = 10
MAX_IDLE_EXITS = 3
FULL_ROUND_SLEEP_SEC = 120


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with WATCH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def last_seen(worker_n: int) -> int:
    path = BACKEND / f"owner-sync-w{worker_n}.log"
    if not path.exists():
        return -1
    text = path.read_text(encoding="utf-8", errors="replace")
    marker = '"seen":'
    idx = text.rfind(marker)
    if idx < 0:
        return -1
    rest = text[idx + len(marker) :].lstrip()
    digits = []
    for ch in rest:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    return int("".join(digits)) if digits else -1


def spawn(worker_n: int, id_min: int, id_max: int) -> subprocess.Popen:
    err_path = BACKEND / f"owner-sync-w{worker_n}.err.log"
    out_path = BACKEND / f"owner-sync-w{worker_n}.log"
    with err_path.open("a", encoding="utf-8") as err:
        err.write(f"\n--- watchdog start {datetime.now():%Y-%m-%d %H:%M} ids [{id_min},{id_max}) ---\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND)
    env["PYTHONUNBUFFERED"] = "1"
    out_fh = out_path.open("a", encoding="utf-8")
    err_fh = err_path.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--category",
            "13",
            "--id-min",
            str(id_min),
            "--id-max",
            str(id_max),
        ],
        cwd=str(BACKEND),
        env=env,
        stdout=out_fh,
        stderr=err_fh,
    )
    # Detach FDs from this process; child keeps them open.
    out_fh.close()
    err_fh.close()
    return proc


def main() -> None:
    os.chdir(BACKEND)
    if STOP_FILE.exists():
        STOP_FILE.unlink()

    workers: list[dict] = []
    log("watchdog starting 4 workers (stop: owner-sync.stop)")
    for n, id_min, id_max in SPLITS:
        proc = spawn(n, id_min, id_max)
        workers.append(
            {
                "n": n,
                "min": id_min,
                "max": id_max,
                "proc": proc,
                "idle": 0,
            }
        )
        log(f"spawned w{n} pid={proc.pid} ids [{id_min},{id_max})")

    while True:
        if STOP_FILE.exists():
            log("stop file present - watchdog exit")
            break

        time.sleep(POLL_SEC)
        alive = 0
        restart: list[int] = []

        for i, w in enumerate(workers):
            proc: subprocess.Popen | None = w["proc"]
            if proc is not None and proc.poll() is None:
                alive += 1
                continue
            if proc is None:
                continue

            code = proc.returncode
            seen = last_seen(w["n"])
            if seen == 0:
                w["idle"] += 1
            else:
                w["idle"] = 0

            if w["idle"] >= MAX_IDLE_EXITS:
                log(f"w{w['n']} idle x{w['idle']} (seen=0) - resting")
                w["proc"] = None
                continue

            log(f"w{w['n']} exited code={code} seen={seen} - queue restart")
            restart.append(i)

        if restart:
            time.sleep(RESTART_DELAY_SEC)
            if STOP_FILE.exists():
                break
            for i in restart:
                w = workers[i]
                if w["idle"] >= MAX_IDLE_EXITS:
                    continue
                proc = spawn(w["n"], w["min"], w["max"])
                w["proc"] = proc
                log(f"respawned w{w['n']} pid={proc.pid}")
                alive += 1

        if alive == 0 and not STOP_FILE.exists():
            log(f"all resting - full respawn in {FULL_ROUND_SLEEP_SEC}s")
            time.sleep(FULL_ROUND_SLEEP_SEC)
            if STOP_FILE.exists():
                break
            for w in workers:
                w["idle"] = 0
                proc = spawn(w["n"], w["min"], w["max"])
                w["proc"] = proc
                log(f"full-round spawn w{w['n']} pid={proc.pid}")

    log("watchdog stopped")


if __name__ == "__main__":
    main()
