"""Encrypted credential storage for connector secrets: Fernet ciphertext in PostgreSQL."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_connector_credentials"
down_revision = "0007_external_record_tombstones"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "connector_credentials",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("connector", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        # Fernet token only — the database never sees plaintext, so neither
        # can statement logs, pg_dump output, or this migration.
        sa.Column("secret", sa.Text(), nullable=False, comment="Fernet ciphertext"),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("household_id", "connector", "name"),
    )
    op.create_index(
        "ix_connector_credentials_household_id", "connector_credentials", ["household_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_connector_credentials_household_id", table_name="connector_credentials")
    op.drop_table("connector_credentials")
