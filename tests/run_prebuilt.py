#!/usr/bin/env python3
"""Run the database suite from trusted prebuilt binaries; no compiler/install step."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from check_http import check as check_http
from check_journal import check as check_journal
from check_checkpoint import check as check_checkpoint
from check_checkpoint_process import check as check_checkpoint_process
from check_backup import check as check_backup
from check_backup_process import check as check_backup_process
from check_migration import check as check_migration
from check_migration_process import check as check_migration_process
from check_resources import main as check_resources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaries", type=Path)
    args = parser.parse_args()
    binaries = args.binaries.resolve()
    for name in ["tree", "writers", "storage_faults", "transactions", "bounds", "concurrency", "facade", "journal_driver", "registry_server", "checkpoints", "checkpoint_faults", "checkpoint_concurrency", "checkpoint_allocations", "checkpoint_driver", "checkpoint_process", "backups", "backup_faults", "backup_concurrency", "backup_allocations", "restore_faults", "backup_process", "backup_driver", "backup_race", "schemas", "migration_concurrency", "migration_allocations", "migration_faults", "migration_driver", "migration_process"]:
        if not (binaries / name).is_file(): raise SystemExit(f"missing {name}")

    def run(command):
        subprocess.run([str(arg) for arg in command], check=True, timeout=90)

    with tempfile.TemporaryDirectory(prefix="luce-db-prebuilt-") as tmp:
        run([binaries / "tree"])
        run([binaries / "writers"])
        for name in ["transactions", "bounds", "concurrency", "facade", "storage_faults", "checkpoints", "checkpoint_faults", "checkpoint_concurrency", "checkpoint_allocations"]:
            run([binaries / name, Path(tmp) / f"{name}.db"])
        run([binaries / "concurrency", Path(tmp) / "concurrency-wait.db", "wait"])
        for name in ["backups", "backup_faults", "backup_concurrency", "backup_allocations", "restore_faults", "backup_race",
                     "schemas", "migration_concurrency", "migration_allocations", "migration_faults"]:
            run([binaries / name, Path(tmp) / f"{name}.db"])
    check_journal(binaries / "journal_driver")
    check_checkpoint(binaries / "checkpoint_driver")
    check_checkpoint_process(binaries / "checkpoint_driver", binaries / "checkpoint_process")
    check_backup(binaries / "backup_driver", binaries / "checkpoint_driver")
    check_backup_process(binaries / "backup_driver", binaries / "checkpoint_driver", binaries / "backup_process")
    check_migration(binaries / "migration_driver")
    check_migration_process(binaries / "migration_process")
    check_http(binaries / "registry_server")
    check_resources(binaries)
    print("PASS prebuilt database suite", flush=True)


if __name__ == "__main__": main()
