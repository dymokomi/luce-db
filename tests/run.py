#!/usr/bin/env python3
"""Compile and run the Prism-backed database server tests."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["native0", "native1", "native2", "native3", "c", "c-release", "all"], default="all")
    parser.add_argument("--base", type=Path, default=Path(os.environ.get("LUCE_BASE_COMPILER", ROOT / "build/toolchain/luce-base")))
    parser.add_argument("--luce", type=Path, default=Path(os.environ.get("LUCE_COMPILER", ROOT / "build/toolchain/luce")))
    args = parser.parse_args()
    if not args.base.is_file():
        raise SystemExit(f"compiler not found: {args.base}")
    if not args.luce.is_file():
        raise SystemExit(f"compiler not found: {args.luce}")
    environment = dict(os.environ, LUCE_BASE=str(args.base.resolve()))
    environment.setdefault("LUCE_STD", str(ROOT.parent / "luce-base/src/std"))
    environment.setdefault("LUCE_CACHE", str(ROOT / "build/cache"))
    modes = {f"native{i}": ["--native", "--opt", str(i)] for i in range(4)}
    modes.update({"c": ["--backend=c"], "c-release": ["--backend=c", "--release"]})
    selected = modes if args.mode == "all" else {args.mode: modes[args.mode]}

    def run(command):
        print("RUN", " ".join(str(arg) for arg in command), flush=True)
        # High-level bindings and optimized C compilation need more time than
        # the runtime fixtures on hosted CPUs. Keep both phases bounded.
        timeout = 600 if len(command) > 1 and command[1] == "build" else 180
        subprocess.run([str(arg) for arg in command], cwd=ROOT, env=environment, check=True, timeout=timeout)

    for mode, flags in selected.items():
        print(f"MODE {mode}", flush=True)
        output = ROOT / "build" / mode
        output.mkdir(parents=True, exist_ok=True)
        run([args.base.resolve(), "build", ROOT / "tests/server.lucb", *flags, "-o", output / "server"])
        run([args.base.resolve(), "build", ROOT / "tests/tls.lucb", *flags, "-o", output / "tls"])
        run([args.luce.resolve(), "build", ROOT / "tests/facade.luc", *flags, "-o", output / "facade"])
        with tempfile.TemporaryDirectory(prefix="luce-db-tests-") as tmp:
            run([output / "server", Path(tmp) / "server.db"])
            run([output / "tls", Path(tmp) / "tls.db"])
            run([output / "facade", Path(tmp) / "facade.db"])
        print(f"PASS {mode}", flush=True)
    print(f"PASS all {len(selected)} selected compiler modes", flush=True)


if __name__ == "__main__":
    main()
