# Native snapshot backups and verified restore

Experimental API and format; no foreign storage/cryptographic engine. A backup is
a standalone complete [format-002 base](CHECKPOINTS.md), not a WAL copy or a live
directory copy. Its generation is preserved, including empty nonzero generations.
CRC checks detect accidental corruption; they are not signatures or authentication.

## API

```luce
from db import Database, verify_backup, restore_backup

pub func main() -> int!:
    let database = Database("registry.db")
    let info = database.backup("registry.backup")  # must be a new destination
    assert(verify_backup("registry.backup").generation == info.generation)
    let restored = restore_backup("registry.backup", "restored.db")
    assert(restored.generation == info.generation)
    database.close()
    return 0
```

Each operation returns `BackupInfo` with `generation`, `records` and exact encoded
`bytes` as integers. This does not return an open database; open `Database` on the
restored file normally. Do not use the existing `Database(path)` constructor to
validate an untrusted backup: ordinary open may create a missing file and recovery
can discard a torn WAL tail. The strict backup reader never does either.

`Database.backup(path)` retains one committed immutable snapshot through encoding
and publication. It counts against the existing 1,024-view limit. The source's
writer queue is not held during export I/O, so commits/checkpoints can continue;
an export never checkpoints or appends to its source. It remains exactly the
captured generation, not the generation at return. Source storage uncertainty
prevents new snapshot acquisition. Destination failures do not poison the source.
As with other native/managed handles, do not close the same facade concurrently
with calls on it. The retained engine/root are released on all return paths.

`verify_backup(path)` opens the input read-only, without creating a lock/sidecar,
syncing, truncating, repairing or rewriting it. It checks the complete versioned
base, record/count/size bounds, key order/UTF-8, checksums, footer and exact EOF.
Even a valid appended transaction or one extra byte is rejected. It does not
instantiate a second AVL index. File reads may update OS access-time metadata.

`restore_backup(input, destination)` first validates the whole input, before
creating destination files. It then copies through bounded buffers into a private
temporary file, checks the input's identity/size/modification/status times against
the initial verification, closes the input, syncs and independently validates the
prepared output, then publishes to a new destination. Opening/committing/checkpointing
the result uses the normal database API. Existing-store replacement, service cutover,
rollback and backup retention/transfer are separate operator workflows.

## Publication, ownership and failures

Parents must already exist. Final input/output symlinks are refused; input files
must be regular with one hard link. The immediate parent is opened without following
a final symlink; intermediate directory symlinks retain the platform's normal
resolution semantics. These are trusted operator-controlled directories, not a
hostile filesystem sandbox. Network filesystems and concurrent external mutation
are unsupported. Metadata/identity checks detect the tested modifications, not all
adversarial TOCTOU or checksum-collision attacks. Inputs must remain immutable
through validation/copy; no input-side advisory-lock protocol is imposed.

Destination preparation holds its persistent `.lock` sidecar exclusively using
the same lock convention as ordinary database open. It refuses nonregular/multiply
linked lock files, a changed lock identity and every existing destination entry,
including a dangling symlink. No lock file is removed on completion or failure:
deleting a shared lock pathname could create an ownership race. A valid restore
input can therefore leave an empty destination lock even when later work fails.
Lock creation opens an existing file or attempts exclusive creation, retrying at
most 128 creation collisions. This avoids the observed concurrent nonexclusive
`O_CREAT`/`ENOENT` race without deleting lock files or retrying arbitrary I/O errors.
Ordinary journal open uses the same helper. Existing sidecars must be readable and
writable by the owner; fresh sidecars still request private mode 0600.

An exclusive OS-random temporary sibling is created with requested mode 0600,
with at most 128 collision attempts. Publication retains the open descriptor and
uses directory-relative atomic no-replace rename: Linux `renameat2` with
`RENAME_NOREPLACE`, or macOS `renameatx_np` with `RENAME_EXCL`. There is no fallback
to a check-then-overwrite rename on unsupported platforms/filesystems.
[Linux rename semantics](https://man7.org/linux/man-pages/man2/rename.2.html) and
[Apple declarations and flags](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/stdio.h).

After publication, verify the output pathname's identity, sync the containing
directory and close the output descriptor before reporting success. The file and
directory sync durability model and device/power-loss exclusions are the same as
[checkpoint publication](CHECKPOINTS.md#publication-and-failure-contract). Requests
for mode 0600 are subject to umask; original ownership, ACLs and xattrs are not copied.
These are plaintext backup files, not encrypted credential archives.

Failures known to precede publication leave no final backup and preserve the source.
A late destination collision reports `files.already_exists` and preserves the
existing entry. Other errors after an attempted rename, or directory-sync/close
errors after publication, report `db.uncertain`: a complete output may exist, but
durability was not acknowledged. Do not blindly retry or call this a rollback.
Inspect the exact destination with the strict verifier; an existing name is never
overwritten on retry. Verification proves structure, not that an earlier failed
directory-sync barrier has now completed or that a backup has trusted provenance.

Error cleanup removes only a temporary pathname still identifying its open file;
the original error wins if cleanup fails. Process death or cleanup failure can
leave an orphan. No orphan is auto-promoted or broadly deleted. Investigate under
exclusive operator ownership. Temporary input/output test fixtures are disposable;
these cleanup rules do not authorize deleting real backup files or live data.

## Buffering and test scope

Encoding uses the checkpoint's 65,536-byte buffer and bounded traversal stack.
Copying uses one 65,536-byte buffer. Strict verification retains the current
key/value record and previous key, not all records or a decoded tree. Buffer
capacity growth can transiently retain old plus new allocations; each is bounded
by the maximum key/value sizes. This is bounded auxiliary buffering, not aggregate
memory or process RSS: exporting a snapshot can retain old source-tree versions
while writers continue, and callers still need aggregate admission limits.

The test gates retain every previous DB suite and add:

- Native and actual Luce round trips, source-byte preservation, retained views,
  binary/empty/UTF-8 values, empty/extreme generations and subsequent commits.
- 452 independent strict-format/restore scenarios, with both verify and restore
  rejecting every small-fixture truncation and byte corruption, semantic-invalid
  checksummed records, malformed sizes, legacy journals and appended tails.
  Input bytes/timestamps and absence of partial destinations are checked.
- 118 export entropy/create/read/write/verify/sync/publication/close/cleanup/
  collision cases, including all 95 write cuts in the 94-byte fixture, short/invalid
  transfers, owned orphan cleanup, source health and successful retries.
- 48 restore failures before/after 24 observed I/O boundaries. The test create hook
  closes/removes its own unreturned resource on injected post-create failure;
  this is hook ownership, not a claim that the OS returns a descriptor on error.
- 28 single-shot/persistent heap-failure paths, exact pointer/size/live-byte
  accounting and successful retries at the same destination. Heap interception
  occurs only with no workers. Small-fixture export/verify/restore observe 4/3/7
  heap allocations; this is not a universal allocation count.
- Four gated export/concurrent-commit/checkpoint/reader/destination-owner scenarios,
  including uncertain publication while the source remains usable.
- 100 eight-thread same-destination export races, with exactly one winner and
  only ownership/existing-destination conflicts for other callers.
- 28 observed-phase process-kill, destination ownership, late no-overwrite collision,
  moved-parent and input replacement/symlink/hardlink/append/valid-rewrite cases.
  These are process-crash tests, not physical device power interruptions.
- Real `luce-server` workers competing for an invitation and backup destination,
  with exactly one successful claim and export, consistent exported state and
  no overwritten backup after restart. The routes remain test-only/unauthenticated.
- Quick streaming with two 131,073-byte values; a separate full local/CI profile
  exports, verifies and restores eighteen 1 MiB values, larger than a WAL frame.

Final-source local macOS arm64 verification passed all six compiler modes and the
expanded ASan/UBSan suite, with all previous DB gates retained. The native-opt-3
larger-than-frame profile also passed. Logs: ignored `build/backup-correctness.log`,
`backup-sanitize.log` and `backup-extended.log`. After the sidecar fix, 100 repeated
full HTTP fixtures passed with each of native-opt-2 and C-debug. Earlier syntax,
sandbox-bind and pre-fix race runs remain separate failed/incomplete evidence.
Sanitizers cover the generated-C native/fault/worker/heap/oracle/process programs,
not the generated high-level Luce consumer or the HTTP fixture.

Published/tested source: `19b3d2c4854a9790e59b16c7ac256bddcaae5ebb`.
[CI run 34946319620](https://github.com/dymokomi/luce-db/actions/runs/34946319620)
passed all six modes, expanded sanitizers and the larger-than-frame backup profile
on Ubuntu 24.04 x86_64 (7m50s) and macOS 15 arm64 (9m2s). Downloaded per-platform
logs confirm the scope above; this is not inferred from an earlier revision.

The Linux native-opt-3 archive had SHA-256
`234eed3019cb5b28bcec179056d0031a8523efe6bae161f3d7839988843ec964`.
Before execution, local and remote checks verified its exact revision, 35 unique
allowlisted regular members, 34 content hashes, permissions/size bounds and all
23 ELF64 x86_64 executable headers. The complete prebuilt suite passed on an
isolated second host under the unchanged [test protections](VPS_TESTING.md):
private network/temporary storage, read-only host/input, dynamic user, 25% CPU,
512 MiB memory maximum and 180-second deadline. Reported runtime was 28.405 seconds
and CPU time 4.672 seconds. These are suite observations, not database throughput,
memory-capacity, security-review or hardware-durability guarantees.

That run included the 452 quick strict-format cases, 118 export-fault cases,
48 restore-fault cases, 28 heap-failure paths, four gated concurrency cases,
100 eight-thread destination races, 28 process/ownership/mutation cases, actual
Luce ownership, the concurrent HTTP invitation/backup/restart fixture and all
previous prebuilt suites. The eighteen-1-MiB-value profile ran locally and in CI,
not on the second host. The exact extraction stage was removed after verification;
the archive and logs were retained. The transient test unit was absent/inactive,
and before/after live-application and reverse-proxy checks matched. No live
configuration, application data or credentials changed.

Still required: application schema/migrations; package/DB/object consistency and
fresh-machine operational restore; backup signing/encryption/custody/retention;
aggregate memory/disk admission and measurements; independent review. A structurally
valid DB backup alone cannot prove that referenced Git objects or side effects exist.
