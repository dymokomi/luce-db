#!/usr/bin/env python3
"""Memory/undefined-behavior checks on the Base compiler's generated C backend."""
import os
from pathlib import Path
import subprocess
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
        for name in ["transactions", "bounds", "concurrency"]:
            generated = output / f"{name}.c"
            executable = output / name
            run([base, "build", ROOT / f"tests/{name}.lucb", "--emit=c", "-o", generated])
            run([os.environ.get("CC", "cc"), "-std=gnu11", "-O1", "-g", "-w", "-fno-strict-aliasing",
                 "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-I", runtime,
                 generated, runtime / "lucb_rt.c", "-pthread", "-lm", "-o", executable])
            run([executable, Path(tmp) / f"{name}.db"])
    print("PASS address/undefined-behavior sanitizers: transactions, bounds, 8-thread updates", flush=True)


if __name__ == "__main__": main()
