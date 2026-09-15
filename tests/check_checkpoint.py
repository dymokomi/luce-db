"""Independent format-002 byte oracle; bounded corruption and checkpoint replay."""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

from check_journal import HEADER as LEGACY, frame

HEADER = b"LUCE-DB-WAL-002\n"


def run(driver, mode, path, success=True):
    result = subprocess.run([str(driver), mode, str(path)], capture_output=True, text=True, timeout=90)
    assert (result.returncode == 0) == success, (mode, path, result.returncode, result.stdout, result.stderr)
    return result.stdout


def row(key, value):
    prefix = struct.pack("<4sII", b"ROW2", len(key), len(value))
    data = prefix + struct.pack("<I", zlib.crc32(prefix)) + key + value
    return data + struct.pack("<I4s", zlib.crc32(data), b"END2")


def encode(generation, records, declared_count=None, declared_size=None):
    data = b"".join(row(key, value) for key, value in records)
    prefix = struct.pack("<4sQQQ", b"CKP2", generation,
                         len(records) if declared_count is None else declared_count,
                         len(data) if declared_size is None else declared_size)
    body = HEADER + prefix + struct.pack("<I", zlib.crc32(prefix)) + data
    footer = b"BASE-END" + struct.pack("<I", zlib.crc32(body))
    return body + footer + struct.pack("<I", zlib.crc32(footer))


def decode(data):
    assert data[:16] == HEADER and len(data) >= 64
    magic, generation, count, size, crc = struct.unpack_from("<4sQQQI", data, 16)
    assert magic == b"CKP2" and crc == zlib.crc32(data[16:44])
    assert generation <= 2**63 - 1 and count <= 1_000_000
    assert generation != 0 or count == 0
    assert size <= 268435456 - 64 and size >= count * 25 and size + 64 <= len(data)
    offset, state, last = 48, {}, None
    for _ in range(count):
        start = offset
        magic, key_size, value_size, prefix_crc = struct.unpack_from("<4sIII", data, offset)
        assert magic == b"ROW2" and prefix_crc == zlib.crc32(data[offset:offset + 12])
        assert 1 <= key_size <= 1024 and value_size <= 1048576
        offset += 16
        key = data[offset:offset + key_size]
        value = data[offset + key_size:offset + key_size + value_size]
        key.decode("utf-8")
        assert last is None or last < key
        assert len(value) == value_size
        offset += key_size + value_size
        assert struct.unpack_from("<I4s", data, offset) == (zlib.crc32(data[start:offset]), b"END2")
        offset += 8
        assert offset <= 48 + size
        state[key], last = value, key
    assert offset == 48 + size
    assert data[offset:offset + 8] == b"BASE-END"
    assert struct.unpack_from("<II", data, offset + 8) == (zlib.crc32(data[:offset]), zlib.crc32(data[offset:offset + 12]))
    return generation, state, offset + 16


def check(driver, full=False):
    cases = 0
    with tempfile.TemporaryDirectory(prefix="luce-db-checkpoint-oracle-") as tmp:
        directory = Path(tmp)
        original = directory / "original.db"
        run(driver, "write", original)
        assert original.read_bytes().startswith(LEGACY)
        records = sorted([(b"binary", b"new\0\xff"), (b"empty", b""),
                          ("unicode/猫".encode(), b"value"), (b"user/bob", b"Bob")])
        expected = encode(3, records)
        assert run(driver, "compact", original).startswith("CHECKPOINT 3\nSTATE 3 4\n")
        assert original.read_bytes() == expected, "native checkpoint differs from independent golden"
        assert decode(expected) == (3, dict(records), len(expected))
        run(driver, "compact", original)
        assert original.read_bytes() == expected, "repeated checkpoint is not deterministic"
        cases += 2
        for cut in range(len(expected)):
            path = directory / f"cut-{cut}.db"
            path.write_bytes(expected[:cut])
            run(driver, "read", path, False)
            assert path.read_bytes() == expected[:cut], "partial base was incorrectly repaired"
            cases += 1
        for offset in range(len(expected)):
            path = directory / f"corrupt-{offset}.db"
            damaged = bytearray(expected)
            damaged[offset] ^= 0x80
            path.write_bytes(damaged)
            run(driver, "read", path, False)
            assert path.read_bytes() == damaged
            cases += 1
        malformed = [encode(0, records), encode(2**63, []), encode(2**64 - 1, []),
                     encode(3, records, declared_count=0), encode(3, records, declared_count=5),
                     encode(3, records, declared_count=1_000_001),
                     encode(3, records, declared_count=2**64 - 1),
                     encode(3, records, declared_size=0), encode(3, records, declared_size=268435456),
                     encode(3, records, declared_size=2**64 - 1),
                     encode(3, records + records[:1]), encode(3, list(reversed(records))),
                     encode(1, [(b"", b"empty-key")]), encode(1, [(b"\xff", b"invalid-utf8")]),
                     encode(1, [(b"x" * 1025, b"overlong")]),
                     encode(1, [(b"x", bytes(1048577))])]
        # Checksum-valid bad lengths must be rejected before unbounded allocation.
        for key_size, value_size in [(2**32 - 1, 0), (1, 2**32 - 1)]:
            bad = bytearray(encode(1, [(b"x", b"y")]))
            struct.pack_into("<II", bad, 52, key_size, value_size)
            struct.pack_into("<I", bad, 60, zlib.crc32(bad[48:60]))
            malformed.append(bytes(bad))
        for index, bad in enumerate(malformed):
            path = directory / f"semantic-{index}.db"
            path.write_bytes(bad)
            run(driver, "read", path, False)
            assert path.read_bytes() == bad
            cases += 1
        suffix = frame(4, [(1, b"after", b"recovery")])
        for cut in range(len(suffix)):
            path = directory / f"tail-{cut}.db"
            path.write_bytes(expected + suffix[:cut])
            assert run(driver, "read", path) == "STATE 3 4\n"
            assert path.read_bytes() == expected
            assert run(driver, "append", path).startswith("COMMIT 4\nSTATE 4 5\n")
            assert path.read_bytes() == expected + suffix
            cases += 1
        appended = directory / "complete-tail.db"
        appended.write_bytes(expected + suffix)
        assert run(driver, "read", appended) == "STATE 4 5\n"
        run(driver, "compact", appended)
        assert appended.read_bytes() == encode(4, sorted(records + [(b"after", b"recovery")]))
        cases += 1
        for generation in [0, 1, 2**63 - 1]:
            path = directory / f"empty-{generation}.db"
            path.write_bytes(encode(generation, []))
            assert run(driver, "read", path) == f"STATE {generation} 0\n"
            run(driver, "compact", path)
            assert path.read_bytes() == encode(generation, [])
            if generation == 2**63 - 1:
                run(driver, "append", path, False)
                assert path.read_bytes() == encode(generation, [])
            cases += 1
        path = directory / "stream.db"
        run(driver, "large" if full else "quick", path)
        data = path.read_bytes()
        generation, state, end = decode(data)
        length, count = (1048576, 18) if full else (131073, 2)
        value = bytes(i % 251 for i in range(length))
        assert generation == count and state == {f"large/{i}".encode(): value for i in range(count)}
        assert end == len(data) and len(data) > (16777216 if full else 262144)
        assert run(driver, "read", path) == f"STATE {count} {count}\n"
        cases += 1
    print(f"PASS {cases} independent checkpoint golden/cut/corruption/semantic/tail/stream cases; full={full}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    check(args.driver.resolve(), args.full)
