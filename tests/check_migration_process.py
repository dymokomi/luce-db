"""Kill/reopen around schema publication. Version and records must match."""
import subprocess
import sys
import tempfile
from pathlib import Path

from check_journal import line


def stop(child):
    if child.poll() is None:
        child.kill()
    return child.communicate(timeout=10)


def inspect(process, path):
    result = subprocess.run([str(process), "inspect", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, (result.stdout, result.stderr)
    header, *keys = result.stdout.splitlines()
    kind, version, generation, count = header.split()
    assert kind == "SCHEMA"
    version, generation, count = int(version), int(generation), int(count)
    assert count == len(keys)
    items = [key for key in keys if key.startswith("item/")]
    if version < 0:
        assert generation == 0 and count == 0
    else:
        assert generation == version + 1
        assert "schema" in keys
        assert set(items) == {f"item/{i}" for i in range(1, version + 1)}
        assert count == 1 + version
    return version


def check(process):
    cases = 0
    with tempfile.TemporaryDirectory(prefix="luce-db-schema-process-") as tmp:
        path = Path(tmp) / "store.db"
        child = subprocess.Popen([str(process), "crash", str(path)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        try:
            assert line(child).startswith("INIT ")
            seen = 0
            for _ in range(5):
                ack = line(child)
                assert ack.startswith("ACK ")
                seen = int(ack.split()[1])
            assert seen >= 5
            cases += 1
        finally:
            stop(child)
        version = inspect(process, path)
        assert version >= seen
        cases += 1
        child = subprocess.Popen([str(process), "crash", str(path)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        try:
            ack = line(child)
            assert ack.startswith("ACK ")
            resumed = int(ack.split()[1])
            assert resumed == version + 1
        finally:
            stop(child)
        assert inspect(process, path) >= version
        cases += 1
    print(f"PASS {cases} schema process-kill/reopen cases with matching version and records", flush=True)


if __name__ == "__main__":
    check(Path(sys.argv[1]))
