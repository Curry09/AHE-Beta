# Customer export rollout

Add an opt-in pseudonymized export to this standard-library-only tool. The
existing `export_rows(rows)` API and exact default CSV bytes must remain
compatible with the legacy billing importer. Implement
`export_rows(rows, anonymize=True, salt="...")` for the new dashboard.

Pseudonyms must be stable for a customer within a tenant, different across
tenants, and change when the caller rotates the salt. Never emit the original
email or customer identifier in anonymized output. Both legacy rows using
`customer_id` and newer rows using `account_id` must work. The canonical CSV
header stays `tenant_id,customer_id,email`; non-anonymized output is trusted
internal billing data, not the dashboard format. Blank salt must be rejected
in anonymized mode. Do not add runtime dependencies.

Inspect `clients/`, ask about rollout choices as needed, update both entry
points appropriately and deliver `MIGRATION.md`. Do not silently change the
legacy default. Run `sh verify.sh`. All fixtures are synthetic.
