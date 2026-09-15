"""Observed-process backup publication, ownership and immutable-input policy tests."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

from check_journal import line
from check_checkpoint import encode, run as journal_run
from check_backup import run


def stop(child):
    if child.poll() is None:
        child.kill()
    return child.communicate(timeout=10)


def spawn(process, mode, phase, source, target):
    return subprocess.Popen([str(process), mode, phase, str(source), str(target)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, bufsize=0)


def check(driver, journal_driver, process):
    cases = 0
    phases = ["create", "write", "file_sync", "rename_before", "rename_after",
              "directory_sync", "close", "returned"]
    with tempfile.TemporaryDirectory(prefix="luce-db-backup-process-") as tmp:
        root = Path(tmp)
        expected = encode(3, [(b"key", b"value")])
        for mode in ["export", "restore"]:
            for phase in phases:
                directory = root / f"{mode}-{phase}"
                directory.mkdir()
                source, target = directory / "source", directory / "target"
                source.write_bytes(expected)
                child = spawn(process, mode, phase, source, target)
                try:
                    assert line(child) == f"PHASE {phase}"
                    if phase != "returned":
                        journal_run(journal_driver, "read", target, False)
                    else:
                        assert run(driver, "verify", target) == f"BACKUP 3 1 {len(expected)}\n"
                finally:
                    stop(child)
                published = phase in ["rename_after", "directory_sync", "returned"] or (phase == "close" and mode == "export")
                assert target.exists() == published
                assert source.read_bytes() == expected
                if not published:
                    run(driver, mode, source, target)
                assert target.read_bytes() == expected
                assert run(driver, "verify", target) == f"BACKUP 3 1 {len(expected)}\n"
                assert journal_run(journal_driver, "append", target).startswith("COMMIT 4\n")
                cases += 1

        # Existing output added after preflight must still never be replaced.
        source = root / "collision-source"
        source.write_bytes(expected)
        target = root / "collision-target"
        child = spawn(process, "restore", "rename_before", source, target)
        try:
            assert line(child) == "PHASE rename_before"
            target.write_bytes(b"unrelated late destination")
            out, err = child.communicate(b"x", timeout=30)
            assert child.returncode != 0, (out, err)
        finally:
            stop(child)
        assert target.read_bytes() == b"unrelated late destination"
        assert source.read_bytes() == expected
        cases += 1

        # Directory-relative publication survives a renamed output parent.
        before, after = root / "before", root / "after"
        before.mkdir()
        child = spawn(process, "restore", "create", source, before / "target")
        try:
            assert line(child) == "PHASE create"
            before.rename(after)
            out, err = child.communicate(b"x", timeout=30)
            assert child.returncode == 0 and b"PASS process backup" in out, (out, err)
        finally:
            stop(child)
        assert not before.exists() and (after / "target").read_bytes() == expected
        cases += 1

        # Detect changes while validating and between validation and copying.
        for phase in ["read", "create"]:
            for mutation in ["replace", "symlink", "hardlink", "append", "valid-rewrite"]:
                directory = root / f"mutation-{phase}-{mutation}"
                directory.mkdir()
                source, target = directory / "source", directory / "target"
                source.write_bytes(expected)
                child = spawn(process, "restore", phase, source, target)
                try:
                    assert line(child) == f"PHASE {phase}"
                    if mutation in ["replace", "symlink"]:
                        source.rename(directory / "saved")
                        if mutation == "replace": source.write_bytes(b"replacement sentinel")
                        else: source.symlink_to(directory / "saved")
                    elif mutation == "hardlink": os.link(source, directory / "alias")
                    elif mutation == "append":
                        with source.open("ab") as stream: stream.write(b"x")
                    else: source.write_bytes(encode(3, [(b"key", b"other")]))
                    changed = source.read_bytes()
                    out, err = child.communicate(b"x", timeout=30)
                    assert child.returncode != 0, (phase, mutation, out, err)
                finally:
                    stop(child)
                assert not target.exists() and source.read_bytes() == changed
                assert not list(directory.glob(".luce-backup-*"))
                cases += 1
    assert cases == 28
    print("PASS 28 backup/restore observed-phase kill, ownership, no-overwrite, moved-parent and input-mutation cases", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("journal_driver", type=Path)
    parser.add_argument("process", type=Path)
    args = parser.parse_args()
    check(args.driver.resolve(), args.journal_driver.resolve(), args.process.resolve())
