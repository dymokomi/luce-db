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
python3 tests/run.py --mode native0 --base ../luce-base/build/luce-base --luce ../luce/build/luce
```
