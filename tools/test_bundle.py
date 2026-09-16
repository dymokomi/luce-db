#!/usr/bin/env python3
"""Bundle only public test binaries/scripts for isolated second-host validation."""
import argparse
import hashlib
import io
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", type=Path, default=ROOT / "build/native3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    programs = ["tree", "writers", "storage_faults", "transactions", "bounds", "concurrency", "facade", "journal_driver", "registry_server", "checkpoints", "checkpoint_faults", "checkpoint_concurrency", "checkpoint_allocations", "checkpoint_driver", "checkpoint_process", "backups", "backup_faults", "backup_concurrency", "backup_allocations", "restore_faults", "backup_process", "backup_driver", "backup_race", "schemas", "migration_concurrency", "migration_allocations", "migration_faults", "migration_driver", "migration_process"]
    scripts = ["run_prebuilt.py", "check_http.py", "check_journal.py", "check_checkpoint.py", "check_checkpoint_process.py", "check_backup.py", "check_backup_process.py", "check_migration.py", "check_migration_process.py"]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = []
    with tarfile.open(args.output, "w:gz") as bundle:
        def add(name, data, mode=0o644):
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(data), mode
            bundle.addfile(item, io.BytesIO(data))
            manifest.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
        for name in programs: add(f"bin/{name}", (args.binaries / name).read_bytes(), 0o755)
        for name in scripts: add(f"tests/{name}", (ROOT / "tests" / name).read_bytes())
        for name in ["LICENSE", "LICENSE-MIT", "LICENSE-APACHE"]:
            add(name, (ROOT / name).read_bytes())
        add("REVISION", (revision + "\n").encode())
        add("SHA256SUMS", "".join(manifest).encode())
    print(f"{hashlib.sha256(args.output.read_bytes()).hexdigest()}  {args.output.name}", flush=True)


if __name__ == "__main__": main()
