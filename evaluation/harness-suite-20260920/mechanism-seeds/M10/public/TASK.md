# Repair the incremental synchronizer

Repair `sync.py` for a consumer that receives records out of order. A record
is identified by `id` and has a monotonically increasing `version`; an older
version must never overwrite a newer one. Duplicate messages are harmless and
`deleted: true` must remove an existing record only when its version is newer.
The public smoke check is intentionally small and passes on the seeded code;
the full public regression check exposes ordering, duplicate, and deletion
cases. Use the check output as evidence, revise the implementation, and rerun
both checks. Add a short note describing the bug and the final invariant.

Run `sh verify.sh`. Do not change the contract to make a failing assertion
disappear.
