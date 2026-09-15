# Initial validation — 2026-09-14

Implementation commit: `e6afc83`. Host: arm64 macOS. The exact Base, Luce and
server sources are pinned in `bootstrap/`. These results are local; Linux/macOS
GitHub CI is configured but has **not run**, because public publication awaits
explicit approval. No AWS instance, VPS service, proxy or DNS was changed.

`python3 tests/run.py --mode all` passed all six modes: native optimization levels
0, 1, 2 and 3, plus C debug and C release. Every mode independently rebuilt and ran:

- 1,000 index inserts/removals and 4,000 deterministic model-based AVL operations,
  checking ordering, balance, counts and retained snapshot state.
- Transaction atomicity, conflict rejection, read-your-writes, abandoned writes,
  key/value limits, malformed UTF-8, empty/binary values, value ownership and locks.
- Eight concurrent threads completing 320 two-record transactions; no lost
  increments, mismatched snapshot pairs, or mutation of an earlier empty snapshot.
- An actual high-level Luce consumer, including retained values and database reopen.
- 267 journal cases: independent golden bytes, all final-frame cut offsets,
  one-byte corruption at every position of a complete two-transaction journal,
  malformed records with valid checksums, short headers, file-type/ownership checks,
  forced partial-write error/poisoning, and process-kill/reopen checks.
- A real `luce-server` fixture with four application workers and 32 concurrent HTTP
  invitation claims: exactly one 201, 31 conflicts, overlapping handlers, matching
  user/audit records, and no invitation reuse after server restart.

`python3 tests/sanitize.py` passed AddressSanitizer + UndefinedBehaviorSanitizer on
the generated-C transaction, bounds/ownership and eight-thread concurrency tests.
This is not ThreadSanitizer coverage or a proof that all races/leaks are absent.

The sanitizer work also found a separately reproducible Base C-emission defect:
slicing a zero-initialized empty span emits null-pointer arithmetic. The package
avoids this path in its buffer implementation; checks were not disabled. The
standalone reproducer under `tests/regressions/empty_span.lucb` intentionally remains
outside the passing gate for the language audit. Native compiler sources were not
modified. Readiness/ACK lines also explicitly flush stdout to avoid backend-dependent
pipe buffering during process tests.

Not validated here: Linux execution, power interruption, fsync fault injection,
ENOSPC on a full filesystem, malicious storage directories, network filesystems,
checkpoint/restore/migration, aggregate memory pressure, fair writer scheduling,
production authentication or any performance target. Process-kill recovery does
not establish power-loss durability. The server is an unauthenticated loopback
test fixture, not a deployable registry.
