#!/usr/bin/env python3
"""Process RSS of existing suites. Not a production memory budget or admission API."""
import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
# Regression ceiling for these small correctness binaries, not a server capacity claim.
CEILING = 256 * MIB


def rss_bytes(value, host=sys.platform):
    if host == "darwin":
        return value
    if host.startswith("linux"):
        return value * 1024
    raise RuntimeError("resource measurements are defined only for Linux/macOS")


def measured(command, timeout=180):
    with tempfile.TemporaryFile() as output:
        began = time.monotonic()
        process = subprocess.Popen([str(item) for item in command], stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.monotonic() - began >= timeout:
                    raise TimeoutError(f"resource child exceeded {timeout}s: {command}")
                time.sleep(0.01)
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, status, _ = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
        output.seek(0)
        transcript = output.read(65537)
    assert len(transcript) <= 65536, "unexpectedly large resource output"
    assert process.returncode == 0, (process.returncode, transcript.decode(errors="replace"))
    return transcript.decode(errors="replace"), rss_bytes(usage.ru_maxrss)


def main(binaries=None):
    if binaries is None:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("binaries", type=Path, nargs="?", default=ROOT / "build/native3")
        binaries = parser.parse_args().binaries
    binaries = Path(binaries).resolve()
    results = []
    with tempfile.TemporaryDirectory(prefix="luce-db-resources-") as tmp:
        tmp = Path(tmp)
        for name, extra in [("writers", []), ("concurrency", [tmp / "concurrency.db"]),
                            ("backups", [tmp / "backups.db"]), ("schemas", [tmp / "schemas.db"])]:
            transcript, peak = measured([binaries / name, *extra])
            print(f"RSS {name} {peak} {peak / MIB:.1f}MiB", flush=True)
            assert peak < CEILING, (name, peak, CEILING)
            results.append((name, peak))
    print(f"PASS aggregate process RSS under {CEILING // MIB} MiB ceiling", flush=True)
    return results


if __name__ == "__main__":
    main()
