"""The initial migration upgrades and downgrades cleanly and installs the guards."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from alembic import command
from tests.conftest import TEST_DB_URL, alembic_config

TABLES = {"admins", "contracts", "signers", "contract_events", "contract_event_pii"}
TRIGGERS = {
    "trg_contract_events_append_only",
    "trg_contract_events_no_truncate",
    "trg_contract_event_pii_no_update",
}


def _sync_engine():  # type: ignore[no-untyped-def]
    return create_engine(TEST_DB_URL.replace("+asyncpg", "+psycopg"))


def _triggers() -> set[str]:
    with _sync_engine().connect() as conn:
        rows = conn.execute(text("select tgname from pg_trigger where not tgisinternal"))
        return {r[0] for r in rows}


def test_downgrade_then_upgrade_round_trip() -> None:
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    with _sync_engine().connect() as conn:
        assert not TABLES & set(inspect(conn).get_table_names())
    assert not _triggers() & TRIGGERS

    command.upgrade(cfg, "head")
    with _sync_engine().connect() as conn:
        insp = inspect(conn)
        assert TABLES <= set(insp.get_table_names())
        unique_email = [
            i for i in insp.get_indexes("admins") if i["name"] == "ix_admins_email_lower"
        ]
        assert unique_email and unique_email[0]["unique"]
        contract_cols = {c["name"] for c in insp.get_columns("contracts")}
        assert {"status", "original_pdf_sha256", "retain_until", "anonymized_at"} <= contract_cols
        event_cols = {c["name"] for c in insp.get_columns("contract_events")}
        assert event_cols == {
            "id",
            "contract_id",
            "event_type",
            "actor_type",
            "actor_id",
            "occurred_at",
            "metadata",
        }
        version = conn.execute(text("select version_num from alembic_version")).scalar_one()
        assert version == "0001"
    assert TRIGGERS <= _triggers()


def test_public_has_no_write_grants_on_audit_log() -> None:
    with _sync_engine().connect() as conn:
        grants = (
            conn.execute(
                text(
                    "select privilege_type from information_schema.role_table_grants "
                    "where table_name = 'contract_events' and grantee = 'PUBLIC'"
                )
            )
            .scalars()
            .all()
        )
    assert not {"UPDATE", "DELETE", "TRUNCATE"} & set(grants)
