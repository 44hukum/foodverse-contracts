# Database roles

The schema is owned by the role in `DATABASE_URL` (the migration role). In
local development and in tests that same role runs the application, so the
append-only guarantee for `contract_events` rests on the trigger installed by
migration `0001` and on the guard in `app/models/event.py`.

In production, give the application and the retention job their own roles so
the grants form a third line of defence (SPEC.md §6, CLAUDE.md rule 1).
Run this once per environment as the schema owner after migrating:

```sql
-- application role (DATABASE_URL in production)
CREATE ROLE contracts_app LOGIN PASSWORD '<from the secret store>';
GRANT CONNECT ON DATABASE foodverse_contracts TO contracts_app;
GRANT USAGE ON SCHEMA public TO contracts_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON admins, contracts, signers TO contracts_app;
GRANT SELECT, INSERT ON contract_events, contract_event_pii TO contracts_app;
-- deliberately no UPDATE/DELETE on contract_events, no UPDATE/DELETE on contract_event_pii

-- retention role (RETENTION_DATABASE_URL)
CREATE ROLE foodverse_retention LOGIN PASSWORD '<from the secret store>';
GRANT CONNECT ON DATABASE foodverse_contracts TO foodverse_retention;
GRANT USAGE ON SCHEMA public TO foodverse_retention;
GRANT SELECT ON contracts, signers, contract_events, contract_event_pii TO foodverse_retention;
GRANT UPDATE ON signers, contracts TO foodverse_retention;
GRANT DELETE ON contract_event_pii TO foodverse_retention;
GRANT INSERT ON contract_events TO foodverse_retention;   -- writes signer.anonymized
```

Never grant `UPDATE`, `DELETE`, or `TRUNCATE` on `contract_events` to any
runtime role, and never drop the triggers `trg_contract_events_append_only`,
`trg_contract_events_no_truncate`, or `trg_contract_event_pii_no_update`.
