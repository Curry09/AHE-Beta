# Synchronizer contract

The consumer is at-least-once and may deliver messages in any arrival order.
The message version is the only ordering authority for a given `id`.

Required invariants:

1. Applying a message with a version lower than or equal to the stored version
   does not change state.
2. Applying a newer value stores exactly its version and value.
3. Applying a newer deletion removes the record; an older deletion does not.
4. Replaying the same complete message list is idempotent.

The synchronizer is an in-memory boundary for this seed. Do not add a network
service or a hidden side channel. The supplied `messages.json` is a replayable
operator fixture, not a private grader.
