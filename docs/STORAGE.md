# Experimental journal format 001

Both format 001 and checkpoint-capable [format 002](CHECKPOINTS.md) are supported.
Normal creation still writes 001; only an explicit checkpoint upgrades a file.
The following transaction frame definition is shared by both versions.

This format is intentionally small and documented for independent verification.
It is not a stable public format until migration/checkpoint design is complete.
All integers are unsigned little-endian. CRC32 is IEEE CRC32 (the same result as
Python `zlib.crc32`), an accidental-corruption check, **not authentication**.

The 16-byte header is ASCII `LUCE-DB-WAL-001\n`. Each transaction consists of:

| Offset | Bytes | Field |
| --- | ---: | --- |
| 0 | 4 | ASCII `TXN1` |
| 4 | 4 | Payload length |
| 8 | 8 | Generation, starting at 1 and increasing by exactly 1 |
| 16 | 4 | Operation count |
| 20 | 4 | CRC32 of bytes 0 through 19 |
| 24 | payload length | Operations |
| 24 + payload length | 4 | CRC32 of the complete preceding frame prefix + payload |
| 28 + payload length | 4 | ASCII `END1` |

Each operation is: kind u8 (1 = put, 2 = delete), key length u32, value length u32,
key bytes, value bytes. Deletion requires zero value bytes. Replay validates UTF-8,
lengths, operation count, generation, exact payload consumption, and both checksums.
Repeated keys within a transaction apply in order. There is no hidden struct dump,
host endianness dependency, pointer serialization, compression, or foreign codec.

Commit sequence: acquire the writer slot (fail-fast by default, optionally through
the [bounded FIFO admission queue](WRITERS.md)); validate snapshot generation and
poison state; build a complete frame; append the entire frame; `fsync`; publish an
immutable new root under the short head lock; return the generation. Allocation
failure and admission rejection/timeout occur before append and cannot publish
anything. An admission deadline does not interrupt append or sync.

On file creation, write the header. After a complete successful replay, including
any required tail truncation, sync the journal and its retained parent directory
before exposing an engine. This applies to every open, not just new files or torn
tails: existing complete bytes may come from an earlier failed/unacknowledged sync,
and an existing filename may come from an unsuccessful creation directory sync.
Failure at either recovery barrier closes the unpublished engine; retrying open
revalidates and repeats both barriers. No directory sync is needed for an ordinary
append to an already established filename. Final
database/lock symlinks are not followed; the database must be regular with one link.
Parents must be operator-controlled. The sidecar stays present after clean close.
File/lock creation requests mode 0600; existing file permissions are not rewritten.

On recovery, replay complete valid records. A partial final prefix (<24 bytes) or
a checksum-valid prefix with an incomplete body/trailer is a torn tail: truncate
to the last committed boundary and sync before accepting new operations. A corrupt
complete frame, corrupt full prefix, unsupported header, or invalid semantic record
fails closed **without modifying the journal**. A partial initial file header is
an error, not an automatically reset empty database. Keep the original and investigate.

Open retains the directory descriptor through engine lifetime along with the file
and process lock. Read/write/file-sync/directory-sync/truncate operations have an
internal per-store native callback boundary for deterministic tests; the Luce API
uses only the standard OS implementation. See [STORAGE_FAULTS.md](STORAGE_FAULTS.md)
for callback lifetime rules, exact covered failures and exclusions.

Failure during append or sync is an **uncertain commit outcome**, even if this
process has not published a root. New snapshots/commits fail until every engine
handle is closed and the database is reopened. A complete valid record can recover
even when its caller never saw success. Applications therefore need idempotency
keys written in the same transaction as effects. Old snapshots remain valid and
may still read their earlier state. They must not be mistaken for fresh reads.

The durability boundary is the OS/device contract of `fsync`. The tests cover
process termination and write errors, not electrical power loss, dishonest device
caches, filesystem bugs, loss of the host, or cross-machine replication. In
particular macOS `fsync` is not a claim of `F_FULLFSYNC` drive-cache flushing.
Do not use production secrets without security review, backup and restore tooling,
and deployment-specific durability testing.
