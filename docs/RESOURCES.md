# Aggregate process resource measurements

This is a measurement slice, not a production memory budget, fair scheduler or
independent capacity claim. Existing writer FIFO admission remains the only
in-engine admission control.

`python3 tests/check_resources.py build/native3` records `wait4` peak RSS for
the writers, eight-thread concurrency, backup and schema-migration binaries.
The regression ceiling is 256 MiB per child. OS RSS includes runtime/startup;
it is not a ledger of live tree nodes.

Not covered: process-wide server admission, disk quotas, checkpoint of
multi-gigabyte stores, or calibrated production limits.
