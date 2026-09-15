"""Observed-phase process termination, file identity and moved-parent fixtures."""
import os
import argparse
from pathlib import Path
import subprocess
import tempfile

from check_journal import line, HEADER as LEGACY
from check_checkpoint import run, decode, HEADER


def check(driver, process_driver):
    phases = ["create", "write", "file_sync", "rename_before", "rename_after", "directory_sync", "close", "returned"]
    cases = 0
    with tempfile.TemporaryDirectory(prefix="luce-db-checkpoint-process-") as tmp:
        root = Path(tmp)
        for phase in phases:
            directory = root / phase
            directory.mkdir()
            path = directory / "test.db"
            run(driver, "write", path)
            old = path.read_bytes()
            lock_inode = Path(str(path) + ".lock").stat().st_ino
            child = subprocess.Popen([str(process_driver), phase, str(path)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            try:
                assert line(child) == f"PHASE {phase}"
                run(driver, "read", path, False)  # Ownership persists across rename.
                assert Path(str(path) + ".lock").stat().st_ino == lock_inode
            finally:
                child.kill()
                child.communicate(timeout=10)
            if phase in phases[:4]:
                assert path.read_bytes() == old
                assert old.startswith(LEGACY)
            else:
                generation, state, end = decode(path.read_bytes())
                assert generation == 3 and len(state) == 4 and end == path.stat().st_size
            assert run(driver, "read", path) == "STATE 3 4\n"
            run(driver, "compact", path)
            assert path.read_bytes().startswith(HEADER)
            assert run(driver, "append", path).startswith("COMMIT 4\n")
            cases += 1
        before = root / "parent-before"
        before.mkdir()
        path = before / "test.db"
        run(driver, "write", path)
        child = subprocess.Popen([str(process_driver), "relocate", str(path)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        after = root / "parent-after"
        try:
            assert line(child) == "PHASE relocate"
            before.rename(after)
            out, err = child.communicate(b"x", timeout=30)
            assert child.returncode == 0 and b"PASS process checkpoint" in out, (out, err)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
        assert not before.exists()
        assert run(driver, "read", after / "test.db") == "STATE 3 4\n"
        assert (after / "test.db").read_bytes().startswith(HEADER)
        cases += 1
        for mutation in ["replace", "symlink", "hardlink", "append"]:
            directory = root / mutation
            directory.mkdir()
            path = directory / "test.db"
            run(driver, "write", path)
            original = path.read_bytes()
            child = subprocess.Popen([str(process_driver), "identity", str(path)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            try:
                assert line(child) == "PHASE identity"
                if mutation in ("replace", "symlink"):
                    path.rename(directory / "saved.db")
                    if mutation == "replace": path.write_bytes(b"unrelated replacement")
                    else:
                        sentinel = directory / "sentinel"
                        sentinel.write_bytes(b"unrelated symlink target")
                        path.symlink_to(sentinel)
                elif mutation == "hardlink": os.link(path, directory / "alias")
                else:
                    with path.open("ab") as stream: stream.write(b"unexpected append")
                out, err = child.communicate(b"x", timeout=30)
                assert child.returncode == 0 and b"PASS identity mismatch" in out, (out, err)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=10)
            assert not list(directory.glob(".luce-db-*")), "identity rejection created temporary output"
            if mutation == "replace": assert path.read_bytes() == b"unrelated replacement"
            elif mutation == "symlink": assert path.is_symlink() and sentinel.read_bytes() == b"unrelated symlink target"
            elif mutation == "hardlink": assert path.read_bytes() == original
            else: assert path.read_bytes() == original + b"unexpected append"
            if mutation in ("replace", "symlink"): assert (directory / "saved.db").read_bytes() == original
            cases += 1
        mode_path = root / "mode.db"
        run(driver, "write", mode_path)
        mode_path.chmod(0o644)
        run(driver, "compact", mode_path)
        assert mode_path.stat().st_mode & 0o777 == 0o600
        cases += 1
    assert cases == 14
    print("PASS 14 checkpoint observed-phase kill, lock, moved-parent, changed-identity and private-mode cases", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("driver", type=Path)
    parser.add_argument("process_driver", type=Path)
    args = parser.parse_args()
    check(args.driver.resolve(), args.process_driver.resolve())
