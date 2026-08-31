"""Per-household connector config intake: enabled, credential refs, trigger word, cadence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_connector_household_config"
down_revision = "0008_connector_credentials"
branch_labels = None
depends_on = None

uuid = postgresql.UUID(as_uuid=True)
timestamp = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "connector_configs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey("households.id"), nullable=False),
        sa.Column("connector", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        # Names into connector_credentials for the same household+connector —
        # references only; secret material never leaves the credential table.
        sa.Column("credential_names", postgresql.JSONB(), nullable=False),
        sa.Column("trigger_word", sa.String(100), nullable=True),
        sa.Column("poll_seconds", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", timestamp, nullable=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.UniqueConstraint("household_id", "connector"),
    )
    op.create_index("ix_connector_configs_household_id", "connector_configs", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_connector_configs_household_id", table_name="connector_configs")
    op.drop_table("connector_configs")
