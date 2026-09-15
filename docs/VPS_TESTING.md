# Isolated existing-host tests

The public CI workflow produces `luce-db-smoke-x86_64-linux` only after all Linux
compiler-mode tests and sanitizer checks pass. It contains fifteen test executables,
five Python standard-library-only scripts, both license texts, the Git revision
and per-file hashes.
These are test artifacts, not an installation package or an authenticated service.

For an explicitly approved Ubuntu 24.04 x86-64 host:

1. Select a successful CI run for a reviewed commit. Download its test artifact with
   `gh run download RUN_ID --repo dymokomi/luce-db --name luce-db-smoke-x86_64-linux`.
   Inspect archive members and the embedded revision. Record the archive SHA256.
2. Read-only preflight: verify SSH host identity, live service status, available
   memory/disk, Python and systemd. Record proxy configuration checksum/activation
   time. Do not reuse a deployment script that restarts real services or installs packages.
3. Upload only that public bundle into a unique `mktemp -d` directory. Check the
   archive hash again, extract without restoring archive ownership, then verify
   `SHA256SUMS` and `REVISION`. No credentials or live datasets go into the bundle.
4. Use a transient systemd service with `--wait --pipe --collect`; run
   `tests/run_prebuilt.py` against its `bin` directory under the protections below.
   Bind the bundle read-only at `/tmp/luce-db-input` inside the private namespace.
   The staging directory must be readable/traversable by the dynamic UID and contain
   only public test files. Do not weaken home/live-app protections to make it readable.
5. Check the exit status, preserve the test log, verify the transient unit has gone,
   and delete only the exact validated staging directory. Recheck live services,
   proxy checksum/PID and public HTTPS. Never use a broad `/tmp` cleanup command.

Settings used in the initial successful test:

| Setting | Value |
| --- | --- |
| Identity | `DynamicUser=yes`, no capabilities, `NoNewPrivileges=yes` |
| Network | `PrivateNetwork=yes`; test listeners and clients share only this namespace |
| Filesystem | `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`, read-only input bind |
| Existing application data | `InaccessiblePaths=/opt/apps` |
| Additional restrictions | `PrivateDevices=yes`, `RestrictNamespaces=yes`, core dumps disabled |
| Memory | `MemoryHigh=384M`, `MemoryMax=512M`, `MemorySwapMax=0` |
| CPU/I/O | `CPUQuota=25%`, `Nice=19`, `IOSchedulingClass=idle` |
| Process/time limits | `TasksMax=64`, `RuntimeMaxSec=180`, `LimitFSIZE=512M` |
| Python | `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1` |

The runner creates and removes its own databases in private temporary directories;
it does not accept production database paths. Python drives independent checks;
all database and HTTP server internals in the test binaries remain Luce Base.
If a sandbox setting is unavailable, stop and review the isolation rather than
silently running these fixtures unconfined on a live server.

The namespace/lifecycle controls follow the host's
[systemd 255 execution documentation](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml).
The concrete successful run and remaining validation limits are in
[VALIDATION.md](VALIDATION.md). This does not authorize general production deployment,
public listener exposure, installation of dependencies, or cloud provisioning.
