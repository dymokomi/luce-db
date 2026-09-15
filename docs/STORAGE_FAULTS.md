# Journal I/O failures and recovery barriers

This records the recovery-fault slice before explicit compaction. Current
checkpoint semantics and its additional fault coverage are in [CHECKPOINTS.md](CHECKPOINTS.md).

September 15, 2026 UTC. Experimental native engine; not a completed checkpoint,
backup/restore, migration or production-durability milestone. Format 001 and the
public Luce API are unchanged. Compiler/server source pins remain unchanged.

## Correctness change

Previously, opening a complete existing journal skipped synchronization. After a
failed write/sync, complete bytes could still be readable; after a failed creation
directory sync, the filename could still exist. Reopen therefore could expose
recovered state without re-establishing its file and namespace durability barriers.

Replay now validates every record, optionally truncates a torn tail, synchronizes
the file, and synchronizes its retained parent directory before returning an engine.
Both barriers run even when the existing journal needs no repair. Any failure
returns no engine and releases its unpublished roots, descriptors and process lock.
The caller may retry open; errors never imply rollback. A complete unacknowledged
transaction can recover. Corrupt records still fail before repair/synchronization;
they are not silently skipped or replaced.

These are OS `fsync` boundaries, not a claim about electrical power loss or device
cache behavior. Existing macOS `fsync` versus `F_FULLFSYNC` exclusions still apply.

## Internal test boundary

`storage_io.Controls` contains a borrowed context and native callbacks for read,
write, file sync, directory sync and truncate. Each journal owns its controls value;
there is no global override. Its context must outlive the **last** engine reference,
including retained transactions/snapshots after closing the initial database handle.
Do not change callbacks/context while open/replay/writers may use them. Callbacks
must preserve the documented file/stream semantics and must not initiate a write
transaction recursively. The normal facade never exposes or selects test controls.

Read/write adapters retain Base's `io.read_exact`/`write_all` checks for short
transfers, zero progress, impossible counts and propagated errors. Test callbacks
forward to real local OS files and inject errors before/after selected operations;
there is no foreign database backend or alternate production durability mode.

## Test scope

`src/luce_db/storage_fault_tests.lucb` runs 200 scenarios on newly created disposable
paths. Cases are counted once even when they include multiple assertions/retries:

- 49 transaction-write cut points, including zero bytes and an error after the
  complete 48-byte frame reaches the OS; five additional zero/oversized write,
  before/after-sync and successful seven-byte-chunk cases.
- 17 initial-header write cut points and four before/after file/directory-sync
  failures. Partial headers remain errors and are not silently reset.
- 113 read cut points through a two-frame journal, including failure after earlier
  replay roots were built, plus premature EOF and oversized successful counts.
  Failed reads leave bytes unchanged and release process ownership.
- Four torn-tail recovery failures before/after truncation and before/after sync.
  A failed repair can already have truncated the tail; retry still validates and
  restores a usable append boundary. It never discards acknowledged transactions.
- Five complete-file reopen scenarios: repeated failures before/after each sync
  boundary, plus successful one-byte reads. Every retry repeats required barriers.
- One concurrent scenario gates an active writer at sync while another writer
  waits in FIFO admission. Readers still acquire the old snapshot; after the first
  sync reports an error, both writers return `uncertain` and the waiter performs no
  append. A different engine with different controls commits while the first is
  gated, proving the fault state is not a global database switch.

Commit cases verify unchanged acknowledged state, no premature publication even
inside sync callbacks, old-snapshot lifetime, poison diagnostics, rejected fresh
reads/retries, retained process locking, complete-versus-torn recovery outcomes
and a successful subsequent append. All previous index, transaction, admission,
ownership, independent journal oracle and actual server concurrency suites remain.

The new executable is included in all six compiler modes, generated-C ASan/UBSan
and the prebuilt bundle. Test temporary directories are automatically removed by
the Python runners. Python is test orchestration only; injected callbacks, database
logic and concurrency cases are all Luce Base.

## Evidence and remaining work

Final-source local macOS arm64 verification passed all six modes: native-opt-0
through 3, C debug and C release. Each passed all 200 scenarios and every prior
index/transaction/ownership/FIFO/eight-worker/journal/HTTP gate. Generated-C
ASan/UBSan passed the new 200 scenarios and all existing instrumented suites.
Logs are retained under ignored `build/storage-fault-correctness.log` and
`build/storage-fault-sanitize.log`.

Source `664af5f703952fc51f1a23de918025385e2e77c9` also passed
[CI 34940960779](https://github.com/dymokomi/luce-db/actions/runs/34940960779)
on Linux x86_64 and macOS arm64. Downloaded logs contain all six mode passes and
the complete 200-case/previous-suite scope; both sanitizer steps passed as well.
The verified Linux prebuilt bundle passed the complete suite in an isolated test
environment. A separate relocated macOS bundle also passed. Both temporary
extractions were removed; host-specific operator metadata is retained locally,
not added to this public report. These results do not establish the exclusions
below or complete the checkpoint/restore milestone.

Not covered: deterministic failures in open/lock/metadata/seek/close, allocator
exhaustion, actual disk-full or power-cut injection, hostile directories, network
filesystems, ThreadSanitizer, all scheduling interleavings, checkpoint rename/
replacement/reclamation, migrations, backup/restore, aggregate memory bounds,
production latency/throughput and independent storage/security review. Those are
separate gates, not implied by passing these finite fault scenarios.
