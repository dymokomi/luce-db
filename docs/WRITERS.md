# Writer admission and diagnostics

Both the native Base API and the owning Luce facade support
`transaction.commit(wait_ms=0)`. The return value remains the committed generation;
the journal format is unchanged. A successful commit closes the transaction.

## Admission contract

- `wait_ms` must be an integer in 0–60,000; otherwise `invalid` is returned before
  admission or I/O. Zero preserves the original fail-fast behavior.
- A free slot with no queued waiters is acquired immediately. With contention,
  positive budgets enqueue in mutex-observed FIFO order, up to 32 waiting attempts.
  The active writer does not count toward that limit.
- `busy` means a fail-fast attempt met contention, or the waiting queue was full.
  `timed_out` means an enqueued attempt expired before acquiring the slot. Neither
  performs commit I/O, publishes changes, nor closes the transaction. A caller may
  retry the still-open transaction within its own retry budget, but it may now be stale.
- Only the queue head can acquire a released slot. New arrivals, including
  fail-fast callers, cannot overtake queued attempts. Expired waiters unlink their
  own fixed slots; later live waiters preserve their relative order.
- The budget covers admission, not disk I/O or the complete operation. Once
  admitted, commit may outlast the budget. Queued waiters check a monotonic clock
  and sleep 1 ms between checks; this is not a realtime return deadline. A delayed
  thread can observe expiry late and can delay the next waiter until it runs.
- The queue mutex protects only slot bookkeeping; it is not held during disk I/O
  or application work. Waiting occupies the caller's thread. Bound application
  workers too: this API is not asynchronous execution, cancellation, or group commit.

After admission, the engine checks poison state and validates the transaction's
original whole-database generation. A commit `conflict` requires restarting the
complete transaction from a fresh snapshot, including application conditions. FIFO
orders admission attempts, not successful transactions or retries. It does not
prevent optimistic conflicts or guarantee eventual transaction success. In the
small local eight-worker fixture, queued mode produced more stale-snapshot retries
than fail-fast mode; neither fixture is a throughput benchmark.

An append/sync error is different: `uncertain` means the outcome may recover after
reopen. Do not retry blindly or interpret closing the transaction as rollback. See
[the storage contract](STORAGE.md) for reconciliation and durability boundaries.

Transactions retain native engine ownership while waiting and through queue
release, including when the `Database` handle is already closed. Do not close or
mutate a transaction concurrently with its own commit. Join workers before closing
a shared native database handle. Managed Luce/interop references remain worker-local.

## Statistics

`database.statistics()` returns an immutable `Statistics` value in Base or Luce.
It is a diagnostic observation, not a transaction, admission reservation or an
authorization check. A closed database returns `closed`; a poisoned engine still
allows this diagnostic call.

| Field | Meaning |
| --- | --- |
| `generation` | Last published generation; empty database is 0 |
| `records` | Current published index key count |
| `journal_bytes` | Last published journal boundary, including the 16-byte header; not necessarily current file length during I/O or after an uncertain write |
| `needs_reopen` | Engine has been poisoned by uncertain I/O |
| `active_views` | Outstanding native transactions + snapshots; values alone do not count |
| `waiting_writers` | Current enqueued attempts, excluding the active writer |
| `peak_waiting_writers` | Largest observed queue count for this engine opening |
| `queued_attempts` | Total attempts actually enqueued, including later timeouts/conflicts; immediate acquisitions are excluded |
| `busy_returns` | Fail-fast contention and full-queue rejections |
| `timed_out_attempts` | Enqueued attempts that expired before admission |
| `conflicted_commits` | Generation-validation rejections at commit; excludes an `insert` conflict on an existing key |

The generation/record/byte tuple and poison flag are read under one publication
lock. Admission fields are read together under the queue lock; view/conflict
counters use native atomics. These groups are not one globally atomic snapshot.
Concurrent changes can make relationships between groups transiently inconsistent.
Admission/conflict counters and peaks reset on each engine open; they are not
persisted in the journal. Generation, record count and journal boundary recover
from the journal.

## Verification

Native tests cover FIFO order, no overtaking, head/middle/tail timeout removal,
32-slot saturation and reuse, invalid budgets, and eventual queue drain. Integration
tests run eight workers in both admission modes, check retry counter accounting,
exercise queued commits through actual HTTP handlers, and verify the Luce facade's
statistics. Ownership tests commit after closing the final database handle, while
the I/O-error fixture checks last-published diagnostics and `needs_reopen`.
These run in all six compiler modes; queue/concurrency/lifetime tests also run
under generated-C AddressSanitizer and UndefinedBehaviorSanitizer.
