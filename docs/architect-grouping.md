# Architect Proposal Grouping

Proposal grouping assigns related requirements to the same Architect, reducing duplicate handling while preserving the context that needs to be discussed together. The classifier only decides which proposals are suitable for joint synthesis; proposal publication, closure, and admission remain the responsibility of the existing process.

## Configuration

Set the following strategy in the experiment JSON, then prepare and start a new experiment:

```json
{
  "policies": {
    "architect_grouping": true
  }
}
```

This is the configuration fragment merged into the complete experiment definition. The strategy defaults to `false`, the enabled value is fixed at `prepare`, and it is passed to the controller by the local and E2B backends. `ARCHITECT_GROUPING` in the host or credential file does not override the experiment configuration. Existing runs continue to use their frozen settings.

Grouping also applies to single-user experiments. The number of Architects is specified by `roles.architect`; it can likewise be enabled when U1 produces multiple related proposals. See the [configuration reference](CONFIGURATION.md#runtime-policies) for the complete fields.

## Scheduling Process

Requests are processed in the following order in non-final rounds:

1. Wait for all Triage operations in the round to complete, and collect open proposals that are not from PM.
2. Call the grouping model once, providing proposal IDs, titles, and summaries of at most 1200 characters.
3. Validate the returned `{"groups": [[1, 2], [3]]}`, ensuring that every input ID appears exactly once.
4. Split each group into tasks of at most 6 items per batch. Batches from the same group are processed sequentially by the same Architect instance; different groups may run in parallel.
5. Pass the synthesis results to the Owner for admission, then wait for code delivery.

Divergent PM retains an independent Owner admission path. A single source is retained for the Owner, and a synthesis proposal is not forcibly generated. Each batch may reference only its own sources and continues to use the `source_proposals` and `covers` checks.

## Failure Handling and Records

The grouping model uses the Architect connection configuration, with an output limit of 16384 tokens, a request timeout of 300 seconds, and no automatic SDK retries. If the request fails, the output is truncated, the JSON is invalid, or IDs are duplicated or omitted, the scheduler falls back to serial synthesis sorted by ID, with at most 6 items per batch.

When an Architect batch fails, the error is recorded and the remaining batches continue; unprocessed open sources remain in the queue. When reading the Gitea queue, pagination is traversed; a pagination read failure raises an error, and grouping does not continue using an incomplete proposal list.

Grouping inputs, model outputs, durations, fallback reasons, and batch results are stored under `architect_grouping/` in the records for the current round and role; usage is included in the existing Token statistics. A warning is issued if writing the grouping records fails, while proposal processing continues.

6 items per batch is a quantity limit and does not guarantee that any model's context window will be satisfied. Batches from the same group still call the model independently and do not share a continuous conversation; grouping itself also does not guarantee that proposals have undergone semantic deduplication. Actual effects should be evaluated together with the proposals and delivery results.

## Development Verification

After installing the development dependencies, the relevant regression tests can be run:

```bash
uv run --locked --extra experiments --extra dev pytest backend/tests/demand/test_grouped_architect.py backend/tests/loop/test_architect.py backend/tests/test_stage_resume_e2e.py
```
