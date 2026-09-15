#!/usr/bin/env python3
"""Run the database suite from trusted prebuilt binaries; no compiler/install step."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from check_http import check as check_http
from check_journal import check as check_journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaries", type=Path)
    args = parser.parse_args()
    binaries = args.binaries.resolve()
    for name in ["tree", "writers", "storage_faults", "transactions", "bounds", "concurrency", "facade", "journal_driver", "registry_server"]:
        if not (binaries / name).is_file(): raise SystemExit(f"missing {name}")

    def run(command):
        subprocess.run([str(arg) for arg in command], check=True, timeout=90)

    with tempfile.TemporaryDirectory(prefix="luce-db-prebuilt-") as tmp:
        run([binaries / "tree"])
        run([binaries / "writers"])
        for name in ["transactions", "bounds", "concurrency", "facade", "storage_faults"]:
            run([binaries / name, Path(tmp) / f"{name}.db"])
        run([binaries / "concurrency", Path(tmp) / "concurrency-wait.db", "wait"])
    check_journal(binaries / "journal_driver")
    check_http(binaries / "registry_server")
    print("PASS prebuilt database suite", flush=True)


if __name__ == "__main__": main()
