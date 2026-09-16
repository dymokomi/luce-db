# Application schema migrations

Experimental API. Schema version is an application convention stored as an
ordinary key/value, not the WAL/base format version. A checkpoint or backup
copies metadata bytes and never runs migrations.

## Encoding

Metadata value layout, little-endian, exact EOF:

```
"LDSM" | u8 encoding=1 | u16 application_length | application UTF-8 | u64 schema_version
```

Application IDs are nonempty UTF-8 of at most 256 bytes. Schema versions are
nonnegative and at most `2^63-1`. The caller supplies the expected application
ID; a stored ID is not trusted on its own. CRC of the surrounding database
record is not a signature.

## API

```luce
from db import Database

pub func main() -> int!:
    let database = Database("registry.db")
    discard(database.initialize_schema("schema/registry", "registry"))
    let snapshot = database.snapshot()
    let version = snapshot.schema("schema/registry", "registry") else return 1
    if version == 0:
        let migration = database.begin_migration("schema/registry", "registry", 0)
        migration.put_text("user/alice", "Alice")
        discard(migration.commit())
    database.close()
    return 0
```

- `Database.initialize_schema(key, application, wait_ms=0)` writes schema zero
  only on a captured empty store. Matching existing zero metadata is a no-op.
  Nonempty unversioned data is refused; it is not silently adopted. Concurrent
  initializers use ordinary generation conflict.
- `Snapshot.schema(key, application)` decodes metadata from that snapshot.
  Missing key is `none`; corrupt or mismatched identity is an error. Do not mix
  a fresh schema query with an older retained data view.
- `Database.begin_migration(key, application, expected_version)` starts one
  exact source version and reserves the next version in the same native
  transaction. There is no callback, multi-step schedule, implicit downgrade or
  automatic retry.
- `Migration` offers transactional get/put/insert/remove and
  `commit(wait_ms=0)` / `close()`. It cannot read or mutate its metadata key.
  A conflicting ordinary writer requires a fresh migration; it must not overwrite
  a newer schema.

## Failures and exclusions

Close without commit discards the step. `conflict` at commit means restart from
a new snapshot. `uncertain` still poisons the engine; reopen and compare schema
version with records. Backup/restore preserve metadata without invoking this
API. Opening an unsupported restored schema is the application's decision.

Not provided: legacy adoption, multi-step orchestration, service-wide
maintenance mode, schema-key security, signing, or package/object consistency.
Ordinary transactions can still write the metadata key; that is a convention,
not an access-control boundary.

## Verification

Local macOS arm64 passed all six compiler modes and expanded ASan/UBSan, with
prior DB gates retained. Published/tested source:
`f6f96784764d17da1e33e8a6a6f2243e8d6e0d09`.
[CI run 35055536821](https://github.com/dymokomi/luce-db/actions/runs/35055536821)
passed on Ubuntu 24.04 x86_64 (9m16s) and macOS 15 arm64 (10m15s), including the
larger-than-frame checkpoint/backup profiles.

The Linux native-opt-3 archive had SHA-256
`4871cd0eea6e87929d03e74333ff159e21fb05696afb0fb3031f44f6b3ce1c2a`.
Before execution, local and remote checks verified its exact revision, 43 unique
allowlisted regular members, 42 content hashes, permissions/size bounds and all
29 ELF64 x86_64 executable headers. The complete prebuilt suite passed on an
isolated second host under the unchanged [test protections](VPS_TESTING.md):
private network/temporary storage, read-only host/input, dynamic user, 25% CPU,
512 MiB memory maximum and 180-second deadline. Reported runtime was 31.715 seconds
and CPU time 5.250 seconds. Exact stage removed; live applications and reverse
proxy unchanged. This is not aggregate admission, independent review or registry
readiness.
