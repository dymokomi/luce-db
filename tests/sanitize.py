#!/usr/bin/env python3
"""Memory/undefined-behavior checks on the Base compiler's generated C backend."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = ROOT / "build/toolchain/luce-base"
    runtime = ROOT.parent / "luce-base/runtime"
    output = ROOT / "build/sanitizers"
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, ASAN_OPTIONS="halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")

    def run(command):
        subprocess.run([str(arg) for arg in command], cwd=ROOT, env=environment, check=True, timeout=180)

    with tempfile.TemporaryDirectory(prefix="luce-db-sanitizers-") as tmp:
        for name in ["transactions", "bounds", "concurrency", "writers", "storage_faults", "checkpoints", "checkpoint_faults", "checkpoint_concurrency", "checkpoint_allocations", "checkpoint_driver", "checkpoint_process", "backups", "backup_faults", "backup_concurrency", "backup_allocations", "restore_faults", "backup_process", "backup_driver", "backup_race", "schemas", "migration_concurrency", "migration_allocations", "migration_faults", "migration_driver", "migration_process"]:
            generated = output / f"{name}.c"
            executable = output / name
            source = ROOT / "src/luce_db/writer_tests.lucb" if name == "writers" else ROOT / f"tests/{name}.lucb"
            if name == "storage_faults": source = ROOT / "src/luce_db/storage_fault_tests.lucb"
            internal = {"checkpoints": "checkpoint_tests", "checkpoint_faults": "checkpoint_fault_tests",
                        "checkpoint_concurrency": "checkpoint_concurrency", "checkpoint_allocations": "checkpoint_allocations",
                        "checkpoint_process": "checkpoint_process", "backups": "backup_tests",
                        "backup_faults": "backup_fault_tests", "backup_concurrency": "backup_concurrency",
                        "backup_allocations": "backup_allocations", "restore_faults": "restore_fault_tests",
                        "backup_process": "backup_process", "backup_race": "backup_race",
                        "schemas": "schema_tests", "migration_concurrency": "migration_concurrency",
                        "migration_allocations": "migration_allocations", "migration_faults": "migration_fault_tests",
                        "migration_process": "migration_process", "migration_driver": "schema_driver"}
            if name in internal: source = ROOT / f"src/luce_db/{internal[name]}.lucb"
            run([base, "build", source, "--emit=c", "-o", generated])
            run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-w", "-fno-strict-aliasing",
                 "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", runtime,
                 generated, runtime / "lucb_rt.c", "-pthread", "-lm", "-o", executable])
            if name not in ("checkpoint_driver", "checkpoint_process", "backup_driver", "backup_process",
                            "migration_driver", "migration_process"):
                run([executable, Path(tmp) / f"{name}.db"])
            if name == "concurrency": run([executable, Path(tmp) / "concurrency-wait.db", "wait"])
        run([sys.executable, ROOT / "tests/check_checkpoint.py", output / "checkpoint_driver"])
        run([sys.executable, ROOT / "tests/check_checkpoint_process.py", output / "checkpoint_driver", output / "checkpoint_process"])
        run([sys.executable, ROOT / "tests/check_backup.py", output / "backup_driver", output / "checkpoint_driver"])
        run([sys.executable, ROOT / "tests/check_backup_process.py", output / "backup_driver", output / "checkpoint_driver", output / "backup_process"])
        run([sys.executable, ROOT / "tests/check_migration.py", output / "migration_driver"])
        run([sys.executable, ROOT / "tests/check_migration_process.py", output / "migration_process"])
    print("PASS address/undefined-behavior sanitizers: previous suites plus checkpoint/backup/schema native/fault/worker/allocation/oracle/process cases", flush=True)


if __name__ == "__main__": main()
