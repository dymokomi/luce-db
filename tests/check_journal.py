"""Independent struct/zlib oracle: exhaustive final-frame cuts, corruption, kill/reopen."""
import os
from pathlib import Path
import selectors
import resource
import signal
import struct
import subprocess
import tempfile
import zlib

HEADER = b"LUCE-DB-WAL-001\n"


def run(driver, mode, path, succeeds=True):
    result = subprocess.run([str(driver), mode, str(path)], capture_output=True, text=True, timeout=20)
    assert (result.returncode == 0) == succeeds, (mode, path, result.returncode, result.stdout, result.stderr)
    return result.stdout


def line(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(15), "child readiness timed out"
    result = process.stdout.readline()
    assert result, (process.poll(), process.stderr.read().decode() if process.poll() is not None else "child closed stdout")
    return result.decode().strip()


def frame(generation, operations):
    payload = b"".join(struct.pack("<BII", kind, len(key), len(value)) + key + value
                       for kind, key, value in operations)
    prefix = struct.pack("<4sIQI", b"TXN1", len(payload), generation, len(operations))
    encoded = prefix + struct.pack("<I", zlib.crc32(prefix)) + payload
    return encoded + struct.pack("<I", zlib.crc32(encoded)) + b"END1"


def decode(data):
    assert data[:16] == HEADER
    offset, generation, state = 16, 0, {}
    while offset < len(data):
        start = offset
        magic, size, sequence, count = struct.unpack_from("<4sIQI", data, offset)
        assert magic == b"TXN1" and sequence == generation + 1
        assert struct.unpack_from("<I", data, offset + 20)[0] == zlib.crc32(data[offset:offset + 20])
        offset += 24
        end = offset + size
        for _ in range(count):
            kind, key_size, value_size = struct.unpack_from("<BII", data, offset)
            offset += 9
            key = data[offset:offset + key_size]
            offset += key_size
            value = data[offset:offset + value_size]
            offset += value_size
            assert key and key.decode("utf-8") and kind in (1, 2)
            if kind == 1:
                state[key] = value
            else:
                assert not value
                state.pop(key, None)
        assert offset == end
        assert struct.unpack_from("<I", data, offset)[0] == zlib.crc32(data[start:offset])
        assert data[offset + 4:offset + 8] == b"END1"
        offset += 8
        generation = sequence
    assert offset == len(data)
    return generation, state


def check(driver):
    with tempfile.TemporaryDirectory(prefix="luce-db-journal-") as tmp:
        directory = Path(tmp)
        original = directory / "original.db"
        run(driver, "write", original)
        first = frame(1, [(1, b"user/alice", b"Alice"), (1, b"binary", b"\0\xff\x7f")])
        second = frame(2, [(2, b"user/alice", b""), (1, b"user/bob", b"Bob")])
        expected = HEADER + first + second
        assert original.read_bytes() == expected, "journal differs from independent golden encoding"
        assert decode(expected) == (2, {b"binary": b"\0\xff\x7f", b"user/bob": b"Bob"})
        boundary = len(HEADER + first)
        for cut in range(len(second)):
            path = directory / f"cut-{cut}.db"
            path.write_bytes(expected[:boundary + cut])
            assert run(driver, "read", path).startswith("STATE 1 2\n")
            assert path.read_bytes() == expected[:boundary]
            run(driver, "append", path)
            assert decode(path.read_bytes())[0] == 2
        for position in range(len(expected)):
            path = directory / f"corrupt-{position}.db"
            damaged = bytearray(expected)
            damaged[position] ^= 0x80
            path.write_bytes(damaged)
            run(driver, "read", path, succeeds=False)
            assert path.read_bytes() == damaged, "corrupt complete record must not be repaired"
        # Valid checksums must not bypass semantic validation or sequence checks.
        malformed = [frame(3, [(1, b"x", b"y")]), frame(2, []),
                     frame(2, [(3, b"x", b"")]), frame(2, [(2, b"x", b"bad")]),
                     frame(2, [(1, b"", b"v")]), frame(2, [(1, b"\xff", b"v")]),
                     frame(2, [(1, b"x" * 1025, b"v")]),
                     frame(2, [(1, b"x", bytes(1048577))])]
        for index, bad_frame in enumerate(malformed):
            path = directory / f"semantic-{index}.db"
            path.write_bytes(HEADER + first + bad_frame)
            run(driver, "read", path, succeeds=False)
            assert path.read_bytes() == HEADER + first + bad_frame
        for cut in range(16):
            path = directory / f"header-{cut}.db"
            path.write_bytes(HEADER[:cut])
            run(driver, "read", path, succeeds=False)
        # Final symlinks, hard links, non-regular files, oversize journals.
        alias = directory / "alias.db"
        alias.symlink_to(original)
        run(driver, "read", alias, succeeds=False)
        hard = directory / "hard.db"
        os.link(original, hard)
        run(driver, "read", hard, succeeds=False)
        hard.unlink()
        fifo = directory / "fifo.db"
        os.mkfifo(fifo)
        run(driver, "read", fifo, succeeds=False)
        huge = directory / "huge.db"
        with huge.open("wb") as out:
            out.write(HEADER)
            out.truncate(268435457)
        run(driver, "read", huge, succeeds=False)
        owner = subprocess.Popen([str(driver), "hold", str(original)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert line(owner) == "READY"
            run(driver, "read", original, succeeds=False)
        finally:
            owner.kill()
            owner.communicate(timeout=10)
        assert run(driver, "read", original).startswith("STATE 2 2\n")
        def restrict_writes():
            signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(resource.RLIMIT_FSIZE, (96, 96))
        uncertain = directory / "uncertain.db"
        failure = subprocess.run([str(driver), "uncertain", str(uncertain)], capture_output=True,
                                 text=True, timeout=20, preexec_fn=restrict_writes)
        assert failure.returncode == 0, (failure.stdout, failure.stderr)
        assert "PASS uncertain" in failure.stdout
        assert run(driver, "read", uncertain).startswith("STATE 0 0\n")
        # Killing a process is not a power-loss test. Every observed ACK must survive;
        # complete but unacknowledged transactions may legitimately survive too.
        for trial in range(4):
            path = directory / f"crash-{trial}.db"
            process = subprocess.Popen([str(driver), "crash", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            ack = 0
            try:
                for _ in range(10 + trial * 7):
                    response = line(process)
                    assert response.startswith("ACK "), response
                    ack = int(response.split()[1])
            finally:
                process.kill()
                process.communicate(timeout=10)
            run(driver, "read", path)
            generation, state = decode(path.read_bytes())
            assert generation >= ack
            assert len(state) == generation + 1
            assert all(state[f"commit/{i}".encode()] == b"durable" for i in range(generation))
            assert state[b"last"] == f"commit/{generation - 1}".encode()
        cases = len(second) + len(expected) + len(malformed) + 16 + 11
        print(f"PASS {cases} journal golden/cut/corruption/ownership/crash cases", flush=True)
