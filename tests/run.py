#!/usr/bin/env python3
"""Compile fresh binaries and run native opt 0-3 / C debug-release gates."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

from check_http import check as check_http
from check_journal import check as check_journal
from check_checkpoint import check as check_checkpoint
from check_checkpoint_process import check as check_checkpoint_process

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["native0", "native1", "native2", "native3", "c", "c-release", "all"], default="all")
    parser.add_argument("--base", type=Path, default=ROOT / "build/toolchain/luce-base")
    parser.add_argument("--luce", type=Path, default=ROOT / "build/toolchain/luce")
    args = parser.parse_args()
    for tool in (args.base, args.luce):
        if not tool.is_file(): raise SystemExit("Run python3 tools/bootstrap.py first, or supply --base and --luce")
    server_pin = (ROOT / "bootstrap/SERVER").read_text().strip()
    server_head = subprocess.check_output(["git", "-C", str(ROOT.parent / "luce-server"), "rev-parse", "HEAD"], text=True).strip()
    if server_head != server_pin: raise SystemExit(f"luce-server pin mismatch: {server_head}")
    environment = dict(os.environ, LUCE_BASE=str(args.base.resolve()))
    modes = {f"native{i}": ["--native", "--opt", str(i)] for i in range(4)}
    modes.update({"c": ["--backend=c"], "c-release": ["--backend=c", "--release"]})
    selected = modes if args.mode == "all" else {args.mode: modes[args.mode]}

    def run(command):
        subprocess.run([str(arg) for arg in command], cwd=ROOT, env=environment, check=True, timeout=180)

    for mode, flags in selected.items():
        start = time.monotonic()
        print(f"MODE {mode}", flush=True)
        output = ROOT / "build" / mode
        output.mkdir(parents=True, exist_ok=True)
        programs = [(ROOT / "src/luce_db/tree_tests.lucb", "tree")]
        programs += [(ROOT / "src/luce_db/writer_tests.lucb", "writers")]
        programs += [(ROOT / "src/luce_db/storage_fault_tests.lucb", "storage_faults")]
        programs += [(ROOT / f"src/luce_db/{source}.lucb", name) for source, name in [
            ("checkpoint_tests", "checkpoints"), ("checkpoint_fault_tests", "checkpoint_faults"),
            ("checkpoint_concurrency", "checkpoint_concurrency"), ("checkpoint_allocations", "checkpoint_allocations"),
            ("checkpoint_process", "checkpoint_process")]]
        programs += [(ROOT / f"tests/{name}.lucb", name) for name in ["transactions", "bounds", "concurrency", "journal_driver", "registry_server"]]
        programs += [(ROOT / "tests/checkpoint_driver.lucb", "checkpoint_driver")]
        for source, name in programs:
            run([args.base.resolve(), "build", source, *flags, "-o", output / name])
        run([args.luce.resolve(), "build", ROOT / "tests/facade.luc", *flags, "-o", output / "facade"])
        with tempfile.TemporaryDirectory(prefix="luce-db-tests-") as tmp:
            run([output / "tree"])
            run([output / "writers"])
            for name in ["transactions", "bounds", "concurrency", "facade", "storage_faults", "checkpoints", "checkpoint_faults", "checkpoint_concurrency", "checkpoint_allocations"]:
                run([output / name, Path(tmp) / f"{name}.db"])
            run([output / "concurrency", Path(tmp) / "concurrency-wait.db", "wait"])
        check_journal(output / "journal_driver")
        check_checkpoint(output / "checkpoint_driver")
        check_checkpoint_process(output / "checkpoint_driver", output / "checkpoint_process")
        check_http(output / "registry_server")
        print(f"PASS {mode} ({time.monotonic() - start:.1f}s)", flush=True)
    print(f"PASS all {len(selected)} selected compiler modes", flush=True)


if __name__ == "__main__": main()
