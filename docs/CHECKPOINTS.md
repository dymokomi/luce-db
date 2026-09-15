# Explicit checkpoint/compaction and format 002

Experimental native Luce Base storage. This adds a complete base snapshot to the
existing WAL strategy, not a second storage engine, backup service or SQL backend.
The public entry point is `Database.checkpoint(wait_ms=0) -> int!`; the returned
generation is unchanged. A successful call preserves records and existing snapshots,
and later commits continue at the next generation. Same-generation transactions
remain valid; stale transactions still conflict. Closed/poisoned engines reject it.

Checkpoint shares commit's bounded FIFO admission. Its wait budget ends at admission,
not at a disk-I/O deadline. No reader lock is held during encoding/sync; readers
retain immutable in-memory roots. Checkpoint is explicit, not automatically triggered
by open or commit. It drops obsolete transaction history; small journals can grow
because a base has its own framing. It does not guarantee compression or a speedup.

## Publication and failure contract

1. Hold the writer slot and committed root. Check size/generation bounds and verify
   that the filename still identifies the opened regular, single-link journal at
   its expected size. An unavailable/changed identity poisons until investigation
   and reopen; do not continue appending through an obsolete descriptor.
2. Create an exclusive random temporary sibling relative to the retained directory
   descriptor. Request mode 0600, refuse symlinks, and retry at most 128 collisions.
   Encode only current records in byte-key order, using one 65,536-byte heap buffer
   and a bounded 64-entry traversal stack. No whole-database output allocation.
3. Sync the complete temporary file, verify size and recheck the old filename's
   identity. Replace it using directory-relative `renameat`, retaining the new open
   descriptor. Verify published identity, sync the containing directory, switch
   the append descriptor and close the old descriptor. Only then publish the new
   journal-byte statistic and return success. The sidecar lock is never replaced.

The OS rename operation replaces a filename while open descriptors remain usable;
its directory-relative form anchors resolution to the retained directory.
[Linux rename documentation](https://man7.org/linux/man-pages/man2/rename.2.html).
File sync alone does not establish durability of the directory entry, so the parent
has its own sync boundary. [Linux fsync documentation](https://man7.org/linux/man-pages/man2/fsync.2.html).
The existing OS/device durability exclusions remain: in particular this is not a
macOS `F_FULLFSYNC` or physical power-loss claim.
[Apple fsync documentation](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fsync.2.html).

Allocation, entropy, create, encode, write and temporary-file sync failures known to
precede publication leave the current journal/engine usable. Cleanup attempts only
the temporary name whose device/inode still matches its descriptor, then closes it.
The original error is preserved if cleanup also fails. Such a failure or process
termination can leave a temporary sibling: it is never automatically promoted or
indiscriminately deleted. Retain/investigate it using an explicit operator procedure.

After any default rename attempt, a reported error is conservatively `uncertain`;
there is no blind retry. An internal test hook can report a known pre-attempt error
without setting its publication flag. Directory-sync, published-identity or old-file
close errors after replacement also poison the engine. Old snapshots remain readable;
new snapshots, commits and checkpoints fail until all owners close and reopen.
Reopen validates whichever complete file is visible and repeats file/directory sync.
Checkpoint never changes logical generation, even when its physical outcome is uncertain.

Replacement requests private mode 0600 (subject to umask). Prior ownership, ACLs,
xattrs and other inode metadata are not preserved; this is an explicit new inode,
not in-place editing. Directory ownership and mutation remain operator-controlled.
Identity checks catch tested discrepancies but are not protection against every
adversarial TOCTOU race. Network filesystems, shared-disk writers and forked open
engines remain unsupported. Allow disk space for old and new files together.

## Format 002

All integers are unsigned little-endian; CRC32 is IEEE CRC32, detecting accidental
corruption, **not authenticating data**. Only explicit checkpoint upgrades an existing
001 file; normal creation still writes 001 and both versions can be opened. Older
readers reject 002. There is no silent downgrade or application-schema migration.

The first 16 bytes are ASCII `LUCE-DB-WAL-002\n`. Then comes this 32-byte base prefix:

| Offset within prefix | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 4 | `CKP2` |
| 4 | 8 | Base generation |
| 12 | 8 | Exact current record count |
| 20 | 8 | Combined encoded record bytes, excluding prefix/footer |
| 28 | 4 | CRC32 of prefix bytes 0–27 |

Each current record consists of:

| Offset within record | Bytes | Meaning |
| --- | ---: | --- |
| 0 | 4 | `ROW2` |
| 4 | 4 | UTF-8 key byte length |
| 8 | 4 | Value byte length |
| 12 | 4 | CRC32 of record bytes 0–11 |
| 16 | variable | Key then value bytes |
| 16 + key + value | 4 | CRC32 of record prefix (including prefix CRC), key and value |
| 20 + key + value | 4 | `END2` |

Keys must be strictly increasing, unique, nonempty valid UTF-8 and at most 1,024
bytes; values are 0–1,048,576 bytes. At most 1,000,000 records and generation at
most 2^63−1; generation zero requires no records. Exact minimum record size is 25
bytes. Check counts, lengths and 256 MiB total-journal bound before allocating/reading
record bodies. A checkpoint base can exceed the 16 MiB transaction-frame bound.

The 16-byte completeness footer contains `BASE-END` (8 bytes), CRC32 of every byte
from file offset zero through the last record (4 bytes), then CRC32 of the first
12 footer bytes (4 bytes). Thus an empty base is 64 bytes. Replay must consume exactly
the declared record count and bytes before this footer. Missing, truncated, corrupt,
unsorted or inconsistent base data fails closed without truncation or replacement.

After the complete base, ordinary [format-001 transaction frames](STORAGE.md) start
at base generation + 1. Their existing checksum, sequence, semantic and torn-final-
transaction rules apply. There is no second base in the suffix. Checkpoint output
is deterministic for the same committed key/value state and generation.

## Verification scope

- Native and actual Luce APIs: empty/repeated/nonempty checkpoint, generation and
  size, inode replacement, snapshots/values, same-generation/stale transactions,
  subsequent commits/reopen and closed/invalid-wait/generation bounds.
- 485 independent Python struct/zlib scenarios: exact golden encoding, every small-
  fixture cut and byte corruption, semantic-invalid checksummed records and maximum
  width fields, base/torn-WAL boundaries, empty/extreme generations and streaming.
  Quick streaming covers two 131,073-byte values; the full profile uses eighteen
  1 MiB values, proving a base larger than a transaction frame. Full is local/CI only.
- 112 deterministic entropy/create/write/sync/rename/directory/close/cleanup/collision
  cases, including all 95 byte cuts in a 94-byte base and errors after publication.
  Poisoning, original-file preservation, retained locks, orphan handling and retry
  are checked. Collision sentinels must remain unchanged.
- 26 single-shot/persistent allocation-failure paths. The observed checkpoint writer
  allocates exactly one 65,536-byte buffer; replay fixture has 12 observed allocations.
  Exact pointer/size/live-byte accounting and successful retries follow every fault.
  Global heap interception occurs only with no workers. This is not process RSS.
- Four gated checkpoint/commit/checkpoint FIFO scenarios at file sync, rename and
  directory sync, including a failed publication. Readers stay usable while gated;
  after uncertainty, queued operations fail without appending through the old inode.
- Fourteen observed-phase process-kill/lock, renamed-parent, changed-path/symlink/
  hardlink/size and replacement-mode cases. They do not simulate device power loss.
- The real loopback `luce-server` fixture runs checkpoints alongside 32 competing
  invitation claims and verifies the compacted user/audit state after restart.
  It is still deliberately unauthenticated test code, never a deployable registry.

Final-source local macOS arm64 verification passed all six compiler modes, the
expanded ASan/UBSan suite and the full eighteen-1-MiB-value profile. Logs are retained
under ignored `build/checkpoint-correctness.log`, `checkpoint-sanitize.log` and
`checkpoint-extended.log`. All previous DB gates remain enabled; compiler and
standard-library sources are unchanged.

Published/tested source: `13f23bae7289c13ab9726e45d9f08212e588b998`.
[CI run 34942903244](https://github.com/dymokomi/luce-db/actions/runs/34942903244)
passed all six modes, expanded sanitizers and the larger-than-frame profile on
Ubuntu 24.04 x86_64 (4m54s) and macOS 15 arm64 (5m40s). Downloaded per-platform
logs and the sanitizer/extended step output confirm the scope above; this is not
inferred from an earlier revision's results.

The Linux native-opt-3 archive had SHA-256
`cb80bfe50f57a6fd563702a60b0f8a24efbe37bf34bf1c6742a90dad34437840`.
Before execution, local and remote checks verified its exact revision, 25 unique
allowlisted regular members, 24 content hashes, permissions/size bounds and all
15 ELF64 x86_64 executable headers. The complete prebuilt suite passed on an
isolated second host under the unchanged [test protections](VPS_TESTING.md):
private network/temporary storage, read-only host/input, dynamic user, 25% CPU,
512 MiB memory maximum and 180-second deadline. Reported runtime was 19.983 seconds
and CPU time 2.879 seconds. These are suite observations, not database throughput,
memory-capacity, security-review or hardware-durability guarantees.

That run included the 485 quick format cases, 112 deterministic publication-fault
cases, 26 allocation-failure paths, four gated concurrency cases, fourteen process/
identity cases, actual Luce ownership, the concurrent HTTP checkpoint/restart
fixture and all previous prebuilt suites. The eighteen-1-MiB-value profile ran
locally and in CI, not on the second host. A separately verified local macOS
bundle also passed the relocated prebuilt suite. Both exact extraction stages
were removed after verification; archives/logs were retained. The transient test
unit was absent/inactive, and before/after live-service and HTTPS checks matched.
No live configuration, application data or credentials changed.

Remaining work: backup/export/restore and consistency verification, application
migrations, aggregate admission, measured large-store latency/memory/recovery,
notification-based waiting/cancellation/group commit and independent review.
Checkpoint is not a backup: it intentionally discards obsolete history.
