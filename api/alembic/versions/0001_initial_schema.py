"""initial schema: admins, contracts, signers, contract_events, contract_event_pii

Revision ID: 0001
Revises:
Create Date: 2026-09-26

contract_events is append-only. Besides the application-level guard in
app.models.event, this migration installs a trigger that rejects UPDATE,
DELETE and TRUNCATE on contract_events and UPDATE on contract_event_pii.
Deleting from contract_event_pii stays possible for the retention role
(SPEC.md §9). Grants for the runtime roles are documented in
docs/runbooks/database-roles.md; the trigger applies regardless of role.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION contract_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'P0001', HINT = 'Write a new event instead of changing one.';
END;
$$;
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "admins",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_admins_email_lower", "admins", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "contracts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("term_end_date", sa.Date(), nullable=True),
        sa.Column("original_pdf_key", sa.Text(), nullable=False),
        sa.Column("original_pdf_sha256", sa.CHAR(64), nullable=False),
        sa.Column("original_pdf_size", sa.Integer(), nullable=False),
        sa.Column("final_pdf_key", sa.Text(), nullable=True),
        sa.Column("final_pdf_sha256", sa.CHAR(64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.Date(), nullable=True),
        sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status in ('draft','sent','viewed','signed','expired','cancelled')",
            name="ck_contracts_status",
        ),
        sa.CheckConstraint(
            "char_length(title) between 1 and 200", name="ck_contracts_title_length"
        ),
    )
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_created_by", "contracts", ["created_by"])
    op.create_index(
        "ix_contracts_created_at_id", "contracts", [sa.text("created_at desc"), sa.text("id desc")]
    )

    op.create_table(
        "signers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.CHAR(64), nullable=True),
        sa.Column("token_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("typed_name", sa.Text(), nullable=True),
        sa.Column("signature_image_key", sa.Text(), nullable=True),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_text_version", sa.Text(), nullable=True),
        sa.Column("signed_ip", postgresql.INET(), nullable=True),
        sa.Column("signed_user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_signers_token_hash",
        "signers",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("token_hash is not null"),
    )

    op.create_table(
        "contract_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "contract_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contracts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.CheckConstraint(
            "actor_type in ('admin','signer','system')", name="ck_contract_events_actor_type"
        ),
    )
    op.create_index("ix_contract_events_contract_id", "contract_events", ["contract_id"])

    op.create_table(
        "contract_event_pii",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("contract_events.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )

    # --- append-only enforcement (second line of defence after role grants) ---
    op.execute(APPEND_ONLY_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_contract_events_append_only BEFORE UPDATE OR DELETE ON contract_events "
        "FOR EACH ROW EXECUTE FUNCTION contract_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER trg_contract_events_no_truncate BEFORE TRUNCATE ON contract_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION contract_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER trg_contract_event_pii_no_update BEFORE UPDATE ON contract_event_pii "
        "FOR EACH ROW EXECUTE FUNCTION contract_events_append_only()"
    )
    # PUBLIC never gets write access to the log; per-role grants live in the runbook.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON contract_events FROM PUBLIC")
    op.execute("REVOKE UPDATE, TRUNCATE ON contract_event_pii FROM PUBLIC")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_contract_event_pii_no_update ON contract_event_pii")
    op.execute("DROP TRIGGER IF EXISTS trg_contract_events_no_truncate ON contract_events")
    op.execute("DROP TRIGGER IF EXISTS trg_contract_events_append_only ON contract_events")
    op.execute("DROP FUNCTION IF EXISTS contract_events_append_only()")
    op.drop_table("contract_event_pii")
    op.drop_table("contract_events")
    op.drop_table("signers")
    op.drop_table("contracts")
    op.drop_table("admins")
