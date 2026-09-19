# luce-db

Database **server** over [luce-prism](../luce-prism). Prism is the storage engine
(documents, WAL, flock). This package is the process: open a store, listen,
accept clients, require a token.

Dual-licensed under [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE).

```toml
[dependencies]
luce_db = "../luce-db"
luce_prism = "../luce-prism"
```

```luce
from db import Database
from prism import Value

pub func main(arguments: list[str]) -> int!:
    let database = Database.open(arguments[0], "secret")
    let tx = database.begin()
    tx.add("/notes", "file")
    tx.set("/notes", "text", Value.text("hello"))
    discard(tx.commit())
    let snap = database.snapshot()
    print(snap.get("/notes", "text").text_at())
    return 0
```

- `Database.open(path, token)` — exclusive owner (`Store.open` + flock). Token is required.
- `begin` / `snapshot` — Prism sessions on that store.
- `listen` / `serve` — Unix socket `{path}.sock`.
- `Database.connect(socket, token)` — local Unix client; same token.
- `listen_tls(host, port)` — TCP TLS 1.3 (ChaCha20-Poly1305, pinned issuer).
- `tls_issuer_x` / `tls_issuer_y` — P-256 key to pin on clients.
- `Database.connect_tls(host, port, token, issuer_x, issuer_y)`.
- `bake` — apply unbaked layers (owner only).

There is no byte-key KV API. The Unix path uses a shared-secret token. Remote
clients use TLS plus the same token. Not `luce-auth` and not a public CA store.

```sh
python3 tools/bootstrap.py
python3 tests/run.py --mode all
```

Check out sibling `luce-base`, `luce`, `luce-prism`, `luce-tls` and
`luce-crypto` at the revisions in `bootstrap/` first. Bootstrap verifies those
revisions and builds compilers inside this package without editing language
sources. Alternatively, pass `--base PATH --luce PATH` to the test runner.
Compiler caches default to `build/cache`; `LUCE_CACHE` can override that location.

The default test matrix covers native optimization levels 0–3 and the C debug/
release backends. Each mode exercises the native DB facade, loopback TLS and an
actual Luce consumer, with runner-owned temporary database paths. These are
functional smoke tests, not durability/fault, sanitizer or shutdown guarantees.
Prism's detached TLS worker and connection lifecycle still needs hardening before
production use. The removed standalone KV engine's checkpoint/backup/resource
tests do not validate this Prism-backed implementation.
