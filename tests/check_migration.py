"""Independent schema-metadata oracle. No production inputs or foreign DB engine."""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

MAGIC = b"LDSM"


def encode(application, version):
    app = application.encode()
    assert 1 <= len(app) <= 256
    return MAGIC + bytes([1]) + struct.pack("<H", len(app)) + app + struct.pack("<Q", version)


def decode(data, application):
    app = application.encode()
    assert data[:4] == MAGIC and data[4] == 1
    length = struct.unpack_from("<H", data, 5)[0]
    stored = data[7:7 + length]
    version = struct.unpack_from("<Q", data, 7 + length)[0]
    assert stored == app and 7 + length + 8 == len(data) and version <= 2**63 - 1
    return version


def run(driver, *args, success=True):
    result = subprocess.run([str(driver), *args], capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) == success, (args, result.returncode, result.stdout, result.stderr)
    return result.stdout


def driver_bytes(driver, application, version):
    lines = run(driver, "encode", application, str(version)).splitlines()
    assert lines[0].startswith("BYTES ")
    count = int(lines[0].split()[1])
    values = [int(line) for line in lines[1:]]
    assert len(values) == count
    return bytes(values)


def check(driver):
    cases = 0
    for application, version in [("app", 0), ("app", 1), ("registry", 2**32), ("猫", 7)]:
        expected = encode(application, version)
        assert driver_bytes(driver, application, version) == expected
        assert decode(expected, application) == version
        cases += 1
    with tempfile.TemporaryDirectory(prefix="luce-db-schema-") as tmp:
        path = Path(tmp) / "store.db"
        assert run(driver, "init", path, "app") == "INIT 1\n"
        assert run(driver, "schema", path, "app") == "SCHEMA 0 1\n"
        assert run(driver, "migrate", path, "0", "app", "user/alice", "Alice") == "COMMIT 2\n"
        assert run(driver, "schema", path, "app") == "SCHEMA 1 2\n"
        run(driver, "migrate", path, "0", "app", "user/bob", "Bob", success=False)
        run(driver, "schema", path, "other", success=False)
        cases += 4
    print(f"PASS {cases} independent schema metadata encodings and driver steps", flush=True)


if __name__ == "__main__":
    check(Path(sys.argv[1]))
