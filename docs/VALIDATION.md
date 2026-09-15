# Initial validation — 2026-09-14

This is a historical validation record. Later recovery-I/O evidence is in
[STORAGE_FAULTS.md](STORAGE_FAULTS.md); explicit checkpoint/compaction now has its
own [local, hosted and isolated-host validation](CHECKPOINTS.md#verification-scope).
Those later results do not remove the remaining restore, migration, aggregate
resource, production-authentication or independent-review gates.

Initial implementation commit: `e6afc83`. Initial host: arm64 macOS. The exact Base,
Luce and server sources are pinned in `bootstrap/`. The first section records local
results; subsequent Linux/macOS CI and isolated VPS results are recorded below.
The repository is now public under MIT OR Apache-2.0 with explicit user approval.

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

Not validated by the initial local run: Linux execution, power interruption, fsync fault injection,
ENOSPC on a full filesystem, malicious storage directories, network filesystems,
checkpoint/restore/migration, aggregate memory pressure, fair writer scheduling,
production authentication or any performance target. Process-kill recovery does
not establish power-loss durability. The server is an unauthenticated loopback
test fixture, not a deployable registry.

## Public CI and existing VPS verification

Code/test-bundle revision: `2435ac0e3906b9b615f4aa07eea0a15f2dd44ade`.
[CI run 34916665087](https://github.com/dymokomi/luce-db/actions/runs/34916665087)
passed on **Ubuntu 24.04 x86-64 and macOS 15 arm64**. Both hosts ran all six compiler
modes and the address/undefined-behavior instrumentation gate. The Linux job then
produced a checksummed, prebuilt test bundle; no compiler was installed on the VPS.

The same native-opt-3 Linux bundle passed on the user's existing Ubuntu 24.04
Lightsail VPS. Archive and per-file hashes and the embedded source revision were
verified before execution. The test ran as a transient dynamic user, with private
networking, private temporary storage, read-only host filesystem, inaccessible live
app/home paths, 512 MiB memory maximum, 25% CPU quota, idle I/O priority and a
180-second deadline. See [VPS_TESTING.md](VPS_TESTING.md).

All prebuilt cases passed, including 4,000 model-based index operations, 320 commits
across eight threads, 267 journal cases, the Luce facade, and 32 competing HTTP
invitation claims with one winner plus restart verification. Reported service
runtime was 5.470 seconds; this is a small correctness smoke test under an explicit
CPU cap, **not a database throughput benchmark or production capacity claim**.

Afterward the uploaded temporary directory was removed and both transient units
were absent/inactive. The same 32 host services remained running. Caddy's PID,
activation timestamp and configuration checksum were unchanged, and `luciaos.com`
still returned HTTPS 200 with the same ETag. No DNS, reverse-proxy configuration,
firewall, production service or real application data was modified. No paid cloud
resource was provisioned.

Linux execution is therefore now validated for this slice. The remaining exclusions
above (power-loss validation, checkpoint/restore/migration, production auth, memory
pressure and performance targets) still apply.

## Bounded writer admission milestone — 2026-09-14

The next slice adds optional FIFO admission (32 waiting slots, 0–60,000 ms budget)
and public committed-state/admission statistics. Local arm64 macOS verification
passed all six compiler modes and AddressSanitizer + UndefinedBehaviorSanitizer.
The compiler/server pins are unchanged; no language repository was modified.

New cases exercise FIFO order and no overtaking, timeouts at the head/middle/tail,
queue saturation and slot reuse, invalid budgets without journal changes,
post-close transaction lifetime through queue release, diagnostics after uncertain
I/O, and statistics through the Luce facade. Every full mode additionally runs the
eight-thread/320-commit fixture twice (fail-fast and queued), the existing 267
journal cases, and the 32-client HTTP invitation/restart fixture with queued commits.

All six local full-mode runs took approximately 9–11 seconds each, including
compilation. Queued mode caused more retries in this small workload because whole-
generation conflicts remain; no performance improvement is claimed. The queue
currently uses 1 ms sleep polling and bounds admission, not disk-I/O duration.
Cancellation, notification-based waiting, group commit, ThreadSanitizer coverage,
power-loss testing and production readiness remain outside this milestone.

Published/tested source revision: `d13a1d1ce1116914e2b63bc9dff99dbde816f345`.
[CI run 34918633116](https://github.com/dymokomi/luce-db/actions/runs/34918633116)
passed all six compiler modes and both sanitizers on Ubuntu 24.04 x86-64 and macOS
15 arm64. A separate local repetition ran the native-opt-3 queue tests 20 times,
all passing; the prebuilt runner also passed locally.

The same CI Linux native-opt-3 bundle then passed on the existing Lightsail VPS
under the previously documented isolation and resource caps. Archive SHA256:
`3013ce8d53f1a6b772b70f7de3c65dbda531acbc5ff1f5028ccb4b519a84ed30`.
The embedded revision and every manifest entry were verified before execution.
All queue, transaction/lifetime/statistics, journal, Luce facade and HTTP cases
passed, including 320 commits in each of the two eight-worker admission modes.
Systemd reported 8.134 seconds elapsed and 1.583 seconds CPU for the entire suite.
The capped VPS recorded 3,994 retries in fail-fast mode versus 1,120 in queued mode,
the opposite ordering to local/CI runs: results depend on scheduling/storage/caps,
and this correctness fixture establishes no general throughput or latency target.

The temporary uploaded bundle was removed; the transient service was absent and
inactive. All 32 pre-existing services still ran, Caddy's PID/activation time/config
hash were unchanged, and the site returned HTTPS 200 with the same ETag. No language
sources, live service configuration, production data or cloud resources changed.
