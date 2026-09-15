# luce-db

Native **Luce Base** embedded transactional storage, with an owning **Luce** API.
Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.
The first milestone is registry metadata: users, invitations, package records,
and atomic audit entries. No SQLite, foreign database engine, SQL parser, or
database subprocess is used. OS file, allocation, thread, and synchronization
primitives remain platform boundaries.

**Experimental; not ready to hold production authentication data.** This is the
first correctness-tested engine slice, not yet the planned full database service.
The HTTP fixture has **no authentication** and must never be deployed publicly.

## Luce API

Add a local dependency to your application's `luce.toml`:

```toml
[dependencies]
luce_db = "../luce-db"
```

```luce
from db import Database

pub func main(arguments: list[str]) -> int!:
    let database = Database(arguments[0])
    let tx = database.begin()
    tx.insert_text("user/alice", "Alice")
    tx.put_text("package/demo", "1.0")
    tx.commit()

    let snapshot = database.snapshot()
    let user = snapshot.get("user/alice") else return 1
    print(user.text())
    user.close()
    snapshot.close()
    database.close()
    return 0
```

The current compiler imports the manifest export `db`; `luce-db` is the repository
name, not hyphenated import syntax. See [tests/facade.luc](tests/facade.luc).

- `Database(path)`: open/create, exclusively owned by this process.
- `begin()`: isolated read-your-writes transaction. `put`/`insert` accept bytes;
  `put_text`/`insert_text` accept strings; `remove` deletes a key.
- `commit(wait_ms=0)`: returns a generation after append + OS `fsync`; closes the
  transaction on success. Zero fails fast on contention; a positive budget opts
  into bounded FIFO writer admission. Closing/releasing without committing rolls
  the transaction back unless an earlier commit returned `uncertain`.
- `snapshot()`: stable read view; `get`, `contains`, `count`, `generation`, `key_at`.
  `key_at` enumerates byte-lexicographic UTF-8 keys. Missing values return `none`;
  an empty value is present.
- `Value`: owns immutable bytes independently of its transaction/snapshot.
  `text()` rejects non-UTF-8; binary `bytes()` is lossless.
- `Database.statistics()`: committed state and observational admission counters;
  see [writer admission and statistics](docs/WRITERS.md).
- `Database.checkpoint(wait_ms=0)`: explicitly rewrite current records into a
  bounded-memory base snapshot, preserving generation and existing readers. This
  upgrades format 001 to 002; see [checkpoint semantics and failure recovery](docs/CHECKPOINTS.md).

Native Base callers explicitly release returned `interop.Reference` carriers.
Luce owns them through its normal managed-object lifetime. Explicit `close()` is
idempotent. A native byte/string view is borrowed until its owner changes/closes;
the Luce bridge copies returned strings/bytes.

## Concurrency and durability

The index is an immutable, structurally shared AVL tree in memory. Snapshot root
acquisition is O(1); lookup and index updates are O(log n). A short mutex protects
root publication; **readers do not hold it during journal sync**. Committing
writers serialize. An intervening commit invalidates the entire transaction's
generation, giving coarse-grained optimistic serializability without lost updates.

`commit(wait_ms=1000)` waits up to a 1,000 ms admission budget behind earlier
waiters. The fixed queue holds at most 32 waiting attempts plus one active writer;
new callers cannot overtake queued attempts. The default remains fail-fast.
`busy` means fail-fast contention or a full queue; use bounded retries with backoff.
`timed_out` means queued admission expired **before any commit I/O**. Both leave the
transaction open. This is not a disk-I/O timeout: after admission, append/sync runs
to completion or an I/O error. Waiters sleep 1 ms between checks, and scheduling
can delay timeout observation. No cancellation API or group commit is implemented.

`conflict` at commit means restart the complete transaction on a fresh snapshot.
`insert` also reports `conflict` when a key already exists: that is a domain conflict,
not necessarily retryable. FIFO applies to admission attempts, not successful
transactions: whole-database generation validation still rejects stale snapshots.
On the small local contention fixture, opting into the queue increased retries;
this is an ordering/backpressure feature, not a throughput improvement claim.

An append/sync error returns `uncertain` and poisons the engine. Close all database,
snapshot and transaction handles, reopen, then resolve the operation using its
application-level idempotency record. A complete unacknowledged commit can recover;
do not report rollback or retry blindly. Existing snapshots remain their original
committed views. See [the storage contract](docs/STORAGE.md).

Successful open/reopen validates replay, synchronizes the journal and its parent
directory, then exposes recovered state. Even a complete existing file may come
from an earlier unacknowledged write or failed creation sync. A failed recovery
barrier returns no engine; do not treat a failed open as rollback. See
[deterministic storage-failure tests](docs/STORAGE_FAULTS.md).

One persistent sidecar `database-path.lock` uses an OS advisory exclusive lock.
It is not a disposable PID file: **never delete it while an owner can exist**.
Snapshots/transactions retain the engine and its lock even after `Database.close`.
Values alone do not retain the file lock. Use a trusted, local filesystem directory;
network filesystems, hostile directory mutation, shared-disk writers, and forks of
an open engine are unsupported.

For `luce-server`, share only native engine state; make managed references on each
application worker. The tested Base integration is
[tests/registry_server.lucb](tests/registry_server.lucb): 4 application workers,
32 competing claims, one atomic invitation/user/audit transaction. Never share a
Luce/interop reference across worker threads. Native `Database` access may be
borrowed by workers while its owner guarantees no concurrent `close`; join workers
before closing it. Transactions and facade objects themselves are worker-local.

## Current bounds and omissions

| Limit | Initial value |
| --- | ---: |
| Journal | 256 MiB |
| One transaction frame | 16 MiB |
| Operations per transaction | 65,536 |
| Key | 1–1,024 UTF-8 bytes |
| Value | 0–1 MiB |
| Current index records | 1,000,000 |
| Active snapshots + transactions per engine | 1,024 |
| Waiting commit attempts per engine | 32 |
| Admission wait budget | 0–60,000 ms |

These are format/admission limits, **not an aggregate memory guarantee**. Old
snapshots and uncommitted transactions retain memory; callers must also bound
concurrency and lifetimes. Exceeding a limit fails explicitly. Explicit checkpoint/
compaction is available; automatic/application migration, backup/restore, page cache,
SQL, secondary-index planner, connectors,
replication, encryption at rest, credentials, sessions, or permission system yet.
The journal is replayed fully on open; it is not a disk-page B+tree. There are no
throughput or power-failure certification claims.

The independent library does not depend on `luce-server`; the **integration tests**
do. A future database service can use `luce-server`; embedded users need no listener.
An optional SQLite connector remains a separate future decision, not the native
engine's storage backend.

## Build and test

Keep `luce-base`, `luce`, `luce-server`, and `luce-db` as sibling checkouts. Compiler
and server revisions are pinned under `bootstrap/`. On arm64 macOS or x86-64 Linux:

```sh
python3 tools/bootstrap.py
python3 tests/run.py --mode native0  # earliest complete gate
python3 tests/run.py                # native opt 0–3, C debug + release
python3 tests/sanitize.py           # generated-C address/undefined-behavior checks
```

Bootstrap builds only under this repository's ignored `build/toolchain`; it never
runs the language repositories' build scripts or edits their source files. An
existing toolchain can be selected using `tests/run.py --base PATH --luce PATH`.
Python 3.10+ is only a test/bootstrap driver; its standard library provides the
independent CRC/record oracle and HTTP clients, not a runtime database dependency.
The runner needs permission to bind ephemeral **127.0.0.1** ports. No AWS credentials,
public listener, live service, external database, or cloud provisioning is needed.

Tests include AVL invariants, stable snapshots, transaction conflicts, abandoned
transactions, boundary inputs, retained values, process locks, golden record bytes,
all final-frame truncation offsets, complete-frame byte corruption, invalid records
with valid checksums, write failures, process-kill recovery, 8-thread updates,
FIFO/no-overtaking admission, head/middle/tail timeouts, queue saturation/reuse,
both fail-fast and queued commits, public statistics, high-level Luce ownership,
and real concurrent HTTP clients plus server restart. The 200 deterministic
storage-I/O cases additionally cover byte-cut failures, short/invalid transfers,
file/directory sync and truncation failures, reopen barriers, retained snapshots,
queued writer poisoning and per-store control isolation.
CI repeats all six modes on Linux and macOS; see its run results for current status.
The initial local results and untested boundaries are in [docs/VALIDATION.md](docs/VALIDATION.md).
`tests/regressions/empty_span.lucb` is a known-failing upstream C-emission reproducer,
not a passing package test. The buffer implementation avoids that compiler path;
the workspace language-audit document records the issue without changing Base.

## Next build order

1. Harden storage: extend the existing journal I/O fault controls to checkpoint/
   replacement boundaries as those are implemented; measure memory/latency,
   notification-based waiting and optional group commit. The first
   bounded FIFO admission implementation is complete; it currently uses sleep polling.
2. Extend explicit checkpoint/compaction with verified backup/restore, application
   migrations, measured recovery/resource limits and an explicit aggregate memory
   budget. Disk-page indexing remains a later storage-layout decision.
3. Define native provider interfaces and typed users/invitations/packages repositories;
   add a worker-safe facade factory usable from high-level Luce server applications.
4. Build `luce-auth` on audited native cryptography and atomic one-use invitations;
   never turn this unauthenticated fixture into a deployed authentication endpoint.
5. Build `luce-pkg-server` + `luce-cli` on the same repositories and authorization;
   settle external Git versus a native Git subset explicitly. HTTP sits behind the
   existing VPS HTTPS proxy. Remote native clients still need verified HTTPS.
6. Continue isolated tests on the approved existing VPS, with resource limits,
   temporary data and cleanup; no production DNS/proxy/service changes. A deployable
   staging service additionally needs authentication, backup/restore and review.
