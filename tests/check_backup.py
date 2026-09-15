"""Independent strict-backup oracle; no production inputs or external DB runtime."""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

from check_checkpoint import encode, decode, run as journal_run
from check_journal import HEADER as LEGACY, frame


def run(driver, mode, source, target=None, success=True):
    command = [str(driver), mode, str(source)]
    if target is not None:
        command.append(str(target))
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert (result.returncode == 0) == success, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout


def check(driver, journal_driver, full=False):
    cases = 0
    with tempfile.TemporaryDirectory(prefix="luce-db-backup-oracle-") as tmp:
        directory = Path(tmp)
        source, exported, restored = [directory / n for n in ("source.db", "backup", "restored.db")]
        journal_run(journal_driver, "write", source)
        original = source.read_bytes()
        assert original.startswith(LEGACY)
        records = sorted([(b"binary", b"new\0\xff"), (b"empty", b""),
                          ("unicode/猫".encode(), b"value"), (b"user/bob", b"Bob")])
        expected = encode(3, records)
        answer = f"BACKUP 3 4 {len(expected)}\n"
        assert run(driver, "export", source, exported) == answer
        assert source.read_bytes() == original and exported.read_bytes() == expected
        exported.chmod(0o400)
        before = exported.stat()
        assert run(driver, "verify", exported) == answer
        assert run(driver, "restore", exported, restored) == answer
        assert restored.read_bytes() == expected and source.read_bytes() == original
        assert restored.stat().st_mode & 0o777 == 0o600
        assert exported.stat().st_mtime_ns == before.st_mtime_ns
        assert exported.stat().st_ctime_ns == before.st_ctime_ns
        assert exported.stat().st_mode == before.st_mode
        journal_run(journal_driver, "append", restored)
        assert restored.read_bytes() == expected + frame(4, [(1, b"after", b"recovery")])
        run(driver, "verify", restored, success=False)
        journal_run(journal_driver, "compact", restored)
        assert run(driver, "verify", restored).startswith("BACKUP 4 5 ")
        cases += 5

        bad_inputs = [expected[:cut] for cut in range(len(expected))]
        for index in range(len(expected)):
            bad = bytearray(expected)
            bad[index] ^= 0x80
            bad_inputs.append(bytes(bad))
        bad_inputs += [LEGACY, original, expected + b"\0", expected + expected,
                       expected + frame(4, [(1, b"after", b"recovery")]),
                       encode(0, records), encode(2**63, []), encode(2**64 - 1, []),
                       encode(3, records, declared_count=0), encode(3, records, declared_count=5),
                       encode(3, records, declared_count=1_000_001),
                       encode(3, records, declared_count=2**64-1),
                       encode(3, records, declared_size=0), encode(3, records, declared_size=268435456),
                       encode(3, records, declared_size=2**64-1),
                       encode(3, records + records[:1]), encode(3, list(reversed(records))),
                       encode(1, [(b"", b"bad")]), encode(1, [(b"\xff", b"bad")]),
                       encode(1, [(b"x" * 1025, b"bad")]), encode(1, [(b"x", bytes(1048577))])]
        for key_size, value_size in [(2**32-1, 0), (1, 2**32-1)]:
            bad = bytearray(encode(1, [(b"x", b"y")]))
            struct.pack_into("<II", bad, 52, key_size, value_size)
            struct.pack_into("<I", bad, 60, zlib.crc32(bad[48:60]))
            bad_inputs.append(bytes(bad))
        # No input sidecar, output lock, repaired source or partial destination.
        invalid, absent = directory / "invalid", directory / "must-not-exist"
        for bad in bad_inputs:
            invalid.write_bytes(bad)
            names = set(directory.iterdir())
            stat = invalid.stat()
            run(driver, "verify", invalid, success=False)
            run(driver, "restore", invalid, absent, success=False)
            assert not absent.exists() and invalid.read_bytes() == bad
            assert set(directory.iterdir()) == names
            assert invalid.stat().st_mtime_ns == stat.st_mtime_ns
            assert invalid.stat().st_ctime_ns == stat.st_ctime_ns
            cases += 1

        # Every existing namespace entry is preserved, including dangling symlinks.
        sentinel = directory / "sentinel"
        sentinel.write_bytes(b"unrelated destination")
        alias = directory / "alias"
        alias.symlink_to(sentinel)
        dangling = directory / "dangling"
        dangling.symlink_to(directory / "missing")
        folder = directory / "folder"
        folder.mkdir()
        fifo = directory / "fifo"
        os.mkfifo(fifo)
        for target in [source, exported, sentinel, alias, dangling, folder, fifo]:
            run(driver, "export", source, target, success=False)
            run(driver, "restore", exported, target, success=False)
            assert sentinel.read_bytes() == b"unrelated destination"
            assert source.read_bytes() == original and exported.read_bytes() == expected
            assert alias.is_symlink() and dangling.is_symlink() and fifo.is_fifo()
            cases += 1
        input_alias = directory / "input-alias"
        input_alias.symlink_to(exported)
        for candidate in [input_alias, dangling, folder, fifo, directory / "missing"]:
            run(driver, "verify", candidate, success=False)
            run(driver, "restore", candidate, absent, success=False)
            assert not absent.exists()
            cases += 1
        hardlink = directory / "hardlink"
        os.link(exported, hardlink)
        for candidate in [hardlink, exported]:
            run(driver, "verify", candidate, success=False)
            run(driver, "restore", candidate, absent, success=False)
            cases += 1
        hardlink.unlink()
        assert run(driver, "verify", exported) == answer
        for generation in [0, 1, 2**63-1]:
            blank, target = directory / f"empty-{generation}", directory / f"restored-{generation}"
            blank.write_bytes(encode(generation, []))
            assert run(driver, "verify", blank) == f"BACKUP {generation} 0 64\n"
            assert run(driver, "restore", blank, target) == f"BACKUP {generation} 0 64\n"
            assert target.read_bytes() == blank.read_bytes()
            assert not blank.with_name(blank.name + ".lock").exists()
            cases += 1

        large, copy, restore = [directory / n for n in ("large.db", "large.backup", "large.restored")]
        journal_run(journal_driver, "large" if full else "quick", large)
        original = large.read_bytes()
        assert run(driver, "export", large, copy) == run(driver, "verify", copy)
        assert run(driver, "restore", copy, restore) == run(driver, "verify", restore)
        assert large.read_bytes() == copy.read_bytes() == restore.read_bytes() == original
        generation, state, end = decode(original)
        assert end == len(original) and generation == len(state) == (18 if full else 2)
        assert len(original) > (16777216 if full else 262144)
        cases += 1
    print(f"PASS {cases} independent strict backup/restore cases; full={full}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("journal_driver", type=Path)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    check(args.driver.resolve(), args.journal_driver.resolve(), args.full)
